"""Download local voice model assets for Vellum.

This script is intentionally idempotent: existing files are reused.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from agent.config import get_settings


KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def _download(url: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 0:
        print(f"exists: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    print(f"download: {url}")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(target)
    print(f"wrote: {target}")


def download_kokoro(root: Path) -> None:
    kokoro_dir = root / "kokoro"
    for name, url in KOKORO_FILES.items():
        _download(url, kokoro_dir / name)


def warm_moonshine(root: Path) -> None:
    moonshine_dir = root / "moonshine"
    moonshine_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MOONSHINE_VOICE_CACHE", str(moonshine_dir))
    try:
        from moonshine_voice import ModelArch, get_model_for_language
    except ImportError as exc:
        raise SystemExit("moonshine-voice is not installed. Install backend requirements first.") from exc

    model_name = get_settings().voice_stt_model
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
    model_arch = arch_by_name.get(model_name)
    if model_arch is None:
        raise SystemExit(f"unsupported Moonshine model: {model_name}")
    model_path, model_arch = get_model_for_language("en", model_arch, cache_root=moonshine_dir)
    print(f"moonshine: {model_path} ({model_arch})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare local STT/TTS models for Vellum voice.")
    parser.add_argument("--root", type=Path, default=None, help="Voice model directory. Defaults to VOICE_MODEL_DIR.")
    parser.add_argument("--skip-kokoro", action="store_true", help="Do not download Kokoro files.")
    parser.add_argument("--skip-moonshine", action="store_true", help="Do not warm Moonshine cache.")
    args = parser.parse_args()

    root = (args.root or get_settings().voice_model_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not args.skip_kokoro:
        download_kokoro(root)
    if not args.skip_moonshine:
        warm_moonshine(root)


if __name__ == "__main__":
    main()
