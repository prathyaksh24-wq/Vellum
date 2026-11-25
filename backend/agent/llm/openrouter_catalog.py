"""OpenRouter's live model list, narrowed to models Vellum can actually use.

Same approach as DeepSeek Harness (pi-ai ``personalizeOpenRouterCatalog``):
ask OpenRouter which models exist instead of hand-maintaining a list. With the
user's key, ``GET /models/user`` returns the models that key may use; without
one (or when that endpoint refuses), the public ``GET /models`` is used.

A model is shown only when it can serve a Vellum turn:

- it writes text and supports tool calling (the agent always sends tools), and
- it has at least one zero-data-retention endpoint (``GET /endpoints/zdr``),
  because every Vellum request carries ``zdr: true`` and
  ``data_collection: deny``; OpenRouter refuses other models outright.

The list is cached for an hour. When OpenRouter cannot be reached the last good
list is kept, and with none the static reviewed catalog stays in use.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60 * 60
RETRY_AFTER_FAILURE_SECONDS = 5 * 60
REQUEST_TIMEOUT_SECONDS = 8.0

_lock = threading.Lock()
_cached: tuple[Any, ...] | None = None
_checked_at = 0.0
_failed_at = 0.0


def _get_json(client: httpx.Client, url: str, headers: dict[str, str]) -> Any:
    response = client.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def _label(raw: dict[str, Any], model_id: str) -> str:
    name = str(raw.get("name") or model_id).strip()
    # "Anthropic: Claude Fable 5" -> "Claude Fable 5"; the row logo shows the vendor.
    vendor, sep, rest = name.partition(": ")
    return rest.strip() if sep and rest.strip() else name


def build_entries(models: list[Any], zdr_endpoints: list[Any], entry_type: Callable[..., Any]) -> tuple[Any, ...]:
    """Turn OpenRouter's model and ZDR-endpoint lists into picker entries."""
    zdr_ids = {
        str(item.get("model_id") or "")
        for item in zdr_endpoints
        if isinstance(item, dict)
    }
    entries: list[Any] = []
    seen: set[str] = set()
    for raw in models:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or "").strip()
        if not model_id or "/" not in model_id or model_id in seen or ":" in model_id:
            # ":batch", ":free" and similar variants share the base model's entry.
            continue
        architecture = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
        outputs = architecture.get("output_modalities") or ["text"]
        params = raw.get("supported_parameters") or []
        if "text" not in outputs or "tools" not in params or model_id not in zdr_ids:
            continue
        seen.add(model_id)
        top = raw.get("top_provider") if isinstance(raw.get("top_provider"), dict) else {}
        try:
            context = int(top.get("context_length") or raw.get("context_length") or 0) or 128_000
        except (TypeError, ValueError):
            context = 128_000
        capabilities = ["completion", "tools"]
        if "image" in (architecture.get("input_modalities") or []):
            capabilities.append("vision")
        entries.append(
            entry_type(
                id=model_id,
                label=_label(raw, model_id),
                provider=model_id.split("/", 1)[0],
                context=context,
                tier="flagship",
                open_weights=bool(raw.get("hugging_face_id")),
                capabilities=tuple(capabilities),
                tool_calling_compatibility="compatible",
            )
        )
    return tuple(entries)


def fetch_live_catalog(api_key: str, base_url: str, entry_type: Callable[..., Any]) -> tuple[Any, ...]:
    root = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
    headers = {"Accept": "application/json"}
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        models_payload: Any = None
        if api_key:
            try:
                models_payload = _get_json(client, f"{root}/models/user", {**headers, "Authorization": f"Bearer {api_key}"})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {401, 403, 404}:
                    raise
        if models_payload is None:
            models_payload = _get_json(client, f"{root}/models", headers)
        zdr_payload = _get_json(client, f"{root}/endpoints/zdr", headers)
    models = models_payload.get("data") if isinstance(models_payload, dict) else None
    zdr = zdr_payload.get("data") if isinstance(zdr_payload, dict) else None
    if not isinstance(models, list) or not isinstance(zdr, list):
        raise ValueError("OpenRouter returned an invalid model list")
    return build_entries(models, zdr, entry_type)


def live_openrouter_models(entry_type: Callable[..., Any], *, force: bool = False) -> tuple[Any, ...] | None:
    """The cached live catalog, refreshed hourly; None until a fetch succeeds."""
    global _cached, _checked_at, _failed_at
    now = time.monotonic()
    with _lock:
        fresh = _cached is not None and now - _checked_at < CACHE_TTL_SECONDS
        backing_off = now - _failed_at < RETRY_AFTER_FAILURE_SECONDS
        if not force and (fresh or (backing_off and _failed_at)):
            return _cached
    from agent.config import get_settings

    settings = get_settings()
    secret = settings.openrouter_api_key
    key = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret or "")
    if not key:
        return None
    try:
        entries = fetch_live_catalog(key, settings.openrouter_base_url, entry_type)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("[MODELS] OpenRouter model list unavailable (%s); keeping the last list.", type(exc).__name__)
        with _lock:
            _failed_at = time.monotonic()
            return _cached
    with _lock:
        if entries:
            _cached = entries
        _checked_at = time.monotonic()
        _failed_at = 0.0
        return _cached


def cached_live_models() -> tuple[Any, ...]:
    """The last successful list, without network work."""
    with _lock:
        return _cached or ()


def live_model_ids() -> frozenset[str]:
    """IDs from the last successful fetch, without network work (for the privacy broker)."""
    return frozenset(entry.id for entry in cached_live_models())


def reset_cache() -> None:
    global _cached, _checked_at, _failed_at
    with _lock:
        _cached, _checked_at, _failed_at = None, 0.0, 0.0
