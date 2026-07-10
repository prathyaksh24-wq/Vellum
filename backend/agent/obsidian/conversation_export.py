"""Render the UI conversation store as a private, readable Obsidian projection.

``data/ui/conversations.json`` is the canonical store.  This module deliberately
does not modify it; it only gives the store a stable Markdown representation in
``Agent/Conversations``.  The projection is keyed by ``conversation_id`` and
``thread_id`` in frontmatter so a title or date change can safely rename a note
instead of creating a second copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CONVERSATIONS_ROOT = Path("Agent") / "Conversations"
SOURCE_LABEL = "data/ui/conversations.json"
PROJECTION_TYPE = "conversation"
UNKNOWN_DATE = date(1970, 1, 1)


@dataclass(frozen=True)
class ExistingNote:
    path: Path
    metadata: dict[str, str]


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the scalar frontmatter needed for identity and retention guards.

    A full YAML dependency would be excessive here.  Exported values are JSON
    quoted scalars, and this parser also accepts the simple unquoted form used
    by hand-written Obsidian notes.
    """

    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() in {"---", "..."}:
            break
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            if value[0] == '"':
                try:
                    value = str(json.loads(value))
                except (TypeError, ValueError):
                    value = value[1:-1]
            else:
                value = value[1:-1].replace("''", "'")
        metadata[key] = value
    return metadata


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _message_text(message: Any) -> str:
    if not isinstance(message, Mapping):
        return ""
    return _as_text(message.get("text") or message.get("content") or message.get("message"))


def _message_role(message: Any) -> str:
    if not isinstance(message, Mapping):
        return "Message"
    role = _as_text(message.get("role") or "message").casefold()
    return {
        "user": "User",
        "assistant": "Assistant",
        "system": "System",
        "tool": "Tool",
    }.get(role, role.title() or "Message")


def _messages(conversation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    messages = conversation.get("messages")
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        return []
    return [message for message in messages if isinstance(message, Mapping) and _message_text(message)]


def _first_user_text(conversation: Mapping[str, Any]) -> str:
    for message in _messages(conversation):
        if _message_role(message) == "User":
            return _message_text(message)
    return ""


def conversation_identity(conversation: Mapping[str, Any]) -> tuple[str, str]:
    """Return stable conversation and thread identifiers for a UI record."""

    raw_id = _as_text(
        conversation.get("conversation_id")
        or conversation.get("id")
        or conversation.get("thread_id")
    )
    raw_thread = _as_text(conversation.get("thread_id") or raw_id)
    if not raw_id:
        # A malformed record still gets a deterministic identity, never a
        # timestamp.  The canonical JSON serialization makes it stable across
        # migration reruns.
        canonical = json.dumps(conversation, sort_keys=True, ensure_ascii=False, default=str)
        raw_id = "conversation-" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]
    if not raw_thread:
        raw_thread = raw_id
    return raw_id, raw_thread


def clean_title(value: Any, *, conversation: Mapping[str, Any] | None = None) -> str:
    """Return a readable title suitable for a heading and a filename stem."""

    title = _as_text(value)
    placeholder = not title or title.casefold() in {
        "new chat",
        "untitled",
        "untitled chat",
        "conversation",
    }
    if placeholder and conversation is not None:
        title = _first_user_text(conversation)
    title = re.sub(r"[\x00-\x1f\x7f]", " ", title)
    title = re.sub(r"^\s*[#>*-]+\s*", "", title)
    # Old QA exports commonly put a timestamp in the title.  Remove that
    # suffix/prefix so new notes cannot recreate timestamp-generated names.
    title = re.sub(
        r"(?i)\b(?:qa|query|response|conversation|chat)?[ _-]*\d{8}(?:[ _-]*\d{6}(?:[ _-]*\d{1,6})?)?\b",
        " ",
        title,
    )
    title = re.sub(r"\s+", " ", title).strip(" .-_/")
    if not title:
        if conversation is not None:
            title = re.sub(r"\s+", " ", _first_user_text(conversation)).strip(" .-_/")
        if not title:
            conversation_id, _thread_id = conversation_identity(conversation or {})
            if re.search(r"\d{8}(?:[_-]\d{6})?", conversation_id):
                token = hashlib.sha1(conversation_id.encode("utf-8")).hexdigest()[:12]
                title = f"Conversation {token}"
            else:
                title = f"Conversation {conversation_id}"
    return title[:160].rstrip()


