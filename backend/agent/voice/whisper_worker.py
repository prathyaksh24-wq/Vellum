"""Offline Whisper inference in the isolated voice model-worker protocol."""

from __future__ import annotations

import base64
from contextlib import redirect_stdout
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import threading
import traceback

from lfm_worker import _watch_parent

_OUTPUT = sys.stdout


def emit(kind: str, **data) -> None:
    _OUTPUT.write(json.dumps({"type": kind, **data}, ensure_ascii=True) + "\n")
    _OUTPUT.flush()


def load_model():
    # CUDA can enumerate successfully while the DLLs needed by inference are
    # missing. Exercise the encoder before reporting the chosen device ready.
    dll_handles = []
    if os.name == "nt":
        # Reuse CUDA libraries already installed for local voice when present;
        # CPU fallback remains self-contained on installations without them.
        # session launches this file from the repository root.
        dll_dir = Path.cwd() / "data/models/lfm2.5-audio/.venv/Lib/site-packages/torch/lib"
        if dll_dir.is_dir():
            dll_handles.append(os.add_dll_directory(str(dll_dir)))
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
    import ctranslate2
    import numpy as np
    from faster_whisper import WhisperModel

    root = Path(os.environ["VELLUM_DICTATION_MODEL_DIR"])
    requested = os.getenv("VELLUM_DICTATION_DEVICE", "auto")
    candidates = ["cuda", "cpu"] if requested == "auto" else [requested]
    for device in candidates:
        try:
            if device == "cuda" and not ctranslate2.get_cuda_device_count():
                raise RuntimeError("No CUDA device is available.")
            model = WhisperModel(str(root), device=device, compute_type="float16" if device == "cuda" else "int8",
                                 cpu_threads=4, num_workers=1, local_files_only=True)
            model.encode(np.zeros((model.feature_extractor.mel_filters.shape[0], 3000), dtype=np.float32))
            return model, device, dll_handles
        except Exception:
            traceback.print_exc(file=sys.stderr)
            if device == candidates[-1]:
                raise
    raise RuntimeError("No local transcription device is available.")


def main() -> int:
    threading.Thread(target=_watch_parent, daemon=True).start()
    try:
        with redirect_stdout(sys.stderr):
            model, device, dll_handles = load_model()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        emit("startup_error", message="Local Whisper could not load. Check the dictation worker log.")
        return 1
    emit("ready", device=device, model=os.getenv("VELLUM_DICTATION_MODEL_ID", "local/whisper"))
    for line in sys.stdin.buffer:
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("request_id", ""))
            if request.get("type") != "turn":
                raise ValueError("Unknown dictation request.")
            audio = base64.b64decode(request["audio_b64"], validate=True)
            language=request.get('language')
            if language is not None and language not in model.supported_languages:
                raise ValueError('The installed model does not support this language.')
            with redirect_stdout(sys.stderr):
                segments, info = model.transcribe(BytesIO(audio), task="transcribe", language=language,
                                                  hotwords=', '.join(request.get('dictionary') or []) or None,
                                                  vad_filter=True, beam_size=5, condition_on_previous_text=False)
                text = " ".join(segment.text.strip() for segment in segments).strip()
            emit("transcript", request_id=request_id, text=text, language=info.language)
            emit("completed", request_id=request_id)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            emit("error", request_id=request_id, message="Local transcription failed. Try recording again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
