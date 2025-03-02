import traceback
import discord
from discord import app_commands
import sqlite3
import logging
import re

from database.db_manager import get_db_connection
from services.api_service import fetch_collection_log
from services.leaderboard_service import update_leaderboard, refresh_leaderboard_display
from utils.helpers import is_admin_user  # Import helper to check admin status

logger = logging.getLogger()


def register_user_commands(bot):
    """Register all user commands with the bot"""

    # ➤ /link command
    @bot.tree.command(
        name="link", description="Link a RuneScape username to your Discord account"
    )
    @app_commands.describe(
        username="Your RuneScape username",
        account_type="Select your account type (Iron, HCIM, UIM, GIM, Main)",
        emoji="(Optional) An emoji to display next to your name",
    )
    @app_commands.choices(
        account_type=[
            app_commands.Choice(name="IM", value="Iron"),
            app_commands.Choice(name="HCIM", value="HCIM"),
            app_commands.Choice(name="UIM", value="UIM"),
            app_commands.Choice(name="GIM", value="GIM"),
            app_commands.Choice(name="Main", value="Main"),
        ]
    )
    async def link(
        interaction: discord.Interaction,
        username: str,
        account_type: str,
        emoji: str = None,
    ):
        guild_id = interaction.guild_id

        # Ensure emoji is valid
        if emoji:
            # Check if it's a custom emoji
            custom_emoji_pattern = r"<a?:\w+:\d+>"
            if not any(ord(c) > 255 for c in emoji) and not re.match(
                custom_emoji_pattern, emoji
            ):
                await interaction.response.send_message(
                    "❌ Invalid emoji! Please use a real emoji or a valid custom emoji.",
                    ephemeral=True,
                )
                return

        # Insert into database
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO linked_accounts (guild_id, discord_id, username, account_type, emoji) VALUES (?, ?, ?, ?, ?)",
                    (guild_id, interaction.user.id, username, account_type, emoji),
                )
                conn.commit()
                await interaction.response.send_message(
                    f"✅ Linked **{username}** as a **{account_type}**! Fetching collection log data...",
                    ephemeral=True,
                )
                logger.info(
                    f"User {interaction.user} linked account {username} as {account_type} in guild {guild_id}."
                )

                # After linking, update leaderboard
                result = await fetch_collection_log(username)
                if result is not None:
                    score = result["score"]
                    rank = result["rank"]

                    # Even if score is -1, add to the leaderboard
                    cursor.execute(
                        "INSERT INTO leaderboard (guild_id, username, collection_log_total, hiscore_rank) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(guild_id, username) DO UPDATE SET collection_log_total = ?, hiscore_rank = ?",
                        (guild_id, username, score, rank, score, rank),
                    )
                    conn.commit()

                    # Log with specific note if score is -1
                    if score == -1:
                        logger.info(
                            f"Added {username} to leaderboard with score -1 (below hiscores threshold) in guild {guild_id}"
                        )
                        await interaction.followup.send(
                            f"✅ Added **{username}** to the leaderboard! Their collection log count is below 500 items.",
                            ephemeral=True,
                        )
                    else:
                        logger.info(
                            f"Leaderboard updated for {username} with score {score} in guild {guild_id}"
                        )
                        await interaction.followup.send(
                            f"✅ Added **{username}** to the leaderboard with **{score}** collection log items!",
                            ephemeral=True,
                        )

                    # Just refresh the display instead of a full update
                    await refresh_leaderboard_display(guild_id)
                else:
                    await interaction.followup.send(
                        f"✅ Linked **{username}**, but couldn't fetch collection log data. The user will be added on the next scheduled update.",
                        ephemeral=True,
                    )

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "❌ You have already linked this username!", ephemeral=True
            )
            logger.warning(
                f"User {interaction.user} tried to link an already linked account: {username}"
            )

    # ➤ /unlink command
    @bot.tree.command(
        name="unlink", description="Unlink one of your linked RuneScape usernames"
    )
    @app_commands.describe(username="The username you want to unlink")
    async def unlink(interaction: discord.Interaction, username: str):
        guild_id = interaction.guild_id
        is_admin = is_admin_user(interaction)

        with get_db_connection() as conn:
            cursor = conn.cursor()

            if is_admin:
                # Admins can unlink any username
                cursor.execute(
                    "SELECT discord_id FROM linked_accounts WHERE guild_id = ? AND username = ?",
                    (guild_id, username),
                )
                owner_info = cursor.fetchone()
                
                if not owner_info:
                    await interaction.response.send_message(
                        f"❌ Username **{username}** is not linked to any user.", 
                        ephemeral=True
                    )
                    return

                # Delete the username regardless of who linked it
                cursor.execute(
                    "DELETE FROM linked_accounts WHERE guild_id = ? AND username = ?",
                    (guild_id, username),
                )
                
                try:
                    owner = await bot.fetch_user(owner_info['discord_id'])
                    owner_mention = owner.mention
                    owner_name = str(owner)
                except:
                    owner_mention = "Unknown User"
                    owner_name = "Unknown User"
                
                admin_message = f" (owned by {owner_name})"
            else:
                # Regular users can only unlink their own usernames
                cursor.execute(
                    "DELETE FROM linked_accounts WHERE guild_id = ? AND discord_id = ? AND username = ?",
                    (guild_id, interaction.user.id, username),
                )
                admin_message = ""

            if cursor.rowcount > 0:
                conn.commit()
                await interaction.response.send_message(
                    f"✅ Unlinked **{username}**{admin_message}!", ephemeral=True
                )
                logger.info(
                    f"User {interaction.user} unlinked account {username} in guild {guild_id}. Admin: {is_admin}"
                )

                # Also remove from leaderboard
                cursor.execute(
                    "DELETE FROM leaderboard WHERE guild_id = ? AND username = ?",
                    (guild_id, username),
                )
                conn.commit()

                # Just refresh the display without fetching new data
                await refresh_leaderboard_display(guild_id)
            else:
                if is_admin:
                    # This shouldn't happen for admins due to our earlier check
                    await interaction.response.send_message(
                        f"❓ Failed to unlink **{username}**.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ You can only unlink usernames you linked yourself.",
                        ephemeral=True,
                    )
                    logger.warning(
                        f"User {interaction.user} tried to unlink an account they didn't link: {username} in guild {guild_id}"
                    )

    # ➤ /list command
    @bot.tree.command(
        name="list", description="View all RuneScape usernames linked to your account"
    )
    @app_commands.describe(
        user="(Optional) The user whose linked usernames you want to view"
    )
    async def list_accounts(
        interaction: discord.Interaction, user: discord.Member = None
    ):
        guild_id = interaction.guild_id

        target_user = user if user else interaction.user

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username, account_type, emoji FROM linked_accounts WHERE guild_id = ? AND discord_id = ?",
                (guild_id, target_user.id),
            )
            accounts = cursor.fetchall()

            if not accounts:
                await interaction.response.send_message(
                    f"❌ {target_user.mention} has not linked any usernames.",
                    ephemeral=True,
                )
                return

            msg = f"**Linked usernames for {target_user.mention}:**\n" + "\n".join(
                [
                    f"➤ {username} ({account_type}) {emoji or ''}"
                    for username, account_type, emoji in accounts
                ]
            )
            await interaction.response.send_message(msg, ephemeral=True)
            logger.info(
                f"User {interaction.user} requested list of linked accounts for {target_user} in guild {guild_id}."
            )

    # ➤ /whois command
    @bot.tree.command(
        name="whois",
        description="Shows which Discord user a specific RuneScape username is linked to",
    )
    @app_commands.describe(username="The RuneScape username you want to look up")
    async def whois(interaction: discord.Interaction, username: str):
        guild_id = interaction.guild_id

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT discord_id FROM linked_accounts WHERE guild_id = ? AND username = ?",
                (guild_id, username),
            )
            result = cursor.fetchone()

            if result:
                discord_id = result["discord_id"]
                user = await bot.fetch_user(discord_id)
                await interaction.response.send_message(
                    f"🔍 **{username}** is linked to Discord user **{user}** ({user.mention}).",
                    ephemeral=True,
                )
                logger.info(
                    f"User {interaction.user} looked up whois for {username} in guild {guild_id}."
                )
            else:
                await interaction.response.send_message(
                    f"❌ No Discord user is linked to the username **{username}**.",
                    ephemeral=True,
                )
                logger.warning(
                    f"User {interaction.user} tried to look up whois for non-linked username: {username} in guild {guild_id}"
                )

    # ➤ /update command
    @bot.tree.command(
        name="update", description="Update the details of your linked RuneScape account"
    )
    @app_commands.describe(
        username="The RuneScape username you want to update",
        new_username="(Optional) Update the capitalization of your username",
        account_type="(Optional) Change your account type",
        emoji="(Optional) Update or remove the emoji (use 'none' to remove)",
    )
    @app_commands.choices(
        account_type=[
            app_commands.Choice(name="IM", value="Iron"),
            app_commands.Choice(name="HCIM", value="HCIM"),
            app_commands.Choice(name="UIM", value="UIM"),
            app_commands.Choice(name="GIM", value="GIM"),
            app_commands.Choice(name="Main", value="Main"),
        ]
    )
    async def update_account(
        interaction: discord.Interaction,
        username: str,
        new_username: str = None,
        account_type: str = None,
        emoji: str = None,
    ):
        guild_id = interaction.guild_id

        # Verify ownership
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM linked_accounts WHERE guild_id = ? AND discord_id = ? AND LOWER(username) = LOWER(?)",
                (guild_id, interaction.user.id, username),
            )
            account = cursor.fetchone()

            if not account:
                await interaction.response.send_message(
                    f"❌ You don't have an account linked with the username **{username}**.",
                    ephemeral=True,
                )
                return

            # Start building update data
            update_data = []
            update_params = []
            changes = []

            # Handle username case update
            if new_username and new_username.lower() == username.lower():
                update_data.append("username = ?")
                update_params.append(new_username)
                changes.append(f"Username: **{username}** → **{new_username}**")
            elif new_username:
                # Check if the new username already exists in the database
                cursor.execute(
                    "SELECT discord_id FROM linked_accounts WHERE guild_id = ? AND LOWER(username) = LOWER(?) AND discord_id != ?",
                    (guild_id, new_username, interaction.user.id),
                )
                existing_user = cursor.fetchone()

                if existing_user:
                    # Username already exists for another user
                    await interaction.response.send_message(
                        f"❌ Cannot update to username **{new_username}** as it's already linked to another Discord user.",
                        ephemeral=True,
                    )
                    return

                # Username is available, proceed with update
                update_data.append("username = ?")
                update_params.append(new_username)
                changes.append(f"Username: **{username}** → **{new_username}**")

            # Handle account type update
            if account_type and account_type != account["account_type"]:
                update_data.append("account_type = ?")
                update_params.append(account_type)
                changes.append(
                    f"Account type: **{account['account_type']}** → **{account_type}**"
                )

            # Handle emoji update
            if emoji is not None:
                if emoji.lower() == "none":
                    update_data.append("emoji = NULL")
                    changes.append("Emoji: Removed")
                else:
                    # Validate emoji
                    custom_emoji_pattern = r"<a?:\w+:\d+>"
                    if not any(ord(c) > 255 for c in emoji) and not re.match(
                        custom_emoji_pattern, emoji
                    ):
                        await interaction.response.send_message(
                            "❌ Invalid emoji! Please use a real emoji or a valid custom emoji.",
                            ephemeral=True,
                        )
                        return

                    update_data.append("emoji = ?")
                    update_params.append(emoji)
                    current_emoji = account["emoji"] or "none"
                    changes.append(f"Emoji: {current_emoji} → {emoji}")

            # If nothing to update
            if not update_data:
                await interaction.response.send_message(
                    "❓ No changes specified. Your account details remain the same.",
                    ephemeral=True,
                )
                return

            # Build and execute the update query
            update_query = f"UPDATE linked_accounts SET {', '.join(update_data)} WHERE guild_id = ? AND discord_id = ? AND LOWER(username) = LOWER(?)"
            update_params.extend([guild_id, interaction.user.id, username])

            cursor.execute(update_query, update_params)
            conn.commit()

            # If username was updated, update the leaderboard table too
            if new_username:
                cursor.execute(
                    "UPDATE leaderboard SET username = ? WHERE guild_id = ? AND LOWER(username) = LOWER(?)",
                    (new_username, guild_id, username),
                )
                conn.commit()

            # Response message
            response = "✅ Successfully updated your linked account:\n" + "\n".join(
                f"• {change}" for change in changes
            )
            await interaction.response.send_message(response, ephemeral=True)
            logger.info(
                f"User {interaction.user} updated their linked account {username} in guild {guild_id}"
            )

            # For visual changes, use local refresh instead of API fetch
            if not new_username or (
                new_username and new_username.lower() == username.lower()
            ):
                # Only visual change, don't re-fetch from API
                await refresh_leaderboard_display(guild_id)
            else:
                # Username changed (could affect sorting), so update normally
                await update_leaderboard(guild_id)
