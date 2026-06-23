"""Speech-to-text via OpenAI Whisper API."""

from __future__ import annotations

import io
import logging
from typing import Optional

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)


def _openai_client() -> OpenAI:
    kwargs = {"api_key": settings.OPENAI_API_KEY}
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return OpenAI(**kwargs)


def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    language: Optional[str] = None,
) -> str:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")

    client = _openai_client()
    buffer = io.BytesIO(audio_bytes)
    buffer.name = filename

    kwargs: dict = {
        "model": settings.OPENAI_WHISPER_MODEL,
        "file": buffer,
    }
    if language:
        kwargs["language"] = language

    logger.info("Transcribing %d bytes with %s", len(audio_bytes), settings.OPENAI_WHISPER_MODEL)
    result = client.audio.transcriptions.create(**kwargs)
    text = (result.text or "").strip()
    if not text:
        raise ValueError("No speech detected in audio")
    return text
