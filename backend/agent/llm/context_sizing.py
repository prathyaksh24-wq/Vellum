"""Choose each local model's context window from what this computer can hold.

A larger window costs GPU memory for the attention cache. How much depends on
the model's architecture (sliding-window models such as Gemma 4 grow far more
slowly than dense ones), so Vellum measures instead of estimating: it loads
the model at a candidate window and asks Ollama how much of it landed in GPU
memory (`/api/ps` `size_vram` against `size`). The largest window that keeps
the whole model on the GPU wins. This works on NVIDIA, AMD and Apple GPUs
alike, because Ollama reports the placement it actually made.

Precedence for a local model's window:
1. `OLLAMA_CONTEXT_LENGTH` set explicitly in the environment or `.env`;
2. the user's choice in Settings (Context window);
3. the measured window for this model;
4. 32,768 until a measurement exists.
Hosted models use their own limit unless `CLOUD_CONTEXT_LENGTH` or the
Settings cap applies.

Only counts and window sizes are stored, in data/llm-routing/context-sizing.json.
Measurement loads the model a few times, so it runs once per model, in the
background, after a reply has finished.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)
# Largest first. Above 131,072 a local model's prompt processing becomes the
# limit before memory does, so automatic sizing stops there; Settings can go higher.
CANDIDATES = (131_072, 65_536, 32_768, 16_384)
DEFAULT_WINDOW = 32_768
CPU_WINDOW = 32_768          # no GPU placement: speed, not memory, is the limit
CHOICES = (8_192, 16_384, 32_768, 65_536, 131_072, 262_144)
CLOUD_CHOICES = (32_768, 65_536, 131_072, 200_000, 262_144, 500_000, 1_000_000)
_lock = threading.Lock()
_attempted: set[str] = set()


def sizing_path() -> Path:
    from agent.config import REPO_ROOT
    return Path(REPO_ROOT) / "data" / "llm-routing" / "context-sizing.json"


def _read(path: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads((path or sizing_path()).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or sizing_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


def _explicit(settings, field: str) -> bool:
    return field in getattr(settings, "model_fields_set", set())


# -- preferences (Settings → Context window) ----------------------------------
def preferences(path: Path | None = None) -> dict[str, Any]:
    prefs = _read(path).get("preferences") or {}
    local = prefs.get("local", "auto")
    cloud = prefs.get("cloud", "full")
    return {"local": local if local == "auto" or local in CHOICES else "auto",
            "cloud": cloud if cloud == "full" or cloud in CLOUD_CHOICES else "full"}


def set_preferences(*, local: Any = None, cloud: Any = None, path: Path | None = None) -> dict[str, Any]:
    if local is not None and local != "auto" and local not in CHOICES:
        raise ValueError("Choose Automatic or a supported local window.")
    if cloud is not None and cloud != "full" and cloud not in CLOUD_CHOICES:
        raise ValueError("Choose Full or a supported hosted-model cap.")
    with _lock:
        data = _read(path)
        prefs = {**preferences(path)}
        if local is not None:
            prefs["local"] = local
        if cloud is not None:
            prefs["cloud"] = cloud
        data["preferences"] = prefs
        _write(data, path)
    return prefs


# -- resolution -----------------------------------------------------------------
def local_window(model_id: str, settings, *, path: Path | None = None) -> int:
    """The window a local model runs at, by the precedence in the module docstring."""
    if _explicit(settings, "ollama_context_length"):
        return int(settings.ollama_context_length)
    data = _read(path)
    chosen = preferences(path)["local"]
    if chosen != "auto":
        return int(chosen)
    measured = (data.get("measured") or {}).get(model_id) or {}
    try:
        return int(measured["window"])
    except (KeyError, TypeError, ValueError):
        return DEFAULT_WINDOW


def cloud_cap(settings, *, path: Path | None = None) -> int | None:
    if getattr(settings, "cloud_context_length", None):
        return int(settings.cloud_context_length)
    chosen = preferences(path)["cloud"]
    return None if chosen == "full" else int(chosen)


def describe(settings, model_id: str, *, path: Path | None = None) -> dict[str, Any]:
    """What Settings shows: the effective windows and where each comes from."""
    data = _read(path)
    measured = (data.get("measured") or {}).get(model_id)
    if _explicit(settings, "ollama_context_length"):
        source = "environment"
    elif preferences(path)["local"] != "auto":
        source = "settings"
    else:
        source = "measured" if measured else "default"
    return {"model": model_id, "local_window": local_window(model_id, settings, path=path), "local_source": source,
            "measured": measured, "preferences": preferences(path),
            "cloud_cap": cloud_cap(settings, path=path),
            "cloud_source": "environment" if getattr(settings, "cloud_context_length", None) else "settings",
            "local_choices": list(CHOICES), "cloud_choices": list(CLOUD_CHOICES)}


# -- measurement ----------------------------------------------------------------
def measure(load: Callable[[int], dict[str, Any]], model_max: int) -> dict[str, Any]:
    """Pick the largest candidate window that keeps the whole model on the GPU.

    `load(num_ctx)` loads the model at that window and returns Ollama's `/api/ps`
    entry for it (`size`, `size_vram`, `context_length`).
    """
    tried = []
    for candidate in [value for value in CANDIDATES if value <= model_max] or [min(model_max, DEFAULT_WINDOW)]:
        entry = load(candidate)
        size, on_gpu = int(entry.get("size") or 0), int(entry.get("size_vram") or 0)
        tried.append({"window": candidate, "size": size, "size_vram": on_gpu})
        if size and on_gpu >= size:
            return {"window": candidate, "placement": "gpu", "tried": tried}
    if tried and all(item["size_vram"] == 0 for item in tried):
        return {"window": min(CPU_WINDOW, model_max), "placement": "cpu", "tried": tried}
    return {"window": min(DEFAULT_WINDOW, model_max), "placement": "partial", "tried": tried}


def ollama_loader(base_url: str, model: str, *, timeout: float = 300.0):
    import httpx
    root = base_url.rstrip("/").removesuffix("/v1")

    def load(num_ctx: int) -> dict[str, Any]:
        httpx.post(root + "/api/generate", timeout=timeout, json={
            "model": model, "prompt": "", "keep_alive": "5m", "options": {"num_ctx": num_ctx}}).raise_for_status()
        models = httpx.get(root + "/api/ps", timeout=30).json().get("models") or []
        return next((entry for entry in models if entry.get("name") == model or entry.get("model") == model), {})
    return load


def model_max_context(base_url: str, model: str) -> int:
    import httpx
    info = httpx.post(base_url.rstrip("/").removesuffix("/v1") + "/api/show", json={"model": model},
                      timeout=30).json().get("model_info") or {}
    values = [int(value) for key, value in info.items() if str(key).endswith(".context_length") and str(value).isdigit()]
    return max(values) if values else DEFAULT_WINDOW


def record(model_id: str, result: dict[str, Any], *, hardware: dict[str, Any] | None = None,
           path: Path | None = None) -> None:
    with _lock:
        data = _read(path)
        data.setdefault("measured", {})[model_id] = {
            **result, "hardware": hardware or {}, "measured_at": datetime.now(timezone.utc).isoformat()}
        _write(data, path)


def needs_measurement(model_id: str, settings, *, path: Path | None = None) -> bool:
    if not model_id.startswith("ollama/") or not getattr(settings, "context_auto_size", False):
        return False
    if _explicit(settings, "ollama_context_length") or preferences(path)["local"] != "auto":
        return False
    return model_id not in (_read(path).get("measured") or {})


def measure_now(model_id: str, settings) -> dict[str, Any] | None:
    """Measure one local model and record it (runs off the reply path)."""
    with _lock:
        if model_id in _attempted:
            return None
        _attempted.add(model_id)
    name = model_id.removeprefix("ollama/")
    try:
        result = measure(ollama_loader(settings.ollama_base_url, name),
                         model_max_context(settings.ollama_base_url, name))
        hardware = {}
        try:
            from agent.setup_hardware import scan
            scanned = scan()
            hardware = {"gpu": scanned.gpu_name, "vram_gb": scanned.vram_gb, "ram_gb": scanned.ram_gb}
        except Exception:  # noqa: BLE001 - hardware details are informational
            pass
        record(model_id, result, hardware=hardware)
        # Leave the model loaded at the chosen window so the next reply needs no reload.
        if result["tried"] and result["tried"][-1]["window"] != result["window"]:
            ollama_loader(settings.ollama_base_url, name)(result["window"])
        logger.info("Context window sized: model=%s window=%d placement=%s", model_id, result["window"], result["placement"])
        return result
    except Exception as exc:  # noqa: BLE001 - the default window stays in effect
        logger.warning("Context sizing skipped: model=%s error_type=%s", model_id, type(exc).__name__)
        return None
