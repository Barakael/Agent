"""Text-to-speech via OpenAI TTS API."""

from __future__ import annotations

import logging

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)


def _openai_client() -> OpenAI:
    kwargs = {"api_key": settings.OPENAI_API_KEY}
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return OpenAI(**kwargs)


def synthesize_speech(text: str) -> bytes:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")

    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Text is empty")

    max_chars = settings.OPENAI_TTS_MAX_CHARS
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3] + "..."

    client = _openai_client()
    logger.info("TTS %d chars voice=%s", len(cleaned), settings.OPENAI_TTS_VOICE)
    response = client.audio.speech.create(
        model=settings.OPENAI_TTS_MODEL,
        voice=settings.OPENAI_TTS_VOICE,
        input=cleaned,
    )
    return response.content
