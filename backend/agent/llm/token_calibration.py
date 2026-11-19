"""Per-model correction for Vellum's byte-based token estimate.

`estimate_tokens` divides UTF-8 bytes by three, which over-counts typical
Gemma prompts by about a third, so compaction starts on room that is actually
free. A local model is measured once with Ollama's real `prompt_eval_count`
(a random prefix defeats the prompt cache), and the ratio of real to estimated
tokens, plus a 10% safety margin, scales later estimates for that model.
Prose and structured text (JSON tool schemas and results) tokenize very
differently, so each gets its own ratio.

Until a model is measured the ratio is 1.0, today's conservative behaviour.
Only counts are stored; calibration text is Vellum's own runtime documents.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
SAFETY = 1.10
BOUNDS = (0.5, 1.5)
_lock = threading.Lock()
_attempted: set[str] = set()

# Tool schemas are dense JSON; prose and JSON tokenize differently, so both
# are measured and the larger ratio wins.
_JSON_SAMPLE = json.dumps([{"type": "function", "function": {
    "name": f"connector_tool_{index}", "description": "Read records from the connected workspace with paging.",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "Search terms"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "cursor": {"type": ["string", "null"]},
        "filters": {"type": "object", "properties": {"status": {"enum": ["open", "closed", "all"]},
                                                     "updated_after": {"type": "string", "format": "date-time"}}}},
        "required": ["query"]}}} for index in range(12)])


def calibration_path() -> Path:
    from agent.config import REPO_ROOT
    return Path(REPO_ROOT) / "data" / "llm-routing" / "token-calibration.json"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _bounded(value) -> float:
    return min(max(float(value), BOUNDS[0]), BOUNDS[1])


def token_ratios(model_id: str, *, path: Path | None = None) -> tuple[float, float]:
    """(prose, structured) real-per-estimated ratios; (1.0, 1.0) when unmeasured."""
    record = _read(path or calibration_path()).get(model_id)
    try:
        return _bounded(record["prose"]), _bounded(record["structured"])
    except (TypeError, KeyError, ValueError):
        return 1.0, 1.0


def _corpus() -> dict[str, str]:
    from agent.config import SOURCE_ROOT
    prose = "\n\n".join((Path(SOURCE_ROOT) / "docs" / name).read_text(encoding="utf-8")[:20000]
                        for name in ("main.md", "SOUL.md", "PERSONALITY.md")
                        if (Path(SOURCE_ROOT) / "docs" / name).exists())
    return {"prose": prose, "structured": _JSON_SAMPLE}


def measure(model_id: str, count_tokens, *, texts: dict[str, str] | None = None) -> dict[str, float]:
    """Return safety-adjusted {"prose", "structured"} ratios for `model_id`.

    `count_tokens(text)` must return the model's real prompt token count for a
    single user message containing `text` (including fixed chat overhead).
    """
    from agent.llm.context import estimate_tokens
    overhead = count_tokens("x")
    ratios = {}
    for kind, text in (texts or _corpus()).items():
        estimated = estimate_tokens(text)
        if estimated < 200:
            raise ValueError("Calibration text is too short to measure.")
        ratios[kind] = _bounded(max(0, count_tokens(text) - overhead) / estimated * SAFETY)
    return ratios


def save(model_id: str, ratios: dict[str, float], *, path: Path | None = None) -> None:
    path = path or calibration_path()
    with _lock:
        data = _read(path)
        data[model_id] = {**{kind: round(value, 4) for kind, value in ratios.items()}, "safety": SAFETY,
                          "estimator": "utf8_bytes_div3", "measured_at": datetime.now(timezone.utc).isoformat()}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)


def ollama_counter(base_url: str, model: str, *, num_ctx: int = 32768, timeout: float = 300):
    """Same num_ctx as chat, so measuring never forces a model reload."""
    import httpx

    def count(text: str) -> int:
        response = httpx.post(base_url.rstrip("/").removesuffix("/v1") + "/api/chat", timeout=timeout, json={
            "model": model, "stream": False, "keep_alive": "5m",
            "messages": [{"role": "user", "content": secrets.token_hex(6) + "\n" + text}],
            "options": {"num_predict": 1, "num_ctx": num_ctx}})
        response.raise_for_status()
        return int(response.json()["prompt_eval_count"])
    return count


def ensure_calibrated(model_id: str, settings) -> None:
    """Measure an uncalibrated local model once per process, in the background."""
    if not model_id.startswith("ollama/") or not getattr(settings, "context_token_calibration", False):
        return
    with _lock:
        if model_id in _attempted or "structured" in (_read(calibration_path()).get(model_id) or {}):
            return
        _attempted.add(model_id)

    def run():
        from agent.llm.context import local_num_ctx
        try:
            ratios = measure(model_id, ollama_counter(settings.ollama_base_url, model_id.removeprefix("ollama/"),
                                                      num_ctx=local_num_ctx(settings)))
            save(model_id, ratios)
            logger.info("Token estimate calibrated: model=%s prose=%.3f structured=%.3f",
                        model_id, ratios["prose"], ratios["structured"])
        except Exception as exc:  # the conservative default stays in effect
            logger.warning("Token calibration skipped: model=%s error_type=%s", model_id, type(exc).__name__)

    threading.Thread(target=run, name="vellum-token-calibration", daemon=True).start()
