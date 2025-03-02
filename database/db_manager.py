# database/db_manager.py - Database connection and management
import sqlite3
import logging
from config import DB_PATH

# Get logger
logger = logging.getLogger()

# Database connection
db_conn = None
db_cursor = None


def init_db():
    global db_conn, db_cursor

    db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    db_conn.row_factory = sqlite3.Row
    db_cursor = db_conn.cursor()

    # Initialize schema
    with db_conn:
        cursor = db_conn.cursor()

        # Check for rank column
        cursor.execute("PRAGMA table_info(leaderboard)")
        columns = [column["name"] for column in cursor.fetchall()]

        if "hiscore_rank" not in columns:
            cursor.execute(
                "ALTER TABLE leaderboard ADD COLUMN hiscore_rank INTEGER DEFAULT -1"
            )
            db_conn.commit()
            logger.info("Added hiscore_rank column to leaderboard table")

        # Create tables if they don't exist
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
        db_conn.commit()

    return db_conn


def get_db_connection():
    """Thread-safe database connection with auto-reconnect"""
    global db_conn

    try:
        # Test if connection is alive
        db_conn.execute("SELECT 1")
        return db_conn
    except (sqlite3.OperationalError, sqlite3.ProgrammingError, AttributeError):
        # Reconnect if connection is dead
        logger.warning("Database connection lost, reconnecting...")
        db_conn = init_db()
        return db_conn


# Helper functions for leaderboard management
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
