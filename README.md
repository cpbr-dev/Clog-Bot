# Clog Bot - OSRS Collection Log Leaderboard

A Discord bot that tracks and displays Old School RuneScape collection log completions in a server leaderboard.

## Features

- 📊 **Collection Log Leaderboard**: Automatically generates and updates a top 50 leaderboard for your server
- 🔄 **Auto-Syncing**: Pulls data from OSRS hiscores API hourly
- 🏅 **Player Rankings**: Show off your collection log progress with medals for top 3 placers
- 👤 **Multiple Accounts**: Link multiple RuneScape accounts to your Discord profile
- 🛡️ **Account Types**: Supports different account types (Main, Iron, HCIM, UIM, GIM) with custom emojis
- 🔧 **Admin Controls**: Server admins can manage the leaderboard and override scores for players with <500 items

## Installation

### Requirements
- Python 3.8 or higher
- pip (Python package manager)
- A Discord Bot token

### Steps

1. Clone this repository:
```bash
git clone https://github.com/cpbr-dev/Clog-Bot.git
cd clog-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file by copying the template:
```bash
cp .env.template .env
```

4. Edit the `.env` file with your Discord bot token and other settings

5. Run the bot:
```bash
python main.py
```

## Configuration

Edit the `.env` file with your specific settings:

```Dotenv
# Required Discord Bot Token
DISCORD_TOKEN=your_discord_bot_token_here

# Optional Admin settings
ADMIN_ROLE_ID=admin_role_id_here
ADMIN_USER_ID=admin_user_id_here

# Custom emoji IDs for account types
GIM_EMOJI_ID=emoji_id_here
UIM_EMOJI_ID=emoji_id_here
HCIM_EMOJI_ID=emoji_id_here
IM_EMOJI_ID=emoji_id_here
MAIN_EMOJI_ID=emoji_id_here
```
## Emoji Setup

For custom account type emojis to display correctly:

1. **Discord Server Setup**:
    - Add custom emojis to your Discord server
    - Ensure the bot has the "Use External Emojis" permission
    - Copy the emoji ID by typing `\:emoji_name:` in Discord

2. **Discord Developer Portal**:
    - Alternatively, add emojis directly in your application settings
    - Navigate to the Discord Developer Portal > Your Application > Emojis
    - Upload your emoji images there

3. **Using the Emoji IDs**:
    - Right-click the emoji and select "Copy ID"
    - Add these IDs to your `.env` file in the appropriate fields


## Commands

### User Commands

- `/link [username] [account-type] [emoji]` - Link your RuneScape account to your Discord profile
- `/unlink [username]` - Remove one of your linked RuneScape accounts
- `/update [username]` - Update your linked RuneScape account details
- `/list [username]` - View all RuneScape accounts linked to your profile or another user's profile
- `/whois [username]` - See which Discord user owns a specific RuneScape account

### Admin Commands

- `/setup [channel]` - Set which channel the leaderboard will be posted in
- `/resync` - Manually update the collection log leaderboard with fresh data
- `/override [username] [total]` - Manually set collection log total for a user with <500 items
- Admins can use `/unlink` to remove any user's linked account

## Data and Privacy

- The bot only stores Discord user IDs, RuneScape usernames, account types, and collection log counts
- No personal information is collected or stored

## Support and Contributions

If you encounter issues or have suggestions for improvements:
1. Open an issue on the GitHub repository
2. Submit a pull request with your proposed changes

## License

This project is licensed under the GNU General Public License v3.0 - see the [COPYING](COPYING) file for details.

---

Made with ❤️ by [CPBR](https://github.com/cpbr-dev) for the Verf Clan Discord server
