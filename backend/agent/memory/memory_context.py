"""Hermes-style memory context assembled into the system prompt each turn.

Two pieces, mirroring how Hermes makes an agent "know the user" and grow:

1. SOUL.md  — the personality / identity file (docs/SOUL.md), injected once
   (cached) so tone and self-model are stable.
2. User model — Honcho's dialectic synthesis of who the user is. The dialectic
   is an LLM call on Honcho's side, so we run it on a *cadence* in the
   background (`refresh_user_model`, called after a turn is stored) and cache
   the result per thread. The prompt path only reads the cache — no network
   call in the hot path, so prefix-cache stability and latency are preserved.

Over days this user model deepens (Honcho accumulates observations), so the
injected block gets richer and the agent responds with growing understanding.
Explicit "what did we discuss" recall stays the `search_my_notes` tool
(vector RAG over the vault + past Q&A via ChromaDB).
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

# ── SOUL.md (personality) ─────────────────────────────────────────────
_SOUL_CACHE: str | None = None
_SOUL_LOCK = threading.Lock()
_MAX_SOUL_CHARS = 12_000  # ~4k tokens; head-heavy truncation like Hermes

# ── user model (Honcho dialectic), cached per thread ──────────────────
_USER_MODEL: dict[str, str] = {}
_TURN_COUNT: dict[str, int] = {}
_MODEL_LOCK = threading.Lock()
_DIALECTIC_CADENCE = 2  # refresh every N stored turns (Hermes default)

_DIALECTIC_QUERY = (
    "In 4-8 short bullet points, summarise what you currently know about this user "
    "that would help respond to them better right now: who they are, their preferences, "
    "communication style, recurring goals or projects, and any standing context. "
    "Only include things you are reasonably confident about. If you know little yet, "
    "say so in one line."
)


def load_soul() -> str:
    """Read docs/SOUL.md once (cached), head-heavy truncation if oversized."""
    global _SOUL_CACHE
    if _SOUL_CACHE is not None:
        return _SOUL_CACHE
    with _SOUL_LOCK:
        if _SOUL_CACHE is None:
            text = ""
            try:
                from agent.config import REPO_ROOT

                path = REPO_ROOT / "docs" / "SOUL.md"
                if path.exists():
                    text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:  # pragma: no cover - filesystem edge
                logger.warning("[MEMORY] SOUL.md load failed: %s", exc)
            if len(text) > _MAX_SOUL_CHARS:
                head = int(_MAX_SOUL_CHARS * 0.7)
                tail = int(_MAX_SOUL_CHARS * 0.2)
                text = f"{text[:head]}\n\n…\n\n{text[-tail:]}"
            _SOUL_CACHE = text.strip()
    return _SOUL_CACHE


def get_user_model(thread_id: str) -> str:
    with _MODEL_LOCK:
        return _USER_MODEL.get(thread_id, "")


def set_user_model(thread_id: str, text: str) -> None:
    with _MODEL_LOCK:
        _USER_MODEL[thread_id] = (text or "").strip()


def refresh_user_model(thread_id: str, honcho) -> None:
    """Run Honcho's dialectic on a cadence and cache the synthesis for next turn.

    Safe to call after every stored turn — it self-throttles to every
    _DIALECTIC_CADENCE turns (but always fires on the first turn of a thread).
    Honcho errors are swallowed by the client and here, so this never blocks a
    turn from completing.
    """
    with _MODEL_LOCK:
        count = _TURN_COUNT.get(thread_id, 0) + 1
        _TURN_COUNT[thread_id] = count
    if count != 1 and (count % _DIALECTIC_CADENCE) != 0:
        return
    try:
        synthesis = honcho.chat(session_id=thread_id, query=_DIALECTIC_QUERY)
        if synthesis and synthesis.strip():
            set_user_model(thread_id, synthesis.strip())
    except Exception as exc:  # pragma: no cover - network edge
        logger.warning("[MEMORY] user-model refresh failed: %s", exc)


def build_memory_block(thread_id: str) -> str:
    """System-prompt block: SOUL personality + the evolving user model.

    Returns "" when nothing is available (e.g. day one, no SOUL.md), so the
    base prompt is unchanged for new users.
    """
    parts: list[str] = []
    soul = load_soul()
    if soul:
        parts.append("# Who you are (SOUL)\n" + soul)
    user_model = get_user_model(thread_id)
    if user_model:
        parts.append(
            "# What you know about this user\n"
            "Your evolving model of the user, built from past conversations. Let it shape "
            "how you respond — their tone, depth, and what they care about. Do not recite it "
            "back unless they ask what you remember.\n\n" + user_model
        )
    return "\n\n".join(parts).strip()
