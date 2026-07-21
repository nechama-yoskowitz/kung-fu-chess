"""
Centralized logging configuration for Kung-Fu Chess.

Call setup_logging() once at application startup.
Supports:
- Console handler (always)
- Optional rotating file handler
- Configurable log level via KFC_LOG_LEVEL environment variable
- Safe to call multiple times (idempotent)
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_DIR = "logs"
SERVER_LOG_FILE = "server.log"
CLIENT_LOG_FILE = "client.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3

_configured = False


def setup_logging(
    level: str | None = None,
    enable_file: bool = False,
    log_file: str = SERVER_LOG_FILE,
) -> None:
    """
    Configure the root logger with console and optional file output.

    Parameters
    ----------
    level : str | None
        Log level name (DEBUG, INFO, WARNING, ERROR).
        Falls back to KFC_LOG_LEVEL env var, then DEFAULT_LOG_LEVEL.
    enable_file : bool
        Whether to add a rotating file handler.
    log_file : str
        Filename for the rotating file handler (inside LOG_DIR).
    """
    global _configured

    # Determine level
    if level is None:
        level = os.environ.get("KFC_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()

    # Idempotent: skip if already configured
    if _configured:
        root.setLevel(numeric_level)
        return

    root.setLevel(numeric_level)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(console)

    # Optional file handler
    if enable_file:
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / log_file,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        root.addHandler(file_handler)

    _configured = True


def reset_logging() -> None:
    """Reset the configured flag (for testing)."""
    global _configured
    _configured = False
