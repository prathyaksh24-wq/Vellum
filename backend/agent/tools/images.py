"""Deferred image generation using Vellum's existing image client and key."""
from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import uuid4

from langchain_core.tools import tool

from agent.config import REPO_ROOT, SOURCE_ROOT, get_settings
from agent.plugins.registry import get_plugin_registry
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber


@lru_cache(maxsize=1)
def _client():
    spec = importlib.util.spec_from_file_location("vellum_image_client", SOURCE_ROOT / "scripts" / "openai_image_client.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Image client unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _edit_image(path: str, temporary: Path) -> Path:
    """Confine explicit edit inputs and strip metadata before cloud upload."""
    from PIL import Image
    from agent.obsidian.folder_policy import can_send_to_llm

    candidate = Path(path).expanduser().resolve()
    vault = get_settings().obsidian_vault_path.resolve()
    generated = (REPO_ROOT / "data" / "images").resolve()
    if not candidate.is_relative_to(generated):
        if not candidate.is_relative_to(vault) or not can_send_to_llm(candidate.relative_to(vault).as_posix()):
            raise ValueError("Choose an image in an allowed vault folder or Vellum's generated image folder.")
    if not candidate.is_file() or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Choose an existing PNG, JPEG or WebP image.")
    if candidate.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Edit images must be 10 MiB or smaller.")
    with Image.open(candidate) as original:
        if original.width * original.height > 25_000_000:
            raise ValueError("Edit image exceeds the pixel limit.")
        clean = Image.new("RGBA", original.size)
        clean.paste(original.convert("RGBA"))
        clean.save(temporary, format="PNG")
    return temporary


def _execute_image(
    action: Literal["status", "generate", "edit"] = "status",
    prompt: str = "", image_path: str = "",
    size: Literal["1024x1024", "1536x1024", "1024x1536", "auto"] = "1024x1024",
    background: Literal["auto", "opaque", "transparent"] = "auto",
    confirm: bool = False,
) -> str:
    """Execute only after the owning App Action verifies its bound review."""
    settings = get_settings()
    enabled = get_plugin_registry().is_enabled("openai-system-skills")
    configured = bool(settings.openai_api_key)
    if action == "status":
        return json.dumps({"ok": True, "enabled": enabled, "configured": configured,
                           "cloud": True, "privacy_mode": settings.privacy_mode,
                           "operations": ["generate", "edit"], "requires_confirmation": True})
    if not enabled or not configured:
        return json.dumps({"ok": False, "error": "Enable OpenAI System Skills and configure OpenAI in Vellum settings."})
    if settings.privacy_mode == "local_only":
        return json.dumps({"ok": False, "error": "Image generation sends data to OpenAI and is disabled in local-only mode."})
    if not confirm:
        return json.dumps({"ok": False, "error": "Confirm sending this prompt and any selected edit image to OpenAI before generation. API usage charges may apply."})
    prompt = prompt.strip()
    if not prompt or len(prompt) > 16000 or (action == "edit" and not image_path) or (action == "generate" and image_path):
        return json.dumps({"ok": False, "error": "Provide a prompt up to 16000 characters and an image path only for an edit."})
    classification, _ = classify(prompt)
    if classification is DataClass.RED:
        return json.dumps({"ok": False, "error": "Sensitive content is blocked from image generation."})
    if settings.privacy_mode == "protect_for_me":
        prompt, _ = PrivacyScrubber().scrub(prompt)
    directory = REPO_ROOT / "data" / "images"
    temporary = directory / (".edit-" + uuid4().hex + ".png")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        image = _edit_image(image_path, temporary) if action == "edit" else None
        result = _client().generate_image_file(
            prompt=prompt, api_key=settings.openai_api_key, base_url=settings.openai_base_url,
            output_dir=directory, size=size, background=background, image_path=image,
        )
        return json.dumps({"ok": True, "action": action, "provider": "OpenAI", **result})
    except Exception:
        # Do not echo HTTP payloads, private prompts, paths or credentials.
        return json.dumps({"ok": False, "error": "Image generation did not complete. Check the selected image, OpenAI image access and connection before retrying."})
    finally:
        temporary.unlink(missing_ok=True)


@tool
def image_generate(
    action: Literal["status", "generate", "edit"] = "status", prompt: str = "", image_path: str = "",
    size: Literal["1024x1024", "1536x1024", "1024x1536", "auto"] = "1024x1024",
    background: Literal["auto", "opaque", "transparent"] = "auto",
) -> str:
    """Check local image readiness, or prepare a reviewed OpenAI image generation/edit. A write returns a Vellum confirmation; never confirm it yourself or claim the image exists before an applied receipt."""
    if action == "status":
        return _execute_image(action="status")
    from agent.contracts.images import ImageGenerationRequest
    from agent.tools.app_actions import app_action
    try:
        request = ImageGenerationRequest(action=action, prompt=prompt, image_path=image_path, size=size, background=background)
    except ValueError:
        return json.dumps({"ok": False, "error": "Check the image operation, prompt and edit target."})
    return app_action.invoke({"operation": "execute", "action_id": "image.generate", "arguments": request.model_dump()})
