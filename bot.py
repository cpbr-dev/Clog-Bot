import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import aiohttp

import logging

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get values from .env file
TOKEN = os.getenv("DISCORD_TOKEN")
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID"))

# Simplified logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # Print to console
        logging.FileHandler("bot.log", mode="a"),  # Log to a file
    ],
)


# Database setup
def get_db_connection():
    conn = sqlite3.connect("clog_leaderboard.db")
    conn.row_factory = sqlite3.Row
    return conn


with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS linked_accounts (
            discord_id INTEGER,
            username TEXT,
            account_type TEXT,
            emoji TEXT,
            PRIMARY KEY (discord_id, username)
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leaderboard (
            username TEXT PRIMARY KEY,
            collection_log_total INTEGER
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """
    )
    conn.commit()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# Helper function to get and set the leaderboard message ID
def get_leaderboard_message_id():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM bot_state WHERE key = 'leaderboard_message_id'"
        )
        result = cursor.fetchone()
        return result["value"] if result else None


def set_leaderboard_message_id(message_id: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO bot_state (key, value) VALUES ('leaderboard_message_id', ?)",
            (message_id,),
        )
        conn.commit()


# ➤ /link command
@bot.tree.command(
    name="link", description="Link a RuneScape username to your Discord account"
)
@app_commands.describe(
    username="Your RuneScape username",
    account_type="Select your account type (Iron, HCIM, UIM, GIM, Main)",
    emoji="(Optional) An emoji to display next to your name",
)
async def link(
    interaction: discord.Interaction,
    username: str,
    account_type: str,
    emoji: str = None,
):
    # Ensure emoji is valid
    if emoji and not any(ord(c) > 255 for c in emoji):
        await interaction.response.send_message(
            "❌ Invalid emoji! Please use a real emoji.", ephemeral=True
        )
        return

    # Insert into database
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO linked_accounts (discord_id, username, account_type, emoji) VALUES (?, ?, ?, ?)",
                (interaction.user.id, username, account_type, emoji),
            )
            conn.commit()
            await interaction.response.send_message(
                f"✅ Linked **{username}** as a **{account_type}**!", ephemeral=True
            )
            logging.info(
                f"User {interaction.user} linked account {username} as {account_type}."
            )

            # After linking, update leaderboard
            total = await fetch_collection_log(username)
            if total is not None:
                cursor.execute(
                    "INSERT INTO leaderboard (username, collection_log_total) VALUES (?, ?) ON CONFLICT(username) DO UPDATE SET collection_log_total = ?",
                    (username, total, total),
                )
                conn.commit()
                logging.info(f"Leaderboard updated for {username}")

                # Optionally refresh leaderboard in the channel
                await update_leaderboard()

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
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if interaction.user.guild_permissions.administrator:
            # Admins can unlink any username
            cursor.execute(
                "DELETE FROM linked_accounts WHERE username = ?",
                (username,),
            )
        else:
            # Non-admins can only unlink their own usernames
            cursor.execute(
                "DELETE FROM linked_accounts WHERE discord_id = ? AND username = ?",
                (interaction.user.id, username),
            )

        if cursor.rowcount > 0:
            conn.commit()
            await interaction.response.send_message(
                f"✅ Unlinked **{username}**!", ephemeral=True
            )
            logging.info(f"User {interaction.user} unlinked account {username}.")

            # Refresh leaderboard in the channel
            await update_leaderboard()
        else:
            await interaction.response.send_message(
                "❌ You can only unlink usernames you linked yourself.", ephemeral=True
            )
            logging.warning(
                f"User {interaction.user} tried to unlink an account they didn't link: {username}"
            )


# ➤ /list command
@bot.tree.command(
    name="list", description="View all RuneScape usernames linked to your account"
)
async def list_accounts(interaction: discord.Interaction):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, account_type, emoji FROM linked_accounts WHERE discord_id = ?",
            (interaction.user.id,),
        )
        accounts = cursor.fetchall()

        if not accounts:
            await interaction.response.send_message(
                "❌ You have not linked any usernames.", ephemeral=True
            )
            return

        msg = "**Your linked usernames:**\n" + "\n".join(
            [
                f"➤ {username} ({account_type}) {emoji or ''}"
                for username, account_type, emoji in accounts
            ]
        )
        await interaction.response.send_message(msg, ephemeral=True)
        logging.info(f"User {interaction.user} requested list of linked accounts.")


# ➤ /unlink_all (Admin Only)
@bot.tree.command(
    name="unlink_all", description="(Admin) Remove all linked usernames for a user"
)
@app_commands.describe(user="The user whose linked usernames you want to remove")
async def unlink_all(interaction: discord.Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.", ephemeral=True
        )
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM linked_accounts WHERE discord_id = ?", (user.id,))
        if cursor.rowcount > 0:
            conn.commit()
            await interaction.response.send_message(
                f"✅ Removed all linked usernames for {user.mention}.",
            )
            logging.info(
                f"Admin {interaction.user} removed all linked accounts for {user}."
            )

            # Refresh leaderboard in the channel
            await update_leaderboard()
        else:
            await interaction.response.send_message(
                "❌ This user has no linked usernames.", ephemeral=True
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


# ➤ Update leaderboard every 15 minutes
@tasks.loop(minutes=15)
async def update_leaderboard():
    logging.info("Updating leaderboard...")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM linked_accounts")
        usernames = cursor.fetchall()

        leaderboard_data = []

        for (username,) in usernames:
            total = await fetch_collection_log(username)
            if total is not None:
                cursor.execute(
                    "INSERT INTO leaderboard (username, collection_log_total) VALUES (?, ?) ON CONFLICT(username) DO UPDATE SET collection_log_total = ?",
                    (username, total, total),
                )
                leaderboard_data.append((username, total))

        conn.commit()

        # Sort and take the top 50 players
        leaderboard_data.sort(key=lambda x: x[1], reverse=True)
        leaderboard_data = leaderboard_data[:50]

        leaderboard_message = "**🏆 Collection Log Leaderboard (Top 50) 🏆**\n\n"
        for idx, (username, total) in enumerate(leaderboard_data, 1):
            cursor.execute(
                "SELECT emoji, account_type FROM linked_accounts WHERE username = ?",
                (username,),
            )
            emoji, account_type = (
                cursor.fetchone()
            )  # Get the emoji and account type for that user

            if idx == 1:
                leaderboard_message += f"🥇 **{username}** {emoji or ''} ({account_type}) - {total} / 1,561\n"
            elif idx == 2:
                leaderboard_message += (
                    f"🥈 **{username}** {emoji or ''} ({account_type}) - {total}\n"
                )
            elif idx == 3:
                leaderboard_message += (
                    f"🥉 **{username}** {emoji or ''} ({account_type}) - {total}\n\n"
                )
            else:
                leaderboard_message += (
                    f"{idx}. **{username}** {emoji or ''} ({account_type}) - {total}\n"
                )

        # Add instructions at the end of the leaderboard message
        leaderboard_message += "\n\nTo link your account, use `/link`\nTo unlink an account, use `/unlink`\n"

        # Send or update the leaderboard message
        channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
        leaderboard_message_id = get_leaderboard_message_id()

        if leaderboard_message_id:
            try:
                message = await channel.fetch_message(leaderboard_message_id)
                await message.edit(content=leaderboard_message)
                logging.info("Leaderboard updated successfully!")
            except discord.NotFound:
                logging.warning("Leaderboard message not found, sending a new one.")
                await send_leaderboard_message(channel, leaderboard_message)
        else:
            await send_leaderboard_message(channel, leaderboard_message)


# ➤ Send the leaderboard message for the first time
async def send_leaderboard_message(channel, leaderboard_message):
    logging.info("Sending leaderboard message...")
    message = await channel.send(leaderboard_message)
    set_leaderboard_message_id(str(message.id))
    logging.info("Leaderboard message sent and message ID saved.")



# ➤ /resync (Manual Update Command)
@bot.tree.command(
    name="resync",
    description="Manually update the collection log leaderboard",
)
async def update_leaderboard_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an administrator to use this command.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "🔄 Updating leaderboard now...", ephemeral=True
    )

    # Run the leaderboard update function manually
    await update_leaderboard()

    # Confirm completion
    await interaction.followup.send(
        "✅ Leaderboard updated successfully!", ephemeral=True
    )

# ➤ /whois command
@bot.tree.command(
    name="whois", description="Shows which Discord user a specific RuneScape username is linked to"
)
@app_commands.describe(username="The RuneScape username you want to look up")
async def whois(interaction: discord.Interaction, username: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT discord_id FROM linked_accounts WHERE username = ?",
            (username,),
        )
        result = cursor.fetchone()

        if result:
            discord_id = result["discord_id"]
            user = await bot.fetch_user(discord_id)
            await interaction.response.send_message(
                f"🔍 **{username}** is linked to Discord user **{user}** ({user.mention}).",
                ephemeral=True
            )
            logging.info(f"User {interaction.user} looked up whois for {username}.")
        else:
            await interaction.response.send_message(
                f"❌ No Discord user is linked to the username **{username}**.",
                ephemeral=True
            )
            logging.warning(f"User {interaction.user} tried to look up whois for non-linked username: {username}")


# Bot events
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} commands.")

        update_leaderboard.start()  # Start any background tasks (like leaderboard updater)
        logging.info(f"{bot.user} is online!")

    except Exception as e:
        logging.warning(f"Error while syncing commands: {e}")


# Start the bot
bot.run(TOKEN)
