# utils/logging_setup.py - Logging setup
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clear existing handlers to avoid duplicates
    logger.handlers = []

    # Format with more details
    log_format = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] %(funcName)s - %(message)s"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # Create logs directory if it doesn't exist
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    # File handler with daily rotation at midnight
    log_file = os.path.join(logs_dir, "latest.log")
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,  # Keep a month of logs
        encoding="utf-8",
        delay=False,
    )

    # Custom namer function to use ISO 8601 date format (the superior date format)
    def namer(default_name):
        # default_name will be like: logs/latest.log.YYYY-MM-DD
        base_filename, extension = os.path.splitext(default_name)
        # Extract date part from extension (remove the dot)
        date_str = extension[1:] if extension else datetime.now().strftime("%Y-%m-%d")
        # Return new name: logs/YYYY-MM-DD.log
        return os.path.join(logs_dir, f"{date_str}.log")

    file_handler.namer = namer
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    return logger
