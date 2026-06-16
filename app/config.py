"""
config.py — Environment configuration loader.

Reads all settings from the .env file (or real environment variables)
using python-dotenv and exposes them as a typed Config singleton.
Raises EnvironmentError at import time if any required key is missing.
"""

import os
from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
load_dotenv()


class Config:
    """Centralised access point for all application configuration."""

    # --- Required ---
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()

    # --- Optional with defaults ---
    DB_PATH: str = os.getenv("DB_PATH", "campaigns.db").strip()
    SCHEDULER_INTERVAL_SECONDS: int = int(
        os.getenv("SCHEDULER_INTERVAL_SECONDS", "30")
    )

    @classmethod
    def validate(cls) -> None:
        """Validate that all required configuration values are present.

        Raises:
            EnvironmentError: If GROQ_API_KEY is missing or empty.
        """
        if not cls.GROQ_API_KEY:
            # Inline import to prevent circular dependency
            from app.logger import get_logger
            logger = get_logger("app.config")
            logger.error("Configuration error: GROQ_API_KEY is missing or empty.")
            raise EnvironmentError(
                "GROQ_API_KEY is missing or empty. "
                "Please set it in your .env file or as an environment variable."
            )


# Eagerly validate so the app fails fast at startup if misconfigured
Config.validate()
