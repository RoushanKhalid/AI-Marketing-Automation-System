"""
services/text_generator.py — Groq-powered marketing text generator.

TextGenerator calls the Groq chat completions API using the free
llama3-8b-8192 model to produce compelling marketing copy from a prompt.
"""

from __future__ import annotations

from groq import Groq, GroqError

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a creative marketing copywriter. Write a compelling, concise, and "
    "persuasive marketing message based on the user's prompt. Keep it engaging "
    "and professional. Do not use newlines, markdown formatting, or placeholders "
    "(such as [Name] or [Link]). Write the message as a single, complete paragraph."
)
_MAX_PROMPT_LENGTH = 10_000
_MODEL = "llama-3.1-8b-instant"


class TextGenerator:
    """Generates marketing copy by calling the Groq LLM API."""

    def __init__(self) -> None:
        """Initialise the Groq client using GROQ_API_KEY from config.

        Raises:
            EnvironmentError: If GROQ_API_KEY is absent (propagated from Config).
        """
        self._client = Groq(api_key=Config.GROQ_API_KEY)
        logger.info("TextGenerator initialised — model: %s", _MODEL)

    def generate(self, prompt: str) -> str:
        """Generate marketing text for the given prompt.

        Args:
            prompt: Natural-language description of the desired marketing content.
                    Must be between 1 and 10,000 characters.

        Returns:
            Generated marketing text as a non-empty string.

        Raises:
            ValueError: If the prompt is empty or exceeds the length limit.
            RuntimeError: If the Groq API call fails.
        """
        # --- Validate input ---
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty or whitespace.")
        if len(prompt) > _MAX_PROMPT_LENGTH:
            raise ValueError(
                f"Prompt exceeds the maximum allowed length of {_MAX_PROMPT_LENGTH} characters."
            )

        logger.info("Generating marketing text — prompt: %.80r...", prompt)

        try:
            response = self._client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_tokens=512,
            )
            generated_text: str = response.choices[0].message.content.strip()
            # Strip any markdown bold/italic asterisks
            generated_text = generated_text.replace("**", "").replace("*", "")
            logger.debug("Text generation successful — %d chars produced.", len(generated_text))
            return generated_text

        except GroqError as exc:
            logger.error("Groq API error during text generation: %s", exc)
            raise RuntimeError(f"Text generation failed — Groq API error: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error during text generation: %s", exc)
            raise RuntimeError(f"Text generation failed — unexpected error: {exc}") from exc
