import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import aiohttp

import logging

import os
import re
from dotenv import load_dotenv


import asyncio
import signal
import sys

async def shutdown():
    logging.info("Shutting down bot gracefully...")

    # Stop the background leaderboard task if running
    if update_leaderboard.is_running():
        update_leaderboard.cancel()
        logging.info("Stopped background leaderboard update task.")

    # Close database connection
    if hasattr(get_db_connection, "conn") and get_db_connection.conn:
        get_db_connection.conn.close()
        logging.info("Closed database connection.")

    # Logout the bot and stop
    await bot.close()
    logging.info("Bot has logged out and shut down.")

    sys.exit(0)  # Exit the program safely

# Load environment variables from .env file
load_dotenv()

# Get values from .env file
TOKEN = os.getenv("DISCORD_TOKEN")

# Simplified logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # Print to console
        logging.FileHandler("bot.log", mode="a"),  # Log to a file
    ],
)


# Create a global connection pool
def init_db():
    conn = sqlite3.connect("clog_leaderboard.db", check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

db_conn = init_db()
db_cursor = db_conn.cursor()

def get_db_connection():
    return db_conn  # Return the global connection pool


with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS linked_accounts (
            guild_id INTEGER,
            discord_id INTEGER,
            username TEXT,
            account_type TEXT,
            emoji TEXT,
            PRIMARY KEY (guild_id, discord_id, username)
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leaderboard (
            guild_id INTEGER,
            username TEXT,
            collection_log_total INTEGER,
            PRIMARY KEY (guild_id, username)
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_state (
            guild_id INTEGER,
            key TEXT,
            value TEXT,
            PRIMARY KEY (guild_id, key)
        )
    """
    )
    conn.commit()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# Helper function to get and set the leaderboard message ID
def get_leaderboard_message_id(guild_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM bot_state WHERE guild_id = ? AND key = 'leaderboard_message_id'",
            (guild_id,),
        )
        result = cursor.fetchone()
        return result["value"] if result else None


def set_leaderboard_message_id(guild_id, message_id: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO bot_state (guild_id, key, value) VALUES (?, 'leaderboard_message_id', ?)",
            (guild_id, message_id),
        )
        conn.commit()


# Helper function to get and set the leaderboard channel ID
def get_leaderboard_channel_id(guild_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM bot_state WHERE guild_id = ? AND key = 'leaderboard_channel_id'",
            (guild_id,),
        )
        result = cursor.fetchone()
        return int(result["value"]) if result else None


def set_leaderboard_channel_id(guild_id, channel_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO bot_state (guild_id, key, value) VALUES (?, 'leaderboard_channel_id', ?)",
            (guild_id, str(channel_id)),
        )
        conn.commit()


# ➤ /setup command
@bot.tree.command(
    name="setup", description="Set up the leaderboard channel for this server"
)
@app_commands.describe(channel="The channel to post the leaderboard in")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.", ephemeral=True
        )
        return

    guild_id = interaction.guild_id

    # Fetch the existing leaderboard message ID
    leaderboard_message_id = get_leaderboard_message_id(guild_id)

    if leaderboard_message_id:
        try:
            old_channel_id = get_leaderboard_channel_id(guild_id)
            old_channel = bot.get_channel(old_channel_id)
            old_message = await old_channel.fetch_message(leaderboard_message_id)
            await old_message.delete()
            logging.info(
                f"Deleted old leaderboard message {leaderboard_message_id} in guild {guild_id}."
            )
        except discord.NotFound:
            logging.warning(
                f"Old leaderboard message {leaderboard_message_id} not found in guild {guild_id}."
            )
        except discord.Forbidden:
            logging.error(
                f"Bot does not have permission to delete messages in channel {old_channel_id}."
            )

    # Set the new leaderboard channel ID
    set_leaderboard_channel_id(guild_id, channel.id)

    # Update the leaderboard in the new channel
    await update_leaderboard(guild_id)

    await interaction.response.send_message(
        f"✅ Leaderboard channel set to {channel.mention}", ephemeral=True
    )
    logging.info(
        f"Leaderboard channel set to {channel.id} for guild {interaction.guild_id}"
    )


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
        app_commands.Choice(name="Iron", value="Iron"),
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
                f"✅ Linked **{username}** as a **{account_type}**!", ephemeral=True
            )
            logging.info(
                f"User {interaction.user} linked account {username} as {account_type} in guild {guild_id}."
            )

            # After linking, update leaderboard
            total = await fetch_collection_log(username)
            if total is not None:
                cursor.execute(
                    "INSERT INTO leaderboard (guild_id, username, collection_log_total) VALUES (?, ?, ?) ON CONFLICT(guild_id, username) DO UPDATE SET collection_log_total = ?",
                    (guild_id, username, total, total),
                )
                conn.commit()
                logging.info(f"Leaderboard updated for {username} in guild {guild_id}")

                # Optionally refresh leaderboard in the channel
                await update_leaderboard(guild_id)

    except sqlite3.IntegrityError:
        await interaction.response.send_message(
            "❌ You have already linked this username!", ephemeral=True
        )
        logging.warning(
            f"User {interaction.user} tried to link an already linked account: {username}"
        )


# ➤ /unlink command
@bot.tree.command(
    name="unlink", description="Unlink one of your linked RuneScape usernames"
)
@app_commands.describe(username="The username you want to unlink")
async def unlink(interaction: discord.Interaction, username: str):
    guild_id = interaction.guild_id

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Non-admins can only unlink their own usernames
        cursor.execute(
            "DELETE FROM linked_accounts WHERE guild_id = ? AND discord_id = ? AND username = ?",
            (guild_id, interaction.user.id, username),
        )

        if cursor.rowcount > 0:
            conn.commit()
            await interaction.response.send_message(
                f"✅ Unlinked **{username}**!", ephemeral=True
            )
            logging.info(
                f"User {interaction.user} unlinked account {username} in guild {guild_id}."
            )

            # Refresh leaderboard in the channel
            await update_leaderboard(guild_id)
        else:
            await interaction.response.send_message(
                "❌ You can only unlink usernames you linked yourself.", ephemeral=True
            )
            logging.warning(
                f"User {interaction.user} tried to unlink an account they didn't link: {username} in guild {guild_id}"
            )


# ➤ /list command
@bot.tree.command(
    name="list", description="View all RuneScape usernames linked to your account"
)
@app_commands.describe(
    user="(Optional) The user whose linked usernames you want to view"
)
async def list_accounts(interaction: discord.Interaction, user: discord.Member = None):
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
        logging.info(
            f"User {interaction.user} requested list of linked accounts for {target_user} in guild {guild_id}."
        )


# ➤ /unlink_all (Admin Only)
@bot.tree.command(
    name="unlink_all", description="(Admin) Remove all linked usernames for a user"
)
@app_commands.describe(user="The user whose linked usernames you want to remove")
@app_commands.checks.has_permissions(administrator=True)
async def unlink_all(interaction: discord.Interaction, user: discord.Member):
    guild_id = interaction.guild_id

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.", ephemeral=True
        )
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM linked_accounts WHERE guild_id = ? AND discord_id = ?",
            (guild_id, user.id),
        )
        if cursor.rowcount > 0:
            conn.commit()
            await interaction.response.send_message(
                f"✅ Removed all linked usernames for {user.mention}.",
            )
            logging.info(
                f"Admin {interaction.user} removed all linked accounts for {user} in guild {guild_id}."
            )

            # Refresh leaderboard in the channel
            await update_leaderboard(guild_id)
        else:
            await interaction.response.send_message(
                "❌ This user has no linked usernames.", ephemeral=True
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
            logging.info(
                f"User {interaction.user} looked up whois for {username} in guild {guild_id}."
            )
        else:
            await interaction.response.send_message(
                f"❌ No Discord user is linked to the username **{username}**.",
                ephemeral=True,
            )
            logging.warning(
                f"User {interaction.user} tried to look up whois for non-linked username: {username} in guild {guild_id}"
            )


# ➤ Fetch collection log total from API
async def fetch_collection_log(username):
    url = f"https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player={username}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                for activity in data.get("activities", []):
                    if activity["id"] == 18:  # Collections Logged
                        return activity["score"]
    return None  # Return None if no valid data found


# ➤ Update leaderboard every hour
@tasks.loop(minutes=60)
async def update_leaderboard(guild_id=None, manual=False):
    if guild_id:
        logging.info(
            f"Updating leaderboard for guild {guild_id}... (Manual Update: {manual})"
        )
    else:
        logging.info("Updating leaderboard for all guilds... (Manual: False)")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        if guild_id:
            cursor.execute(
                "SELECT username FROM linked_accounts WHERE guild_id = ?", (guild_id,)
            )
        else:
            cursor.execute("SELECT DISTINCT guild_id FROM linked_accounts")
            guild_ids = cursor.fetchall()
            for (guild_id,) in guild_ids:
                await update_leaderboard(guild_id)
            return

        usernames = cursor.fetchall()

        leaderboard_data = []

        for (username,) in usernames:
            total = await fetch_collection_log(username)
            if total is not None:
                if total == -1:
                    cursor.execute(
                        "SELECT collection_log_total FROM leaderboard WHERE guild_id = ? AND username = ?",
                        (guild_id, username),
                    )
                    result = cursor.fetchone()
                    if result:
                        total = result["collection_log_total"]
                    else:
                        continue  # Skip if no previous value is found

                cursor.execute(
                    "INSERT INTO leaderboard (guild_id, username, collection_log_total) VALUES (?, ?, ?) ON CONFLICT(guild_id, username) DO UPDATE SET collection_log_total = ?",
                    (guild_id, username, total, total),
                )
                leaderboard_data.append((username, total))

        conn.commit()

        # Sort and take the top 50 players
        leaderboard_data.sort(key=lambda x: x[1], reverse=True)
        leaderboard_data = leaderboard_data[:50]

        leaderboard_message = "**🏆 Collection Log Leaderboard (Top 50) 🏆**\n\n"
        for idx, (username, total) in enumerate(leaderboard_data, 1):
            cursor.execute(
                "SELECT emoji, account_type FROM linked_accounts WHERE guild_id = ? AND username = ?",
                (guild_id, username),
            )
            emoji, account_type = (
                cursor.fetchone()
            )  # Get the emoji and account type for that user

            display_total = total if total != -1 else "<500"

            if idx == 1:
                leaderboard_message += f"🥇 **{username}** {emoji or ''} ({account_type}) - {display_total} / 1,561\n"
            elif idx == 2:
                leaderboard_message += f"🥈 **{username}** {emoji or ''} ({account_type}) - {display_total}\n"
            elif idx == 3:
                leaderboard_message += f"🥉 **{username}** {emoji or ''} ({account_type}) - {display_total}\n\n"
            else:
                leaderboard_message += f"{idx}. **{username}** {emoji or ''} ({account_type}) - {display_total}\n"

        # Add instructions at the end of the leaderboard message
        leaderboard_message += "\n\nTo link your account, use `/link`\nTo unlink an account, use `/unlink`\n"

        # Send or update the leaderboard message
        channel_id = get_leaderboard_channel_id(guild_id)
        if not channel_id:
            logging.warning(
                f"No leaderboard channel set for guild {guild_id}. Skipping update."
            )
            return

        channel = bot.get_channel(channel_id)
        leaderboard_message_id = get_leaderboard_message_id(guild_id)

        if leaderboard_message_id:
            try:
                message = await channel.fetch_message(leaderboard_message_id)
                await message.edit(content=leaderboard_message)
                logging.info(f"Leaderboard updated successfully for guild {guild_id}!")
            except discord.NotFound:
                logging.warning(
                    f"Leaderboard message not found for guild {guild_id}, sending a new one."
                )
                await send_leaderboard_message(channel, leaderboard_message, guild_id)
            except discord.Forbidden:
                logging.error(
                    f"Bot does not have permission to edit messages in channel {channel.id} for guild {guild_id}."
                )
        else:
            await send_leaderboard_message(channel, leaderboard_message, guild_id)


# ➤ Send the leaderboard message for the first time
async def send_leaderboard_message(channel, leaderboard_message, guild_id):
    logging.info("Sending leaderboard message...")
    try:
        message = await channel.send(leaderboard_message)
        set_leaderboard_message_id(guild_id, str(message.id))
        logging.info("Leaderboard message sent and message ID saved.")
    except discord.Forbidden:
        logging.error(
            f"Bot does not have permission to send messages in channel {channel.id}."
        )
    except discord.HTTPException as e:
        logging.error(f"Failed to send leaderboard message: {e}")


# ➤ /resync (Admin Only) - Manually update the collection log leaderboard
@bot.tree.command(
    name="resync",
    description="Manually update the collection log leaderboard",
)
@app_commands.checks.has_permissions(administrator=True)
async def update_leaderboard_command(interaction: discord.Interaction):
    guild_id = interaction.guild_id

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "🔄 Updating leaderboard now...", ephemeral=True
    )

    # Run the leaderboard update function manually
    await update_leaderboard(guild_id, manual=True)

    # Confirm completion
    await interaction.followup.send(
        "✅ Leaderboard updated successfully!", ephemeral=True
    )


# ➤ /override (Admin Only) - Manually set collection log total for a user
@bot.tree.command(
    name="override",
    description="(Admin) Manually override the collection log total for a user",
)
@app_commands.describe(
    username="The RuneScape username", total="The new collection log total"
)
@app_commands.checks.has_permissions(administrator=True)
async def override(interaction: discord.Interaction, username: str, total: int):
    guild_id = interaction.guild_id

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.", ephemeral=True
        )
        return

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
            if current_total >= 500 :
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
            logging.info(
                f"Admin {interaction.user} manually set collection log total for {username} to {total} in guild {guild_id}."
            )

            # Refresh leaderboard in the channel
            await update_leaderboard(guild_id)

    except Exception as e:
        await interaction.response.send_message(
            f"❌ Failed to set collection log total: {e}", ephemeral=True
        )
        logging.error(f"Failed to set collection log total for {username}: {e}")


# Error handling
async def on_tree_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CommandOnCooldown):
        return await interaction.response.send_message(
            f"Command is currently on cooldown! Try again in **{error.retry_after:.2f}** seconds!",
            ephemeral=True,
        )
    elif isinstance(error, app_commands.MissingPermissions):
        return await interaction.response.send_message(
            f"You're missing permissions to use that", ephemeral=True
        )
    else:
        raise error


# Bot events
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} commands.")

        update_leaderboard.start()  # Start background task
        logging.info(f"{bot.user} is online!")

        # Register signal handler for graceful shutdown
        loop = asyncio.get_running_loop()
        for signame in ('SIGINT', 'SIGTERM'):
            loop.add_signal_handler(getattr(signal, signame), lambda: asyncio.create_task(shutdown()))

    except Exception as e:
        logging.warning(f"Error while syncing commands: {e}")

# Start the bot
bot.tree.on_error = on_tree_error

try:
    bot.run(TOKEN)
except KeyboardInterrupt:
    logging.info("Received exit signal, shutting down gracefully...")
    asyncio.run(shutdown())  # Ensure cleanup runs