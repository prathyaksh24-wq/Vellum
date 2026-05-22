"""Text-to-speech providers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent.config import get_settings
from agent.voice.audio import encode_wav_mono_float32


class TextToSpeech(Protocol):
    def synthesize_wav(self, text: str) -> bytes:
        ...


class KokoroSpeaker:
    def __init__(self, voice: str = "af_heart", speed: float = 1.0, model_dir: Path | None = None):
        self.voice = voice
        self.speed = speed
        self.model_dir = model_dir
        self._kokoro = None

    def _load(self):
        if self._kokoro is not None:
            return self._kokoro
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise RuntimeError("kokoro-onnx is not installed") from exc
        settings = get_settings()
        model_dir = self.model_dir or settings.voice_model_dir / "kokoro"
        model_path = model_dir / "kokoro-v1.0.onnx"
        voices_path = model_dir / "voices-v1.0.bin"
        if not model_path.exists() or not voices_path.exists():
            raise RuntimeError(f"Kokoro model files are missing in {model_dir}")
        self._kokoro = Kokoro(str(model_path), str(voices_path))
        return self._kokoro

    def synthesize_wav(self, text: str) -> bytes:
        clean = " ".join((text or "").split())
        if not clean:
            raise ValueError("text cannot be empty")
        samples, sample_rate = self._load().create(
            clean,
            voice=self.voice,
            speed=float(self.speed),
            lang="en-us",
        )
        return encode_wav_mono_float32(samples, int(sample_rate))


_tts_singleton: TextToSpeech | None = None


def get_tts_engine() -> TextToSpeech:
    global _tts_singleton
    if _tts_singleton is None:
        settings = get_settings()
        if not settings.voice_enabled:
            raise RuntimeError("voice is disabled")
        if settings.voice_tts_engine != "kokoro":
            raise RuntimeError(f"unsupported TTS engine: {settings.voice_tts_engine}")
        _tts_singleton = KokoroSpeaker(
            voice=settings.voice_tts_voice,
            speed=settings.voice_tts_speed,
            model_dir=settings.voice_model_dir / "kokoro",
        )
    return _tts_singleton

