# utils/logging_setup.py - Logging setup
import logging
from logging.handlers import RotatingFileHandler


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

    # File handler with rotation (10MB max per file, keeping 5 backup files)
    file_handler = RotatingFileHandler(
        "bot.log", maxBytes=10 * 1024 * 1024, backupCount=5, mode="a"
    )
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    return logger