def slugify_title(title: str, *, fallback: str = "conversation") -> str:
    """Build a deterministic, human-readable Markdown filename stem."""

    normalized = unicodedata.normalize("NFKD", title or "")
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_title = ascii_title.replace("&", " and ")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title.casefold()).strip("-")
    slug = slug[:120].rstrip("-")
    return slug or fallback


# Short aliases are useful to callers and keep the filename policy explicit.
slugify = slugify_title


def _parse_date(value: Any) -> date | None:
    text = _as_text(value)
    if not text:
        return None
    if text.casefold() in {"today", "yesterday", "tomorrow"}:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def conversation_date(conversation: Mapping[str, Any]) -> date:
    """Choose a stable YYYY/MM bucket without using the current clock.

    UI records normally have ``updated_at``.  The epoch fallback is intentional:
    malformed or legacy records must not move folders every time a migration is
    run merely because the day changed.
    """

    candidates: list[Any] = [
        conversation.get("updated_at"),
        conversation.get("updatedAt"),
        conversation.get("created_at"),
        conversation.get("createdAt"),
        conversation.get("created"),
        conversation.get("date"),
    ]
    for message in _messages(conversation):
        candidates.extend(message.get(key) for key in ("created_at", "createdAt", "timestamp", "at", "date"))
    for candidate in candidates:
        parsed = _parse_date(candidate)
        if parsed is not None:
            return parsed
    return UNKNOWN_DATE


def _identity_token(conversation_id: str) -> str:
    token = slugify_title(conversation_id, fallback="conversation")
    return token[:48] or hashlib.sha1(conversation_id.encode("utf-8")).hexdigest()[:12]


def _relative(path: Path, vault_root: Path) -> str:
    return path.relative_to(vault_root).as_posix()


def _safe_vault_path(vault_root: Path, relative_path: str | Path) -> Path:
    root = vault_root.expanduser().resolve()
    target = (root / Path(relative_path)).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Conversation export path escapes the Obsidian vault.")
    return target


def _read_existing_notes(vault_root: Path) -> list[ExistingNote]:
    root = _safe_vault_path(vault_root, CONVERSATIONS_ROOT)
    if not root.exists():
        return []
    notes: list[ExistingNote] = []
    for path in sorted(root.rglob("*.md")):
        try:
            metadata = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if metadata.get("conversation_id") or metadata.get("thread_id"):
            notes.append(ExistingNote(path=path, metadata=metadata))
    return notes


def _value_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip(" -*\t") for line in value.splitlines() if line.strip(" -*\t")]
    if isinstance(value, Mapping):
        for key in ("text", "value", "title", "name", "path", "link"):
            if _as_text(value.get(key)):
                return [_as_text(value[key])]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items: list[str] = []
        for item in value:
            items.extend(_value_items(item))
        return items
    return [_as_text(value)] if _as_text(value) else []


def _field_items(conversation: Mapping[str, Any], names: Iterable[str]) -> list[str]:
    values: list[str] = []
    for name in names:
        if name in conversation:
            values.extend(_value_items(conversation.get(name)))
    seen: set[str] = set()
    return [value for value in values if value and not (value in seen or seen.add(value))]


def _memory_links(conversation: Mapping[str, Any]) -> list[str]:
    values = _field_items(
        conversation,
        ("memory_links", "memoryLinks", "memory", "memories", "memory_paths"),
    )
    links: list[str] = []
    seen: set[str] = set()
    for value in values:
        found = re.findall(r"!?\[\[[^\]]+\]\]", value)
        candidates = found or [value]
        for candidate in candidates:
            candidate = candidate.strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                links.append(candidate)
    return links


def _excerpt(text: str, limit: int = 360) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _summary(conversation: Mapping[str, Any]) -> str:
    explicit = _field_items(conversation, ("summary", "summary_text", "description", "abstract"))
    if explicit:
        return "\n".join(explicit)
    turns = _messages(conversation)
    user = next((_message_text(message) for message in turns if _message_role(message) == "User"), "")
    assistant = next((_message_text(message) for message in turns if _message_role(message) == "Assistant"), "")
    if user and assistant:
        return f"The conversation began with: {_excerpt(user)}\n\nThe assistant responded with: {_excerpt(assistant)}"
    if user:
        return f"The conversation began with: {_excerpt(user)}"
    if assistant:
        return f"The assistant discussed: {_excerpt(assistant)}"
    return "No readable messages were recorded."


def _section_items(conversation: Mapping[str, Any], names: Iterable[str], empty: str) -> list[str]:
    items = _field_items(conversation, names)
    return items or [empty]


