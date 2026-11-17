"""The "About you" memory summary.

Modeled on ChatGPT's memory summary: a second-person profile in prose,
an Overview first, then one section per topic or project (titles chosen per
user), then two or three "Dive Deeper" prompts. It is generated on demand,
streamed, and cached by a checksum of its inputs so reopening is instant
until a memory changes.

Generation runs on the local model. When it is unavailable the summary is
built from the memories themselves, grouped by topic, so the page always
shows something true.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

SUMMARY_SCOPE = "about_you"

SUMMARY_SYSTEM = """You write the "About you" page of a personal assistant's memory.
Write to the user in second person ("You prefer...", "You're building...").
Use only the facts provided. Do not invent anything. When something is uncertain or
still changing, say so plainly (for example "you're still deciding whether...").
Include dislikes as well as likes. Keep it warm but plain; no flattery, no emoji.

Format exactly as Markdown:
## Overview
One paragraph: who the user is, what they're working toward, how they like to communicate.
## <Topic title>
One paragraph per major topic or project (2 to 6 sections). Choose short, specific titles
from the facts (for example a project's name), not generic labels.
## Dive Deeper
- 2 or 3 short questions the user might want to explore next, grounded in the facts.

Never mention items listed under "Do not mention"."""


def summary_inputs(orchestrator: Any) -> dict[str, Any]:
    from agent.memory.orchestrator import _durable_memories

    store = orchestrator.store
    memories = _durable_memories(store.list_saved())
    suppressed = [item for item in store.list_saved() + store.list_archived() if item.get("suppressed")]
    observations: list[str] = []
    provider = orchestrator.provider_extensions.get("hindsight") if orchestrator.provider_extensions else None
    if provider is not None and hasattr(provider, "recall_items"):
        try:
            observations = [item["text"] for item in provider.recall_items(
                "Who is the user: identity, preferences, projects, routines, opinions", limit=15)]
        except Exception:  # noqa: BLE001 - observations are optional
            observations = []
    return {"memories": memories, "suppressed": suppressed, "observations": observations}


def checksum(inputs: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for item in sorted(inputs["memories"], key=lambda m: m["id"]):
        digest.update(f"m{item['id']}:{item.get('updated_at')}:{item.get('feedback_score', 0)}|".encode())
    for item in sorted(inputs["suppressed"], key=lambda m: m["id"]):
        digest.update(f"s{item['id']}|".encode())
    for text in inputs["observations"]:
        digest.update(f"o{text}|".encode())
    return digest.hexdigest()[:24]


def load_cached(store: Any) -> dict[str, Any] | None:
    raw = store.summary(SUMMARY_SCOPE)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def current(orchestrator: Any) -> dict[str, Any]:
    """The cached summary plus whether it is stale. Never calls a model."""
    inputs = summary_inputs(orchestrator)
    cached = load_cached(orchestrator.store)
    fresh = checksum(inputs)
    if cached is None:
        return {"summary": None, "stale": True, "checksum": fresh, "memory_count": len(inputs["memories"])}
    return {"summary": cached, "stale": cached.get("checksum") != fresh, "checksum": fresh,
            "memory_count": len(inputs["memories"])}


def _prompt(inputs: dict[str, Any]) -> str:
    lines = ["Facts the user stated or Vellum learned (topic | origin | fact):"]
    for item in inputs["memories"][:120]:
        lines.append(f"- {item.get('topic') or 'General'} | {item.get('origin') or 'inferred'} | {item['text']}")
    if inputs["observations"]:
        lines.append("\nPatterns from long-term memory:")
        lines.extend(f"- {text}" for text in inputs["observations"][:15])
    if inputs["suppressed"]:
        lines.append("\nDo not mention:")
        lines.extend(f"- {item['text']}" for item in inputs["suppressed"][:40])
    return "\n".join(lines)


def parse_markdown(markdown: str) -> dict[str, Any]:
    sections: list[dict[str, str]] = []
    dive_deeper: list[str] = []
    current_title: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current_title is None:
            return
        body = "\n".join(buffer).strip()
        if current_title.casefold() == "dive deeper":
            dive_deeper.extend(
                re.sub(r"^[-*\d.)\s]+", "", line).strip() for line in body.splitlines() if line.strip()
            )
        elif body:
            sections.append({"title": current_title, "body": body})

    for line in markdown.splitlines():
        heading = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if heading:
            flush()
            current_title, buffer = heading.group(1).strip(), []
        else:
            buffer.append(line)
    flush()
    return {"sections": sections, "dive_deeper": [item for item in dive_deeper if item][:3]}


def fallback_summary(inputs: dict[str, Any]) -> dict[str, Any]:
    """A truthful summary without a model: the memories grouped by topic."""
    memories = inputs["memories"]
    if not memories:
        return {"sections": [{"title": "Overview", "body": "Vellum is just getting to know you. As you chat, "
                              "what you share and correct will show up here."}], "dive_deeper": []}
    groups: dict[str, list[str]] = {}
    for item in memories:
        groups.setdefault(item.get("topic") or "About you", []).append(str(item["text"]).rstrip("."))
    overview = (f"Vellum has {len(memories)} saved {'memory' if len(memories) == 1 else 'memories'} about you "
                f"across {len(groups)} {'topic' if len(groups) == 1 else 'topics'}.")
    sections = [{"title": "Overview", "body": overview}]
    for topic, texts in sorted(groups.items(), key=lambda pair: -len(pair[1]))[:6]:
        sections.append({"title": topic, "body": ". ".join(texts[:8]) + "."})
    return {"sections": sections, "dive_deeper": []}


def _store(orchestrator: Any, parsed: dict[str, Any], *, digest: str, generated_by: str,
           memory_count: int) -> dict[str, Any]:
    summary = {
        **parsed,
        "checksum": digest,
        "generated_by": generated_by,
        "memory_count": memory_count,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    orchestrator.store.update_summary(SUMMARY_SCOPE, json.dumps(summary, ensure_ascii=False))
    return summary


def generate(orchestrator: Any, *, force: bool = False) -> Iterator[tuple[str, Any]]:
    """Yield ("cached", summary) | ("generating", None) / ("delta", text)... / ("done", summary)."""
    from agent.memory.local_llm import LocalLLMError, stream

    inputs = summary_inputs(orchestrator)
    digest = checksum(inputs)
    cached = load_cached(orchestrator.store)
    if cached and cached.get("checksum") == digest and not force:
        yield "cached", cached
        return
    yield "generating", None
    if not inputs["memories"] and not inputs["observations"]:
        yield "done", _store(orchestrator, fallback_summary(inputs), digest=digest, generated_by="empty",
                             memory_count=0)
        return
    parts: list[str] = []
    try:
        for delta in stream(SUMMARY_SYSTEM, _prompt(inputs)):
            parts.append(delta)
            yield "delta", delta
    except LocalLLMError:
        parts = []
    parsed = parse_markdown("".join(parts)) if parts else {"sections": []}
    if not parsed["sections"]:
        yield "done", _store(orchestrator, fallback_summary(inputs), digest=digest, generated_by="fallback",
                             memory_count=len(inputs["memories"]))
        return
    yield "done", _store(orchestrator, parsed, digest=digest, generated_by="model",
                         memory_count=len(inputs["memories"]))
