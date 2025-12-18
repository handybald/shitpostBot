"""Logging configuration for ShitPostBot"""

import logging
import logging.handlers
from pathlib import Path
from src.utils.config_loader import get_config_instance

# Create logs directory if it doesn't exist
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def setup_logger(name: str) -> logging.Logger:
    """Setup logger with file and console handlers"""
    config = get_config_instance()

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Don't add handlers if already configured
    if logger.handlers:
        return logger

    # Format
    formatter = logging.Formatter(
        config.get("logging.format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler with rotation
    log_file = LOG_DIR / config.get("logging.file", "bot.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=config.get("logging.max_bytes", 10485760),
        backupCount=config.get("logging.backup_count", 5)
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get or create logger"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