def _preserved_guards(existing: ExistingNote | None) -> dict[str, Any]:
    if existing is None:
        return {}
    metadata = existing.metadata
    guards: dict[str, Any] = {}
    if metadata.get("pinned", "").casefold() in {"true", "yes", "1"}:
        guards["pinned"] = True
    if metadata.get("retention", "").casefold() in {"keep", "never", "permanent"}:
        guards["retention"] = "keep"
    return guards


def render_conversation(conversation: Mapping[str, Any], *, existing: ExistingNote | None = None) -> str:
    """Render one conversation with deterministic frontmatter and headings."""

    conversation_id, thread_id = conversation_identity(conversation)
    title = clean_title(conversation.get("title"), conversation=conversation)
    bucket = conversation_date(conversation)
    guards = _preserved_guards(existing)
    frontmatter: list[tuple[str, Any]] = [
        ("type", PROJECTION_TYPE),
        ("privacy", "private"),
        ("source", SOURCE_LABEL),
        ("conversation_id", conversation_id),
        ("thread_id", thread_id),
        ("title", title),
        ("conversation_date", bucket.isoformat()),
        ("created", _as_text(conversation.get("created")) or bucket.isoformat()),
        ("updated_at", _as_text(conversation.get("updated_at")) or bucket.isoformat()),
        ("pinned", bool(conversation.get("pinned", False))),
        ("archived", bool(conversation.get("archived", False))),
    ]
    known = {key for key, _value in frontmatter}
    for key, value in guards.items():
        frontmatter = [(key, value) if existing_key == key else (existing_key, old_value) for existing_key, old_value in frontmatter]
        if key not in known:
            frontmatter.append((key, value))

    lines = ["---"]
    for key, value in frontmatter:
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = json.dumps(str(value), ensure_ascii=False)
        lines.append(f"{key}: {rendered}")
    lines.extend(
        [
            "---",
            "",
            f"# {title}",
            "",
            "## Summary",
            "",
            _summary(conversation),
            "",
            "## Conversation / Transcript",
            "",
        ]
    )
    messages = _messages(conversation)
    if messages:
        for message in messages:
            lines.extend([f"### {_message_role(message)}", "", _message_text(message), ""])
    else:
        lines.extend(["_No readable messages were recorded._", ""])

    lines.extend(["## Decisions", ""])
    for item in _section_items(conversation, ("decisions", "decision", "resolved_decisions", "commitments"), "No explicit decisions recorded."):
        lines.extend([f"- {item}", ""])
    lines.extend(["## Open Loops", ""])
    for item in _section_items(conversation, ("open_loops", "openLoops", "follow_ups", "followUps", "open_questions"), "No open loops recorded."):
        lines.extend([f"- {item}", ""])
    links = _memory_links(conversation)
    if links:
        lines.extend(["## Memory Links", ""])
        for link in links:
            lines.extend([f"- {link}", ""])
    return "\n".join(lines).rstrip() + "\n"


def _candidate_paths(
    conversation: Mapping[str, Any],
    *,
    vault_root: Path,
    used: set[Path],
) -> Path:
    conversation_id, _thread_id = conversation_identity(conversation)
    bucket = conversation_date(conversation)
    title = clean_title(conversation.get("title"), conversation=conversation)
    base = CONVERSATIONS_ROOT / f"{bucket:%Y}" / f"{bucket:%m}" / f"{slugify_title(title)}.md"
    candidate = _safe_vault_path(vault_root, base)
    if candidate not in used and not candidate.exists():
        return candidate
    # The identity suffix is stable and is only needed for collisions.  It is
    # deliberately not a timestamp.
    suffix = _identity_token(conversation_id)
    candidate = _safe_vault_path(vault_root, base.with_name(f"{base.stem}--{suffix}.md"))
    counter = 2
    while candidate in used or candidate.exists():
        candidate = _safe_vault_path(vault_root, base.with_name(f"{base.stem}--{suffix}-{counter}.md"))
        counter += 1
    return candidate


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _same_identity(note: ExistingNote, conversation_id: str, thread_id: str) -> bool:
    return (
        note.metadata.get("conversation_id") == conversation_id
        or note.metadata.get("thread_id") == thread_id
    )


