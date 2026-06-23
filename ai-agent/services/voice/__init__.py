"""Voice adapters — STT and TTS via OpenAI API."""

from services.voice.stt import transcribe_audio
from services.voice.tts import synthesize_speech

__all__ = ["transcribe_audio", "synthesize_speech"]
