# main.py - Bot entry point
import discord
from discord.ext import commands
import asyncio
import signal
import sys
import os
from dotenv import load_dotenv
import traceback

# Local imports
from utils.logging_setup import setup_logging
from database.db_manager import init_db
from commands import register_all_commands
from services.leaderboard_service import start_leaderboard_task

# Initialize logger
logger = setup_logging()

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize database
init_db()


async def shutdown():
    logger.info("Shutting down bot gracefully...")
    # Cleanup code...
    sys.exit(0)


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands.")

        # Start background tasks
        start_leaderboard_task(bot)

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for signame in ("SIGINT", "SIGTERM"):
            loop.add_signal_handler(
                getattr(signal, signame), lambda: asyncio.create_task(shutdown())
            )

        logger.info(f"{bot.user} is online!")
    except Exception as e:
        logger.warning(f"Error while syncing commands: {e}")


# Register all commands
try:
    register_all_commands(bot)
    logger.info("Successfully registered all commands")
except Exception as e:
    logger.error(f"Failed to register commands: {e}")
    logger.error(traceback.format_exc())

# Start the bot
try:
    bot.run(TOKEN)
except KeyboardInterrupt:
    logger.info("Received exit signal, shutting down gracefully...")
    asyncio.run(shutdown())
