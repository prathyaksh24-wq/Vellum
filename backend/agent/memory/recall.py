"""Pick the few memories that matter for one request.

Same shape as Claude Code's recall: a small model sees only each memory's
id, title and description, and names at most ``limit`` that will clearly
help. Bodies are not read at selection time, which keeps it cheap. If the
model is slow, missing or returns nonsense, selection falls back to keyword
overlap, so recall never blocks a chat.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from typing import Any

SELECTOR_SYSTEM = (
    "You are selecting memories that will be useful to Vellum, a personal assistant, as it answers "
    "the user's request. Below is a list of the user's saved memories as `id: title - description`. "
    "Return JSON {\"ids\": [...]} with the ids of memories that will clearly help answer the request "
    "(at most {limit}). Only include memories you are certain are relevant from their title and "
    "description. Return {\"ids\": []} when none are.\n\nMemories:\n{manifest}"
)

_CACHE_TTL_SECONDS = 600.0
_cache: dict[str, tuple[float, list[int], str]] = {}
_cache_lock = threading.Lock()


def manifest_line(memory: dict[str, Any]) -> str:
    title = str(memory.get("title") or "").strip() or str(memory.get("text") or "")[:60]
    description = re.sub(r"\s+", " ", str(memory.get("description") or memory.get("text") or "")).strip()
    return f"{int(memory['id'])}: {title} - {description[:140]}"


def _fingerprint(query: str, memories: list[dict[str, Any]], limit: int) -> str:
    digest = hashlib.sha256()
    digest.update(f"{limit}|{query.strip().casefold()}".encode())
    for memory in memories:
        digest.update(f"|{memory['id']}:{memory.get('updated_at')}".encode())
    return digest.hexdigest()


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", str(text).casefold()) if len(term) > 2}


def keyword_rank(query: str, memories: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    terms = _terms(query)
    if not terms:
        return []
    scored = []
    for memory in memories:
        haystack = _terms(f"{memory.get('title')} {memory.get('description')} {memory.get('text')}")
        overlap = len(terms & haystack)
        if overlap:
            score = overlap + 0.25 * int(memory.get("feedback_score") or 0) + 0.05 * min(int(memory.get("use_count") or 0), 20)
            scored.append((score, memory))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [memory for _score, memory in scored[:limit]]


def select_relevant_memories(
    query: str,
    memories: list[dict[str, Any]],
    *,
    limit: int = 5,
    selector: Any | None = None,
    timeout: float | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return (memories, method) where method is model, all, keyword, or cached-*."""
    pool = [memory for memory in memories if not memory.get("suppressed") and int(memory.get("feedback_score") or 0) > -3]
    if not pool or not query.strip():
        return [], "none"
    if len(pool) <= limit:
        return pool, "all"
    key = _fingerprint(query, pool, limit)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            by_id = {int(memory["id"]): memory for memory in pool}
            return [by_id[i] for i in cached[1] if i in by_id], f"cached-{cached[2]}"
    chosen, method = _model_select(query, pool, limit=limit, selector=selector, timeout=timeout)
    if chosen is None:
        chosen, method = keyword_rank(query, pool, limit=limit), "keyword"
    with _cache_lock:
        _cache[key] = (now, [int(memory["id"]) for memory in chosen], method)
        if len(_cache) > 256:
            for stale in sorted(_cache, key=lambda k: _cache[k][0])[:64]:
                _cache.pop(stale, None)
    return chosen, method


def _model_select(query, pool, *, limit, selector, timeout):
    manifest = "\n".join(manifest_line(memory) for memory in pool[:200])
    system = SELECTOR_SYSTEM.replace("{limit}", str(limit)).replace("{manifest}", manifest)
    try:
        if selector is not None:
            result = selector(system, query)
        else:
            from agent.config import get_settings
            from agent.memory.local_llm import complete_json

            result = complete_json(system, query, timeout=timeout or get_settings().memory_recall_timeout_seconds,
                                   max_tokens=120)
    except Exception:  # noqa: BLE001 - fail open to keyword recall
        return None, "keyword"
    raw_ids = result.get("ids") if isinstance(result, dict) else result
    if not isinstance(raw_ids, list):
        return None, "keyword"
    by_id = {int(memory["id"]): memory for memory in pool}
    chosen: list[dict[str, Any]] = []
    for raw in raw_ids:
        try:
            memory = by_id.get(int(raw))
        except (TypeError, ValueError):
            continue
        if memory is not None and memory not in chosen:
            chosen.append(memory)
        if len(chosen) >= limit:
            break
    return chosen, "model"


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
