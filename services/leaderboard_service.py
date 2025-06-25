import discord
from discord.ext import tasks
import logging
import traceback
import datetime

from database.db_manager import (
    get_db_connection,
    get_leaderboard_message_id,
    get_leaderboard_channel_id,
    set_leaderboard_message_id,
)
from services.api_service import fetch_collection_log
from utils.helpers import get_account_type_emoji

logger = logging.getLogger()

# Reference to the bot instance
_bot = None


def start_leaderboard_task(bot):
    """Initialize and start the leaderboard update task"""
    global _bot
    _bot = bot

    # Start the background task
    if not update_leaderboard.is_running():
        update_leaderboard.start()
        logger.info("Started leaderboard update background task")


# ➤ Send the leaderboard embed for the first time
async def send_leaderboard_embed(channel, embed, guild_id):
    logger.info("Sending leaderboard embed...")
    try:
        message = await channel.send(embed=embed)
        set_leaderboard_message_id(guild_id, str(message.id))
        logger.info("Leaderboard embed sent and message ID saved.")
    except discord.Forbidden:
        logger.error(
            f"Bot does not have permission to send messages in channel {channel.id}."
        )
    except discord.HTTPException as e:
        logger.error(f"Failed to send leaderboard embed: {e}")


# ➤ Update leaderboard every hour
@tasks.loop(hours=1)
async def update_leaderboard(guild_id=None, manual=False):
    global _bot

    if not _bot:
        logger.error("Bot reference not set in leaderboard service")
        return

    if guild_id:
        logger.info(
            f"Updating leaderboard for guild {guild_id}... (Manual Update: {manual})"
        )
    else:
        logger.info("Updating leaderboard for all guilds... (Manual: False)")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Fix: don't pass bot to execute(), just use guild_id
            if guild_id:
                cursor.execute(
                    "SELECT username FROM linked_accounts WHERE guild_id = ?",
                    (guild_id,),  # Only pass guild_id here, not bot
                )
                usernames = cursor.fetchall()
                logger.info(
                    f"Found {len(usernames)} linked accounts for guild {guild_id}"
                )
            else:
                cursor.execute("SELECT DISTINCT guild_id FROM linked_accounts")
                guild_ids = cursor.fetchall()
                logger.info(f"Found {len(guild_ids)} guilds with linked accounts")
                for (guild_id,) in guild_ids:
                    # Use recursion to update each guild
                    await update_leaderboard(guild_id)
                return

            if not usernames:
                logger.warning(f"No linked accounts found for guild {guild_id}")
                return

            leaderboard_data = []
            previous_leaderboard = {}

            # Get previous leaderboard data for comparison
            cursor.execute(
                "SELECT username, collection_log_total FROM leaderboard WHERE guild_id = ?",
                (guild_id,),
            )
            for row in cursor.fetchall():
                previous_leaderboard[row["username"]] = row["collection_log_total"]

            logger.info(
                f"Previous leaderboard had {len(previous_leaderboard)} entries for guild {guild_id}"
            )

            # Process each username
            processed_users = 0
            failed_users = 0
            unchanged_users = 0

            for (username,) in usernames:
                try:
                    logger.debug(f"Processing {username} for leaderboard")
                    result = await fetch_collection_log(username)

                    if result is not None:
                        score = result["score"]
                        rank = result["rank"]

                        if score is not None:
                            if score == -1:
                                # Don't skip users with -1 scores, keep them in the leaderboard
                                # They will be displayed as "<500" later
                                logger.debug(f"User {username} has fewer than 500 items (score: -1)")
                                # Only check for previous value if we want to use it instead of -1
                                # But don't skip the user if no previous value exists
                                cursor.execute(
                                    "SELECT collection_log_total FROM leaderboard WHERE guild_id = ? AND username = ?",
                                    (guild_id, username),
                                )
                                previous_result = cursor.fetchone()
                                if previous_result and previous_result["collection_log_total"] > 0 and previous_result["collection_log_total"] < 500:
                                    # Only use previous value if it's valid (between 0-499)
                                    score = previous_result["collection_log_total"]
                                    logger.debug(f"Using previous total for {username}: {score}")
                                # Otherwise keep score as -1 (will display as "<500")

                            # Check if value changed from previous
                            previous_score = previous_leaderboard.get(username)
                            if previous_score == score:
                                unchanged_users += 1
                                logger.debug(f"{username}'s total unchanged: {score}")
                            else:
                                if previous_score is not None:
                                    logger.info(
                                        f"{username}'s total changed: {previous_score} -> {score}"
                                    )
                                else:
                                    logger.info(
                                        f"{username} added to leaderboard with total: {score}"
                                    )

                            # Update database with score and rank
                            cursor.execute(
                                "INSERT INTO leaderboard (guild_id, username, collection_log_total, hiscore_rank) VALUES (?, ?, ?, ?) "
                                "ON CONFLICT(guild_id, username) DO UPDATE SET collection_log_total = ?, hiscore_rank = ?",
                                (guild_id, username, score, rank, score, rank),
                            )
                            leaderboard_data.append((username, score, rank))
                            processed_users += 1
                        else:
                            logger.warning(
                                f"Could not fetch collection log for {username}"
                            )
                            failed_users += 1

                            # Check if they were previously in leaderboard and keep their old score
                            if username in previous_leaderboard:
                                logger.info(
                                    f"Keeping previous score {previous_leaderboard[username]} for {username}"
                                )
                                leaderboard_data.append(
                                    (username, previous_leaderboard[username])
                                )
                                processed_users += 1

                except Exception as e:
                    logger.error(f"Error processing {username} for leaderboard: {e}")
                    logger.error(traceback.format_exc())
                    failed_users += 1

            conn.commit()

            logger.info(f"Leaderboard update summary for guild {guild_id}:")
            logger.info(f"- Processed users: {processed_users}")
            logger.info(f"- Failed users: {failed_users}")
            logger.info(f"- Unchanged users: {unchanged_users}")
            logger.info(f"- Total in leaderboard: {len(leaderboard_data)}")

            # Sort leaderboard data using official rank as tiebreaker
            # Primary sort by score descending, secondary sort by hiscore rank ascending (lower rank is better)
            if (
                len(leaderboard_data) > 0
                and isinstance(leaderboard_data[0], tuple)
                and len(leaderboard_data[0]) >= 2
            ):
                leaderboard_data.sort(
                    key=lambda x: (
                        -x[1],
                        x[2] if len(x) > 2 and x[2] > 0 else float("inf"),
                    )
                )
            else:
                logger.warning(f"Invalid leaderboard data format for guild {guild_id}")
            leaderboard_data = leaderboard_data[:50]

            # Check if anyone was cut off from top 50
            if len(leaderboard_data) == 50 and processed_users > 50:
                logger.info(
                    f"Some users did not make top 50. Cutoff score: {leaderboard_data[-1][1]}"
                )

            # Generate leaderboard message as an embed
            embed = discord.Embed(
                title="🏆 Collection Log Leaderboard (Top 50) 🏆",
                color=0xF5C243,  # Golden color for the leaderboard
            )

            # Create the leaderboard content for the description
            leaderboard_content = ""
            current_rank = 0

            for idx, (username, score, hiscore_rank) in enumerate(leaderboard_data, 1):
                current_rank = idx

                cursor.execute(
                    "SELECT emoji, account_type FROM linked_accounts WHERE guild_id = ? AND username = ?",
                    (guild_id, username),
                )
                result = cursor.fetchone()
                emoji, account_type = result if result else (None, None)

                display_score = score if score != -1 else "<500"

                # Show medal for top 3
                if current_rank == 1:
                    prefix = "🥇"
                elif current_rank == 2:
                    prefix = "🥈"
                elif current_rank == 3:
                    prefix = "🥉"
                else:
                    prefix = f"{current_rank}."

                # Replace account type with custom emoji
                account_type_emoji = get_account_type_emoji(account_type)

                rank_line = f"{prefix} {account_type_emoji} **{username}** {emoji or ''} - {display_score}"
                if current_rank == 1:
                    rank_line += " / 1,581"

                leaderboard_content += rank_line + "\n"
                if current_rank == 3:
                    leaderboard_content += "\n"

            # Set the description to the leaderboard content
            embed.description = leaderboard_content

            # Add command instructions as a field
            commands_field = (
                "• `/link [username] [account-type] [emoji]` - Add your RuneScape account\n"
                "• `/unlink [username]` - Remove one of your linked accounts\n"
                "• `/update [username]` - Change account details\n"
                "• `/list` - View all your linked RuneScape accounts\n"
                "• `/whois [username]` - See which Discord user owns an account"
            )
            embed.add_field(name="📋 Bot Commands", value=commands_field, inline=False)

            # Add info as another field
            info_field = (
                "• The leaderboard shows OSRS Collection Log completion totals\n"
                "• Collection logs under 500 items don't appear on hiscores\n"
                "• Players with <500 items need a moderator to use `/override`\n"
                "• In case of ties, players are ranked by their official OSRS hiscore position"
            )
            embed.add_field(name="ℹ️ Info", value=info_field, inline=False)

            # Add timestamp to footer
            embed.set_footer(text=f"Last updated")
            embed.timestamp = datetime.datetime.now()

            # Send or update the leaderboard embed
            channel_id = get_leaderboard_channel_id(guild_id)
            if not channel_id:
                logger.warning(
                    f"No leaderboard channel set for guild {guild_id}. Skipping update."
                )
                return

            channel = _bot.get_channel(channel_id)
            if not channel:
                logger.error(
                    f"Could not find channel {channel_id} for guild {guild_id}"
                )
                return

            leaderboard_message_id = get_leaderboard_message_id(guild_id)

            if leaderboard_message_id:
                try:
                    message = await channel.fetch_message(leaderboard_message_id)
                    await message.edit(content=None, embed=embed)
                    logger.info(
                        f"Leaderboard embed updated successfully for guild {guild_id}!"
                    )
                except discord.NotFound:
                    logger.warning(
                        f"Leaderboard message not found for guild {guild_id}, sending a new one."
                    )
                    await send_leaderboard_embed(channel, embed, guild_id)
                except discord.Forbidden:
                    logger.error(
                        f"Bot does not have permission to edit messages in channel {channel.id} for guild {guild_id}."
                    )
                except Exception as e:
                    logger.error(f"Error updating leaderboard message: {e}")
                    logger.error(traceback.format_exc())
            else:
                await send_leaderboard_embed(channel, embed, guild_id)
    except Exception as e:
        logger.error(f"Error in update_leaderboard: {e}")
        logger.error(traceback.format_exc())


