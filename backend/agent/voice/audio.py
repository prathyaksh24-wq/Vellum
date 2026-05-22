"""Small audio helpers for local voice I/O."""

from __future__ import annotations

from io import BytesIO
import wave

import numpy as np


def decode_wav_mono_float32(data: bytes) -> tuple[np.ndarray, int]:
    if not data:
        raise ValueError("audio is empty")
    try:
        with wave.open(BytesIO(data), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except wave.Error as exc:
        raise ValueError("audio must be a WAV file") from exc

    if sample_rate <= 0:
        raise ValueError("audio sample rate is invalid")
    if sample_width not in (1, 2, 4):
        raise ValueError("audio sample width is unsupported")

    if sample_width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    else:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples.astype(np.float32, copy=False), sample_rate


def encode_wav_mono_float32(samples, sample_rate: int) -> bytes:
    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    arr = np.clip(arr, -1.0, 1.0)
    pcm = (arr * 32767.0).astype("<i2").tobytes()
    out = BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm)
    return out.getvalue()

