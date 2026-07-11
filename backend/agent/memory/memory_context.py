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
from pathlib import Path
from typing import Any

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
_ORCHESTRATOR: Any | None = None
_MEMORY_FILES_DIR = Path("data/memory")
_MAX_MEMORY_FILE_CHARS = 3600

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


def _default_orchestrator():
    if _ORCHESTRATOR is not None:
        return _ORCHESTRATOR
    from agent.memory.runtime import get_memory_orchestrator

    return get_memory_orchestrator()


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


def build_memory_block(thread_id: str, *, query: str = "", active_project: str | None = None, cloud_safe: bool = True) -> str:
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
    context_files = load_memory_files()
    if context_files:
        parts.append(context_files)
    try:
        packet = _default_orchestrator().build_memory_packet(
            thread_id=thread_id,
            query=query,
            agent_name="VellumAgent",
            active_project=active_project,
            cloud_safe=cloud_safe,
        )
        packet_block = _format_memory_packet(packet)
        if packet_block:
            parts.append(packet_block)
    except Exception as exc:  # pragma: no cover - storage edge
        logger.warning("[MEMORY] memory packet build failed: %s", exc)
    return "\n\n".join(parts).strip()


def load_memory_files(memory_dir: Path | None = None) -> str:
    """Load bounded USER.md/MEMORY.md snapshots generated by the orchestrator."""
    root = Path(memory_dir or _MEMORY_FILES_DIR)
    chunks: list[str] = []
    for filename, title in (("USER.md", "USER.md"), ("MEMORY.md", "MEMORY.md")):
        path = root / filename
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if text:
            chunks.append(f"## {title}\n{text}")
    if not chunks:
        return ""
    block = (
        "# Hermes-style persistent memory\n"
        "This is a bounded snapshot generated by Vellum Memory Orchestrator. Use it quietly; "
        "prefer the current conversation if there is conflict.\n\n"
        + "\n\n".join(chunks)
    )
    return block[:_MAX_MEMORY_FILE_CHARS].rstrip()


def _format_memory_packet(packet: dict[str, Any]) -> str:
    sections: list[str] = []
    global_summary = str(packet.get("global_summary") or "").strip()
    if global_summary:
        sections.append("## Global user summary\n" + global_summary)
    saved = packet.get("saved_memories") or []
    if saved:
        lines = []
        for item in saved[:8]:
            text = str(item.get("text") if isinstance(item, dict) else item).strip()
            if text:
                lines.append("- " + text)
        if lines:
            sections.append("## Saved memories\n" + "\n".join(lines))
    honcho_context = str(packet.get("honcho_context") or "").strip()
    if honcho_context:
        sections.append("## Honcho context\n" + honcho_context)
    project_context = str(packet.get("project_context") or "").strip()
    if project_context:
        sections.append("## Active project context\n" + project_context)
    recent_context = str(packet.get("recent_context") or "").strip()
    if recent_context:
        sections.append("## Recent conversation context\n" + recent_context)
    external_context = str(packet.get("external_context") or "").strip()
    if external_context:
        sections.append("## External memory provider context\n" + external_context)
    knowledge_refs = packet.get("knowledge_refs") or []
    if knowledge_refs:
        lines = []
        for item in knowledge_refs[:4]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "Untitled")
            ref = str(item.get("ref") or "")
            description = str(item.get("description") or "").strip()
            suffix = f" - {description}" if description else ""
            lines.append(f"- {title} ({ref}){suffix}")
        if lines:
            sections.append(
                "## Relevant Knowledge wiki references\n"
                "These are routing references, not copied memory. Use the knowledge_wiki tool to read a page only when needed.\n"
                + "\n".join(lines)
            )
    if not sections:
        return ""
    return (
        "# Memory packet\n"
        "Use this quietly to personalize the answer. Prefer the current conversation when it conflicts "
        "with older memory. Do not mention memory unless it is useful or the user asks.\n\n"
        + "\n\n".join(sections)
    )
