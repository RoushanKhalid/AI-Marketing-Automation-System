"""
services/image_generator.py — Pollinations.AI image URL generator.

ImageGenerator builds a Pollinations.AI image URL from a prompt string.
No HTTP request is made at generation time — the URL itself is the
deliverable, and Pollinations resolves the image lazily when visited.

Free tier: https://pollinations.ai — no API key required.
"""

from __future__ import annotations

import urllib.parse

from app.logger import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://image.pollinations.ai/prompt/{}"
_MAX_PROMPT_LENGTH = 500


class ImageGenerator:
    """Constructs Pollinations.AI image URLs from marketing prompts."""

    def generate(self, prompt: str) -> str:
        """Build and return a Pollinations.AI image URL for the given prompt.

        The URL is constructed by URL-encoding the prompt and interpolating
        it into the Pollinations.AI endpoint template. No network call is
        made during this method.

        Args:
            prompt: Natural-language description of the desired image.
                    Must be 1–500 non-whitespace characters.

        Returns:
            A fully-formed Pollinations.AI image URL string.

        Raises:
            ValueError: If the prompt is empty, whitespace-only, or exceeds
                        500 characters.
        """
        if not prompt or not prompt.strip():
            raise ValueError(
                "Image prompt must be non-empty and non-whitespace."
            )
        if len(prompt) > _MAX_PROMPT_LENGTH:
            raise ValueError(
                f"Image prompt must not exceed {_MAX_PROMPT_LENGTH} characters "
                f"(received {len(prompt)})."
            )

        encoded = urllib.parse.quote_plus(prompt.strip())
        url = _BASE_URL.format(encoded)
        logger.debug("Generated image URL: %s", url)
        return url
