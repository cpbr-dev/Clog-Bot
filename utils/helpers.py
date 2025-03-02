# utils/helpers.py - Helper functions
import discord
from discord import app_commands
import logging
import re
from config import ADMIN_ROLE_ID, ADMIN_USER_ID, ACCOUNT_TYPE_EMOJIS

# Get logger
logger = logging.getLogger()


# Custom check for admin permissions
def is_admin():
    async def predicate(interaction: discord.Interaction):
        # Always allow server administrators
        if interaction.user.guild_permissions.administrator:
            return True

        # Check for specific role if configured
        if ADMIN_ROLE_ID:
            try:
                admin_role_id = int(ADMIN_ROLE_ID)
                if any(role.id == admin_role_id for role in interaction.user.roles):
                    logger.info(
                        f"User {interaction.user} granted admin access via role ID {admin_role_id}"
                    )
                    return True
            except (ValueError, TypeError):
                logger.warning("Invalid ADMIN_ROLE_ID in environment variables")

        # Check for specific user if configured
        if ADMIN_USER_ID:
            try:
                admin_user_id = int(ADMIN_USER_ID)
                if interaction.user.id == admin_user_id:
                    logger.info(
                        f"User {interaction.user} granted admin access via user ID {admin_user_id}"
                    )
                    return True
            except (ValueError, TypeError):
                logger.warning("Invalid ADMIN_USER_ID in environment variables")

        # No permission - raise appropriate error
        raise app_commands.MissingPermissions(["administrator"])

    return app_commands.check(predicate)


# Helper function to check if a user is an admin (returns boolean instead of raising exception)
def is_admin_user(interaction: discord.Interaction):
    # Always allow server administrators
    if interaction.user.guild_permissions.administrator:
        return True

    # Check for specific role if configured
    if ADMIN_ROLE_ID:
        try:
            admin_role_id = int(ADMIN_ROLE_ID)
            if any(role.id == admin_role_id for role in interaction.user.roles):
                return True
        except (ValueError, TypeError):
            logger.warning("Invalid ADMIN_ROLE_ID in environment variables")

    # Check for specific user if configured
    if ADMIN_USER_ID:
        try:
            admin_user_id = int(ADMIN_USER_ID)
            if interaction.user.id == admin_user_id:
                return True
        except (ValueError, TypeError):
            logger.warning("Invalid ADMIN_USER_ID in environment variables")

    return False


# Get account type emoji
def get_account_type_emoji(account_type):
    return ACCOUNT_TYPE_EMOJIS.get(account_type, account_type)


# Validate emoji
def validate_emoji(emoji):
    if not emoji:
        return True

    custom_emoji_pattern = r"<a?:\w+:\d+>"
    return any(ord(c) > 255 for c in emoji) or re.match(custom_emoji_pattern, emoji)
