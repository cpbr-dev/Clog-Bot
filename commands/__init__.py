# commands/__init__.py - Command registration
from .admin_commands import register_admin_commands
from .user_commands import register_user_commands


def register_all_commands(bot):
    """Register all commands with the bot"""
    register_admin_commands(bot)
    register_user_commands(bot)
