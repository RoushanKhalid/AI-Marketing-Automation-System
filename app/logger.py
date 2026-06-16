"""
logger.py — Application-wide logging setup.

Configures a single root logger that writes to:
  - stdout (StreamHandler)
  - app.log in the project root (RotatingFileHandler, 5 MB max, 3 backups)

Usage:
    from app.logger import get_logger
    logger = get_logger(__name__)
"""

import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LOG_FILE = "app.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3

_configured = False


def _localtime_converter(timestamp: float) -> time.struct_time:
    tz_name = os.getenv("TZ", "UTC")
    try:
        zone = ZoneInfo(tz_name)
        dt = datetime.fromtimestamp(timestamp, tz=zone)
        return dt.timetuple()
    except ZoneInfoNotFoundError:
        return time.localtime(timestamp)


def _configure_root_logger() -> None:
    """Set up handlers on the root logger exactly once."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    formatter.converter = _localtime_converter

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    # Rotating file handler
    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root.addHandler(console_handler)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, ensuring root logger is configured first.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    _configure_root_logger()
    return logging.getLogger(name)
