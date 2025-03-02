import discord
from discord import app_commands
import logging

from utils.helpers import is_admin
from database.db_manager import (
    get_db_connection,
    get_leaderboard_channel_id,
    get_leaderboard_message_id,
    set_leaderboard_channel_id,
)
from services.leaderboard_service import update_leaderboard, send_leaderboard_embed

logger = logging.getLogger()


def register_admin_commands(bot):
    """Register all admin commands with the bot"""

    # ➤ /setup command
    @bot.tree.command(
        name="setup", description="Set up the leaderboard channel for this server"
    )
    @app_commands.describe(channel="The channel to post the leaderboard in")
    @is_admin()
    async def setup(interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild_id

        # Fetch the existing leaderboard message ID
        leaderboard_message_id = get_leaderboard_message_id(guild_id)

        if leaderboard_message_id:
            try:
                old_channel_id = get_leaderboard_channel_id(guild_id)
                old_channel = bot.get_channel(old_channel_id)
                old_message = await old_channel.fetch_message(leaderboard_message_id)
                await old_message.delete()
                logger.info(
                    f"Deleted old leaderboard message {leaderboard_message_id} in guild {guild_id}."
                )
            except discord.NotFound:
                logger.warning(
                    f"Old leaderboard message {leaderboard_message_id} not found in guild {guild_id}."
                )
            except discord.Forbidden:
                logger.error(
                    f"Bot does not have permission to delete messages in channel {old_channel_id}."
                )

        # Set the new leaderboard channel ID
        set_leaderboard_channel_id(guild_id, channel.id)

        # Update the leaderboard in the new channel
        await update_leaderboard(guild_id)

        await interaction.response.send_message(
            f"✅ Leaderboard channel set to {channel.mention}", ephemeral=True
        )
        logger.info(
            f"Leaderboard channel set to {channel.id} for guild {interaction.guild_id}"
        )

    # ➤ /resync (Admin Only)
    @bot.tree.command(
        name="resync",
        description="Manually update the collection log leaderboard with fresh data",
    )
    @is_admin()
    async def update_leaderboard_command(interaction: discord.Interaction):
        guild_id = interaction.guild_id

        await interaction.response.send_message(
            "🔄 Syncing leaderboard with fresh data from the OSRS API...", ephemeral=True
        )

        # Run the leaderboard update function manually
        await update_leaderboard(guild_id, manual=True)

        # Confirm completion
        await interaction.followup.send(
            "✅ Leaderboard updated with the latest data from the OSRS hiscores!", ephemeral=True
        )

    # ➤ /override (Admin Only)
    @bot.tree.command(
        name="override",
        description="(Admin) Manually override the collection log total for a user",
    )
    @app_commands.describe(
        username="The RuneScape username", total="The new collection log total"
    )
    @is_admin()
    async def override(interaction: discord.Interaction, username: str, total: int):
        guild_id = interaction.guild_id

        if total >= 499 or total <= 0:
            await interaction.response.send_message(
                "❌ Overrided total must be within the range [0, 499].", ephemeral=True
            )
            return

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT collection_log_total FROM leaderboard WHERE guild_id = ? AND username = ?",
                    (guild_id, username),
                )
                result = cursor.fetchone()
                if result is None:
                    await interaction.response.send_message(
                        f"❌ User **{username}** does not exist in the leaderboard.",
                        ephemeral=True,
                    )
                    return

                current_total = result["collection_log_total"]
                if current_total >= 500:
                    await interaction.response.send_message(
                        f"❌ You can only override the score for users whose score is <500. Current score for **{username}** is **{current_total}**.",
                        ephemeral=True,
                    )
                    return

                cursor.execute(
                    "UPDATE leaderboard SET collection_log_total = ? WHERE guild_id = ? AND username = ?",
                    (total, guild_id, username),
                )
                conn.commit()
                await interaction.response.send_message(
                    f"✅ Manually set collection log total for **{username}** to **{total}**.",
                    ephemeral=True,
                )
                logger.info(
                    f"Admin {interaction.user} manually set collection log total for {username} to {total} in guild {guild_id}."
                )

                # Refresh leaderboard in the channel
                await update_leaderboard(guild_id)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to set collection log total: {e}", ephemeral=True
            )
            logger.error(f"Failed to set collection log total for {username}: {e}")