@update_leaderboard.before_loop
async def before_update_leaderboard():
    """Wait until the bot is ready before starting the task"""
    global _bot
    await _bot.wait_until_ready()
    logger.info("Bot is ready, leaderboard task can start")


# Visual only refresh of the leaderboard (Doesn't fetch new data)
async def refresh_leaderboard_display(guild_id):
    """Refresh the leaderboard display without fetching new data from the API"""
    global _bot

    if not _bot:
        logger.error("Bot reference not set in leaderboard service")
        return

    logger.info(f"Refreshing leaderboard display for guild {guild_id} (no API calls)")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get existing leaderboard data from database
            cursor.execute(
                "SELECT username, collection_log_total, hiscore_rank FROM leaderboard WHERE guild_id = ?",
                (guild_id,),
            )
            leaderboard_data = [
                (row["username"], row["collection_log_total"], row["hiscore_rank"])
                for row in cursor.fetchall()
            ]

            # Sort and generate the leaderboard display as usual
            leaderboard_data.sort(
                key=lambda x: (-x[1], x[2] if x[2] > 0 else float("inf"))
            )
            leaderboard_data = leaderboard_data[:50]

            # Generate embed and update display (same as in update_leaderboard)
            embed = discord.Embed(
                title="🏆 Collection Log Leaderboard (Top 50) 🏆",
                color=0xF5C243,
            )

            leaderboard_content = ""

            for idx, (username, score, hiscore_rank) in enumerate(leaderboard_data, 1):
                current_rank = idx

                cursor.execute(
                    "SELECT emoji, account_type FROM linked_accounts WHERE guild_id = ? AND username = ?",
                    (guild_id, username),
                )
                result = cursor.fetchone()
                emoji, account_type = result if result else (None, None)

                display_score = score if score != -1 else "<500"

                # Show medal for top 3
                if current_rank == 1:
                    prefix = "🥇"
                elif current_rank == 2:
                    prefix = "🥈"
                elif current_rank == 3:
                    prefix = "🥉"
                else:
                    prefix = f"{current_rank}."

                account_type_emoji = get_account_type_emoji(account_type)

                rank_line = f"{prefix} {account_type_emoji} **{username}** {emoji or ''} - {display_score}"
                if current_rank == 1:
                    rank_line += " / 1,581"

                leaderboard_content += rank_line + "\n"
                if current_rank == 3:
                    leaderboard_content += "\n"

            embed.description = leaderboard_content

            # Add command instructions as a field
            commands_field = (
                "• `/link [username] [account-type] [emoji]` - Add your RuneScape account\n"
                "• `/unlink [username]` - Remove one of your linked accounts\n"
                "• `/update [username]` - Change account details\n"
                "• `/list` - View all your linked RuneScape accounts\n"
                "• `/whois [username]` - See which Discord user owns an account"
            )
            embed.add_field(name="📋 Bot Commands", value=commands_field, inline=False)

            # Add info field
            info_field = (
                "• The leaderboard shows OSRS Collection Log completion totals\n"
                "• Collection logs under 500 items don't appear on hiscores\n"
                "• Players with <500 items need a moderator to use `/override`\n"
                "• In case of ties, players are ranked by their official OSRS hiscore position"
            )
            embed.add_field(name="ℹ️ Info", value=info_field, inline=False)

            # Add timestamp
            embed.set_footer(text="Last updated")
            embed.timestamp = datetime.datetime.now()

            # Update the message
            channel_id = get_leaderboard_channel_id(guild_id)
            if not channel_id:
                return

            channel = _bot.get_channel(channel_id)
            if not channel:
                return

            message_id = get_leaderboard_message_id(guild_id)
            if not message_id:
                return

            try:
                message = await channel.fetch_message(message_id)
                await message.edit(content=None, embed=embed)
                logger.info(f"Leaderboard display refreshed for guild {guild_id}")
            except Exception as e:
                logger.error(f"Error refreshing leaderboard display: {e}")

    except Exception as e:
        logger.error(f"Error in refresh_leaderboard_display: {e}")
        logger.error(traceback.format_exc())
