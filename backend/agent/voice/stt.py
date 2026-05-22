"""Speech-to-text providers."""

from __future__ import annotations

import os
from typing import Protocol

from agent.config import get_settings
from agent.voice.audio import decode_wav_mono_float32


class SpeechToText(Protocol):
    engine: str
    model: str

    def transcribe_wav(self, audio_bytes: bytes) -> str:
        ...


class MoonshineTranscriber:
    engine = "moonshine"

    def __init__(self, model: str = "tiny"):
        self.model = model
        self._transcriber = None

    def _load(self):
        if self._transcriber is not None:
            return self._transcriber
        settings = get_settings()
        cache_dir = settings.voice_model_dir / "moonshine"
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MOONSHINE_VOICE_CACHE", str(cache_dir))
        try:
            from moonshine_voice import ModelArch, Transcriber, get_model_for_language
        except ImportError as exc:
            raise RuntimeError("moonshine-voice is not installed") from exc

        arch_by_name = {
            "tiny": ModelArch.TINY_STREAMING,
            "tiny-streaming": ModelArch.TINY_STREAMING,
            "base": ModelArch.BASE_STREAMING,
            "base-streaming": ModelArch.BASE_STREAMING,
            "small": ModelArch.SMALL_STREAMING,
            "small-streaming": ModelArch.SMALL_STREAMING,
            "medium": ModelArch.MEDIUM_STREAMING,
            "medium-streaming": ModelArch.MEDIUM_STREAMING,
        }
        model_arch = arch_by_name.get(self.model)
        if model_arch is None:
            raise RuntimeError(f"unsupported Moonshine model: {self.model}")
        model_path, model_arch = get_model_for_language("en", model_arch, cache_root=cache_dir)
        self._transcriber = Transcriber(model_path=model_path, model_arch=model_arch)
        return self._transcriber

    def transcribe_wav(self, audio_bytes: bytes) -> str:
        samples, sample_rate = decode_wav_mono_float32(audio_bytes)
        transcript = self._load().transcribe_without_streaming(samples, sample_rate)
        lines = getattr(transcript, "lines", []) or []
        text = " ".join(str(getattr(line, "text", "")).strip() for line in lines)
        return " ".join(text.split())


_stt_singleton: SpeechToText | None = None


def get_stt_engine() -> SpeechToText:
    global _stt_singleton
    if _stt_singleton is None:
        settings = get_settings()
        if not settings.voice_enabled:
            raise RuntimeError("voice is disabled")
        if settings.voice_stt_engine != "moonshine":
            raise RuntimeError(f"unsupported STT engine: {settings.voice_stt_engine}")
        _stt_singleton = MoonshineTranscriber(model=settings.voice_stt_model)
    return _stt_singleton
