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

# Account type emojis
ACCOUNT_TYPE_EMOJIS = {
    "GIM": "<:gim:1345118041557696583>",
    "UIM": "<:uim:1345118022712557739>",
    "HCIM": "<:hcim:1345118032162328656>",
    "Iron": "<:im:1345118010675040379>",
    "Main": "<:main:1345164337978933389>",
}
