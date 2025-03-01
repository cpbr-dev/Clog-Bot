# config.py - Central configuration
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

# Database configuration
DB_PATH = "clog_leaderboard.db"

# API configuration
OSRS_API_URL = (
    "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player="
)

# Account type emoji
# Load the IDs from the environment variables

GIM_EMOJI_ID = os.getenv("GIM_EMOJI_ID")
UIM_EMOJI_ID = os.getenv("UIM_EMOJI_ID")
HCIM_EMOJI_ID = os.getenv("HCIM_EMOJI_ID")
IM_EMOJI_ID = os.getenv("IM_EMOJI_ID")
MAIN_EMOJI_ID = os.getenv("MAIN_EMOJI_ID")

ACCOUNT_TYPE_EMOJIS = {
    "GIM": f"<:gim:{GIM_EMOJI_ID}>",
    "UIM": f"<:uim:{UIM_EMOJI_ID}>",
    "HCIM": f"<:hcim:{HCIM_EMOJI_ID}>",
    "Iron": f"<:im:{IM_EMOJI_ID}>",
    "Main": f"<:main:{MAIN_EMOJI_ID}>",
}
