"""Bring memories in from another assistant, and take them out as Markdown.

Import is plan-then-apply: the paste is parsed into single-fact lines,
filtered, and shown to the user; nothing is written until they confirm.
The paste is data, never instructions. Rules follow Claude's importer:
additive only, sensitive categories dropped, links dropped, 64 KB cap.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

MAX_IMPORT_BYTES = 64 * 1024

EXPORT_PROMPT = """List everything you have stored or learned about me from our past conversations, so I can move it to another assistant. Keep my own wording where you can, especially for instructions and preferences.

Use these five sections, in this order:

1. Instructions: rules I asked you to follow going forward (tone, format, things to always or never do, corrections).
2. Identity: name, location, education, languages, interests.
3. Career: current and past roles, companies, skill areas.
4. Projects: things I'm building or committed to, one entry per project, with what it is, its status and key decisions. Start each entry with the project's name.
5. Preferences: opinions, tastes and working-style preferences that apply broadly.

Under each section header, write one entry per line, oldest first, as:
[YYYY-MM-DD] - entry
Use [unknown] when you don't know the date.

Put the whole list in one code block, then say whether it is complete or more remains."""

_CATEGORY_KIND = {
    "instructions": "preference",
    "identity": "fact",
    "career": "fact",
    "projects": "project",
    "preferences": "preference",
}

# Never imported, whatever the wording (mirrors Claude's import filter).
_SENSITIVE = re.compile(
    r"\b(?:diagnos\w*|disorder|depress\w*|anxiety|adhd|autis\w*|therap\w*|medication|illness|disease|"
    r"pregnan\w*|addict\w*|rehab|sobriety|religio\w*|church|mosque|temple|faith|political|liberal|conservative|"
    r"democrat|republican|sexual\w*|gay|lesbian|bisexual|transgender|immigra\w*|visa status|citizenship|"
    r"criminal|arrest\w*|convict\w*|salary|income|net worth|debt|bank account|passport|ssn|social security|"
    r"aadhaar|pan card|home address|phone number|mbti|enneagram|attachment style|my (?:son|daughter|kids?|children))\b",
    re.IGNORECASE,
)
_DIRECTIVE = re.compile(
    r"\b(?:ignore (?:all |any )?(?:previous|prior) instructions|system prompt|you are now|act as|"
    r"when importing|always agree|never disagree|do not question|stay in character|persona)\b",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_LINE = re.compile(r"^\s*(?:[-*]\s*)?\[(?P<date>\d{4}-\d{2}-\d{2}|unknown)\]\s*[-:]\s*(?P<text>.+?)\s*$", re.IGNORECASE)


def plan_import(text: str, existing_texts: list[str], *, include_sensitive: bool = False) -> dict[str, Any]:
    from agent.memory.orchestrator import _memory_topic, _sentence
    from agent.privacy.classifier import DataClass, classify

    raw = text.encode("utf-8")
    truncated = len(raw) > MAX_IMPORT_BYTES
    if truncated:
        text = raw[:MAX_IMPORT_BYTES].decode("utf-8", errors="ignore")
        text = text[: text.rfind("\n")] if "\n" in text else ""
    existing = {_norm(item) for item in existing_texts}
    category = ""
    items: list[dict[str, Any]] = []
    dropped = {"sensitive": 0, "instruction_like": 0, "links_removed": 0, "duplicate": 0, "unparsed": 0}
    seen: set[str] = set()
    for line in text.splitlines():
        if line.strip().startswith("```"):
            category = ""  # a code fence opens or closes the export; notes outside it are not entries
            continue
        header = re.match(r"^\s*(?:#+\s*|\d+\.\s*|\*\*)?\s*(Instructions|Identity|Career|Projects|Preferences)\b",
                          line, re.IGNORECASE)
        if header and not _LINE.match(line):
            category = header.group(1).casefold()
            continue
        match = _LINE.match(line)
        if not match:
            if line.strip() and category:
                dropped["unparsed"] += 1
            continue
        entry = match.group("text").strip()
        if _DIRECTIVE.search(entry):
            dropped["instruction_like"] += 1
            continue
        if _URL.search(entry):
            entry = _URL.sub("", entry).strip(" -,;:")
            dropped["links_removed"] += 1
        if not entry or len(entry) < 6:
            continue
        if not include_sensitive and (_SENSITIVE.search(entry) or classify(entry)[0] == DataClass.RED):
            dropped["sensitive"] += 1
            continue
        key = _norm(entry)
        if key in existing or key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        kind = _CATEGORY_KIND.get(category, "fact")
        sentence = _sentence(entry)
        date = match.group("date").lower()
        items.append({
            "kind": kind,
            "text": sentence,
            "topic": _memory_topic(kind, sentence),
            "category": category or "uncategorized",
            "date": None if date == "unknown" else date,
        })
    return {"items": items, "dropped": dropped, "truncated": truncated, "count": len(items)}


def export_zip(memories: list[dict[str, Any]]) -> bytes:
    """One Markdown file per topic plus an index, like Claude's memory export."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in memories:
        groups.setdefault(item.get("topic") or "About you", []).append(item)
    buffer = io.BytesIO()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        index = [f"# Vellum memory export ({stamp})", "", f"{len(memories)} memories in {len(groups)} topics.", ""]
        for topic, items in sorted(groups.items()):
            slug = re.sub(r"[^a-z0-9]+", "-", topic.casefold()).strip("-") or "topic"
            lines = [f"# {topic}", ""]
            for item in items:
                saved = str(item.get("created_at") or "")[:10]
                lines.append(f"- [{item.get('origin') or 'inferred'}] {item['text']}" + (f" ({saved})" if saved else ""))
            archive.writestr(f"topics/{slug}.md", "\n".join(lines) + "\n")
            index.append(f"- [{topic}](topics/{slug}.md) - {len(items)}")
        archive.writestr("MEMORY.md", "\n".join(index) + "\n")
    return buffer.getvalue()


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))
