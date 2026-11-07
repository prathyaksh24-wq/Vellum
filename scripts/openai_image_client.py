"""Minimal OpenAI image generation client for X media workflows."""
from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-1"
DEFAULT_SIZE = "1024x1024"
DEFAULT_OUTPUT_DIR = Path(os.environ.get("VELLUM_WORKSPACE_ROOT", Path(__file__).resolve().parents[1])) / "data" / "x" / "generated-images"
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
    background: str = "auto",
    image_path: Path | None = None,
) -> dict[str, Any]:
    prompt = prompt.strip()
    if not prompt:
        raise ImageGenerationError("Image prompt is required.")
    resolved_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not resolved_key:
        raise ImageGenerationError("OPENAI_API_KEY is required for image generation.")
    if size not in {"1024x1024", "1536x1024", "1024x1536", "auto"} or background not in {"auto", "opaque", "transparent"}:
        raise ImageGenerationError("Unsupported image size or background.")
    parameters = {"model": model, "prompt": prompt, "size": size, "n": 1, "background": background}
    headers = {"Authorization": f"Bearer {resolved_key}"}
    if image_path is not None:
        # The runtime caller authorizes and confines edit input before this seam.
        with Path(image_path).open("rb") as image:
            response = httpx.post(
                f"{base_url.rstrip('/')}/images/edits", headers=headers,
                data={key: str(value) for key, value in parameters.items()},
                files={"image": (Path(image_path).name, image, "image/png")}, timeout=timeout_secs,
            )
    else:
        response = httpx.post(
            f"{base_url.rstrip('/')}/images/generations", headers=headers,
            json=parameters, timeout=timeout_secs,
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
    try:
        image_bytes = base64.b64decode(b64_json, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ImageGenerationError("OpenAI returned invalid image data.") from exc
    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ImageGenerationError("OpenAI did not return a PNG image.")
    path = directory / f"generated-{uuid4().hex}.png"
    with path.open("xb") as output:
        output.write(image_bytes)
    return {"path": str(path), "model": model, "size": size}