def export_conversations(
    conversations: Iterable[Mapping[str, Any]],
    *,
    vault_root: str | Path,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Export records and return a JSON-serializable migration manifest."""

    vault = Path(vault_root).expanduser().resolve()
    records = [record for record in conversations if isinstance(record, Mapping)]
    existing = _read_existing_notes(vault)
    by_identity: dict[str, ExistingNote] = {}
    for note in existing:
        identity = note.metadata.get("conversation_id") or note.metadata.get("thread_id")
        if identity and identity not in by_identity:
            by_identity[identity] = note

    # Sort only for collision allocation.  The manifest is deterministic even
    # when the UI list order changes.
    indexed = sorted(enumerate(records), key=lambda pair: (conversation_identity(pair[1])[0], pair[0]))
    seen_ids: set[str] = set()
    used_targets: set[Path] = set()
    entries: list[dict[str, Any]] = []
    counts = {"created": 0, "updated": 0, "renamed": 0, "unchanged": 0, "skipped": 0}

    for original_index, conversation in indexed:
        conversation_id, thread_id = conversation_identity(conversation)
        if conversation_id in seen_ids:
            entries.append(
                {
                    "conversation_id": conversation_id,
                    "thread_id": thread_id,
                    "action": "skipped_duplicate_source",
                    "source_index": original_index,
                }
            )
            counts["skipped"] += 1
            continue
        seen_ids.add(conversation_id)
        old = by_identity.get(conversation_id) or by_identity.get(thread_id)
        title = clean_title(conversation.get("title"), conversation=conversation)
        target = _candidate_paths(conversation, vault_root=vault, used=used_targets)
        bucket = conversation_date(conversation)
        base_target = _safe_vault_path(
            vault,
            CONVERSATIONS_ROOT
            / f"{bucket:%Y}"
            / f"{bucket:%m}"
            / f"{slugify_title(title)}.md",
        )
        # Existing identity wins over the fact that its path is occupied.  In
        # particular, this makes a second run truly unchanged instead of
        # suffixing the same note again.
        if old is not None and old.path not in used_targets:
            if old.path == base_target or old.path.name.startswith(f"{base_target.stem}--"):
                target = old.path
        # If the existing identity already occupies this target, allow it to
        # remain there.  Otherwise a title/date change is a safe rename.
        if old is not None and old.path == target:
            pass
        elif old is not None and target.exists():
            target_metadata = parse_frontmatter(target.read_text(encoding="utf-8", errors="ignore"))
            if _same_identity(ExistingNote(target, target_metadata), conversation_id, thread_id):
                old = ExistingNote(target, target_metadata)
            else:
                target = _candidate_paths(conversation, vault_root=vault, used=used_targets | {old.path})
        used_targets.add(target)
        rendered = render_conversation(conversation, existing=old)
        relative_target = _relative(target, vault)

        if old is None:
            action = "create"
            counts["created"] += 1
            if not dry_run:
                _atomic_write(target, rendered)
        else:
            old_text = old.path.read_text(encoding="utf-8", errors="ignore") if old.path.exists() else ""
            same_content = old_text == rendered
            renamed = old.path != target
            action = "unchanged" if same_content and not renamed else ("rename" if renamed else "update")
            counts["unchanged" if action == "unchanged" else ("renamed" if action == "rename" else "updated")] += 1
            if not dry_run:
                if renamed:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        raise FileExistsError(f"Refusing to overwrite conversation note: {target}")
                    old.path.rename(target)
                if not same_content or renamed:
                    _atomic_write(target, rendered)

        entries.append(
            {
                "conversation_id": conversation_id,
                "thread_id": thread_id,
                "title": title,
                "path": relative_target,
                "action": action,
                "source_index": original_index,
                **({"previous_path": _relative(old.path, vault)} if old is not None and old.path != target else {}),
            }
        )

    return {
        "manifest_version": 1,
        "projection": "private-obsidian-conversations",
        "source": SOURCE_LABEL,
        "vault_root": str(vault),
        "dry_run": dry_run,
        "counts": counts,
        "entries": entries,
    }


def load_conversations(source_path: str | Path) -> list[dict[str, Any]]:
    path = Path(source_path).expanduser()
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("conversations") if isinstance(payload, Mapping) else payload
    if not isinstance(records, list):
        raise ValueError("Conversation source must contain a conversations list.")
    return [record for record in records if isinstance(record, dict)]


def run_migration(
    *,
    source_path: str | Path,
    vault_root: str | Path,
    dry_run: bool = True,
) -> dict[str, Any]:
    return export_conversations(load_conversations(source_path), vault_root=vault_root, dry_run=dry_run)


# A concise alias for callers that use the exporter as a small library.
run = run_migration
