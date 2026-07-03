"""Minimal OpenAI image generation client for X media workflows."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-1"
DEFAULT_SIZE = "1024x1024"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "x" / "generated-images"
DEFAULT_TIMEOUT_SECS = 120


class ImageGenerationError(RuntimeError):
    """Image generation failed."""


def generate_image_file(
    *,
    prompt: str,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    timeout_secs: int = DEFAULT_TIMEOUT_SECS,
) -> dict[str, Any]:
    prompt = prompt.strip()
    if not prompt:
        raise ImageGenerationError("Image prompt is required.")
    resolved_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not resolved_key:
        raise ImageGenerationError("OPENAI_API_KEY is required for image generation.")

    response = httpx.post(
        f"{base_url.rstrip('/')}/images/generations",
        headers={"Authorization": f"Bearer {resolved_key}", "Content-Type": "application/json"},
        json={"model": model, "prompt": prompt, "size": size, "n": 1},
        timeout=timeout_secs,
    )
    if response.status_code in (401, 403):
        raise ImageGenerationError("OpenAI image generation authentication failed.")
    if response.status_code >= 400:
        raise ImageGenerationError(f"OpenAI image generation returned HTTP {response.status_code}.")
    payload = response.json()
    items = payload.get("data") if isinstance(payload, dict) else None
    first = items[0] if isinstance(items, list) and items else {}
    b64_json = first.get("b64_json") if isinstance(first, dict) else None
    if not isinstance(b64_json, str) or not b64_json:
        raise ImageGenerationError("OpenAI image generation did not return b64_json image data.")

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    image_id = str(first.get("id") or "generated").replace("/", "_")
    path = directory / f"{image_id}.png"
    path.write_bytes(base64.b64decode(b64_json))
    return {"path": str(path), "model": model, "size": size}
