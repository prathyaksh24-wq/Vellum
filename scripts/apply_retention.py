#!/usr/bin/env python3
"""Safely retain the private Obsidian conversation projection.

Only ``Agent/Conversations/YYYY/MM/*.md`` and its mirrored archive are in
scope.  The canonical JSON store and legacy raw conversation folders are never
modified by this script.  Dry-run is the default; deletion requires ``--apply``
and a verified distilled card.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CONVERSATIONS_ROOT = Path("Agent") / "Conversations"
ARCHIVE_ROOT = Path("Archive") / "Agent" / "Conversations"
MEMORY_ROOT = Path("Agent") / "Memories" / "Conversations"
RETENTION_NOTE = "Archived from:"
CARD_TYPES = {"conversation_memory", "retention_memory"}


@dataclass(frozen=True)
class RetentionFile:
    path: Path
    rel_path: str
    captured_at: datetime


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def configured_vault(project_root: Path) -> Path:
    load_dotenv(project_root / ".env")
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(configured).expanduser() if configured else project_root / "Vault"


def parse_frontmatter(text: str) -> dict[str, str]:
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1] if value[0] == "'" else _json_string(value)
        if key:
            metadata[key] = value
    return metadata


def _json_string(value: str) -> str:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return value[1:-1]
    return str(parsed)


def parse_datetime(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value or value.casefold() in {"today", "yesterday", "tomorrow"}:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(value[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def file_datetime(path: Path) -> datetime:
    metadata = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for key in (
        "updated_at",
        "conversation_date",
        "captured_at",
        "captured_utc",
        "created",
        "created_at",
        "date",
    ):
        parsed = parse_datetime(metadata.get(key))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def retention_keep(path: Path) -> bool:
    metadata = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    pinned = metadata.get("pinned", "").strip().casefold()
    retention = metadata.get("retention", "").strip().casefold()
    return pinned in {"true", "yes", "1"} or retention in {"keep", "never", "permanent"}


def _is_conversation_rel(rel_path: str, *, archived: bool = False) -> bool:
    parts = Path(rel_path).as_posix().split("/")
    if archived:
        if len(parts) != 6 or parts[:3] != ["Archive", "Agent", "Conversations"]:
            return False
        year, month, name = parts[3], parts[4], parts[5]
    else:
        if len(parts) != 5 or parts[:2] != ["Agent", "Conversations"]:
            return False
        year, month, name = parts[2], parts[3], parts[4]
    return bool(re.fullmatch(r"\d{4}", year) and re.fullmatch(r"\d{2}", month) and name.endswith(".md"))


def discover_conversation_files(vault: Path) -> list[RetentionFile]:
    root = vault / CONVERSATIONS_ROOT
    if not root.exists():
        return []
    files: list[RetentionFile] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(vault).as_posix()
        if not _is_conversation_rel(rel) or path.name.startswith("_") or retention_keep(path):
            continue
        files.append(RetentionFile(path=path, rel_path=rel, captured_at=file_datetime(path)))
    return files


def discover_archive_files(vault: Path) -> list[RetentionFile]:
    root = vault / ARCHIVE_ROOT
    if not root.exists():
        return []
    files: list[RetentionFile] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(vault).as_posix()
        if not _is_conversation_rel(rel, archived=True) or path.name.startswith("_") or retention_keep(path):
            continue
        files.append(RetentionFile(path=path, rel_path=rel, captured_at=file_datetime(path)))
    return files


def archive_target(vault: Path, item: RetentionFile) -> Path:
    return vault / Path("Archive") / item.rel_path


def memory_target(vault: Path, item: RetentionFile) -> Path:
    parts = item.rel_path.split("/")
    if parts[:3] == ["Archive", "Agent", "Conversations"]:
        year, month, name = parts[3], parts[4], parts[5]
    elif parts[:2] == ["Agent", "Conversations"]:
        year, month, name = parts[2], parts[3], parts[4]
    else:
        raise ValueError(f"Not a conversation projection: {item.rel_path}")
    stem = Path(name).stem
    return vault / MEMORY_ROOT / year / month / f"{stem}-memory.md"


def relative(path: Path, vault: Path) -> str:
    return path.relative_to(vault).as_posix()


def archive_note_text(original_text: str, original_rel_path: str, archived_at: datetime) -> str:
    marker = f"{RETENTION_NOTE} {original_rel_path}"
    if marker in original_text:
        return original_text
    return f"{original_text.rstrip()}\n\n---\n\n## Retention\n\n- {marker}\n- Archived at: {archived_at.isoformat()}\n"


def extract_body(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def clean_excerpt(text: str, max_words: int = 120) -> str:
    words = re.findall(r"\S+", re.sub(r"\s+", " ", text).strip())
    if not words:
        return "No readable conversation text was available for this memory card."
    excerpt = " ".join(words[:max_words])
    return excerpt + (" …" if len(words) > max_words else "")


def _source_metadata(item: RetentionFile) -> dict[str, str]:
    return parse_frontmatter(item.path.read_text(encoding="utf-8", errors="ignore"))


def distill_text(items: list[RetentionFile], vault: Path, now: datetime) -> str:
    """Create card text without depending on or reading any other vault root."""

    if not items:
        raise ValueError("Cannot distill an empty item group.")
    item = items[0]
    metadata = _source_metadata(item)
    source_paths = [entry.rel_path for entry in items]
    bodies = [extract_body(entry.path.read_text(encoding="utf-8", errors="ignore")) for entry in items]
    source_id = metadata.get("conversation_id", "")
    title = metadata.get("title") or Path(item.rel_path).stem
    sources = "\n".join(f"- `{source}`" for source in source_paths)
    combined_body = "\n\n".join(bodies)
    return f"""---
type: conversation_memory
source_path: {json.dumps(item.rel_path, ensure_ascii=False)}
conversation_id: {json.dumps(source_id, ensure_ascii=False)}
created: {json.dumps(now.date().isoformat())}
source_count: {len(items)}
---

# {title} — Distilled Memory

## Distilled Memory

{clean_excerpt(combined_body)}

## Source

{sources}
"""


def verify_card(card_path: Path, item: RetentionFile | None = None) -> bool:
    """Return true only for a readable card tied to the item being deleted."""

    if not card_path.is_file():
        return False
    try:
        text = card_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    metadata = parse_frontmatter(text)
    if metadata.get("type", "").casefold() not in CARD_TYPES:
        return False
    if "## Distilled Memory" not in text or not extract_body(text).strip():
        return False
    if item is not None:
        source = metadata.get("source_path", "")
        if source and source != item.rel_path:
            return False
        if not source and item.rel_path not in text:
            return False
    return True


def _write_card_if_missing(card: Path, item: RetentionFile, vault: Path, now: datetime) -> tuple[bool, bool]:
    """Return (card_is_verified, card_was_created), never replacing a card."""

    if card.exists():
        return verify_card(card, item), False
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(distill_text([item], vault, now), encoding="utf-8", newline="\n")
    return verify_card(card, item), True


def _same_conversation(source: Path, archived: Path) -> bool:
    source_meta = parse_frontmatter(source.read_text(encoding="utf-8", errors="ignore"))
    archived_meta = parse_frontmatter(archived.read_text(encoding="utf-8", errors="ignore"))
    for key in ("conversation_id", "thread_id"):
        if source_meta.get(key) and source_meta.get(key) == archived_meta.get(key):
            return True
    return source.read_text(encoding="utf-8", errors="ignore") == archived.read_text(encoding="utf-8", errors="ignore")


def update_index(ingester: Any | None, *, deleted: str | None = None, ingested: Path | None = None) -> None:
    if ingester is None:
        return
    if deleted:
        ingester.delete_file_records(deleted)
    if ingested is not None:
        ingester.ingest_file(ingested)


def run(
    *,
    vault_root: Path,
    now: datetime | None = None,
    archive_after_days: int = 30,
    delete_after_days: int = 90,
    dry_run: bool = True,
    ingester: Any | None = None,
    # Kept as accepted compatibility knobs for callers of the old script.  The
    # new projection has one retention policy, so legacy direct folders are not
    # considered regardless of these values.
    query_after_days: int | None = None,
    response_after_days: int | None = None,
) -> dict[str, int]:
    del query_after_days, response_after_days
    vault = Path(vault_root).expanduser().resolve()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    result = {
        "would_archive": 0,
        "would_distill": 0,
        "would_delete": 0,
        "archived": 0,
        "distilled": 0,
        "deleted": 0,
        "blocked": 0,
    }

    hot = discover_conversation_files(vault)
    to_archive = [item for item in hot if (now - item.captured_at).days >= archive_after_days]
    archived = discover_archive_files(vault)
    to_delete = [item for item in archived if (now - item.captured_at).days >= delete_after_days]
    result["would_archive"] = len(to_archive)
    result["would_distill"] = len(to_delete)
    result["would_delete"] = len(to_delete)
    if dry_run:
        return result

    for item in to_archive:
        if not item.path.exists() or retention_keep(item.path):
            continue
        target = archive_target(vault, item)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not _same_conversation(item.path, target):
                result["blocked"] += 1
                continue
            # A previous run completed the archive but was interrupted before
            # removing the source.  The verified same-identity copy is safe.
            item.path.unlink()
            result["archived"] += 1
            update_index(ingester, deleted=item.rel_path)
            continue
        original = item.path.read_text(encoding="utf-8", errors="ignore")
        target.write_text(archive_note_text(original, item.rel_path, now), encoding="utf-8", newline="\n")
        item.path.unlink()
        result["archived"] += 1
        update_index(ingester, deleted=item.rel_path, ingested=target)

    # Deletion candidates were discovered before archival.  They are all under
    # the archive and therefore already satisfy the archive-before-delete rule.
    for item in to_delete:
        if not item.path.exists() or retention_keep(item.path):
            continue
        card = memory_target(vault, item)
        verified, created = _write_card_if_missing(card, item, vault, now)
        if created:
            result["distilled"] += 1
            update_index(ingester, ingested=card)
        # This check is intentionally immediately before unlink: a missing or
        # malformed card can never turn into a destructive delete.
        if not verified or not verify_card(card, item):
            result["blocked"] += 1
            continue
        item.path.unlink()
        result["deleted"] += 1
        update_index(ingester, deleted=item.rel_path)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--vault-root", "--vault", dest="vault_root", type=Path)
    parser.add_argument("--archive-after-days", type=int, default=30)
    parser.add_argument("--delete-after-days", type=int, default=90)
    parser.add_argument("--query-after-days", type=int, default=30, help=argparse.SUPPRESS)
    parser.add_argument("--response-after-days", type=int, default=90, help=argparse.SUPPRESS)
    parser.add_argument("--apply", action="store_true", help="Actually archive/delete. Defaults to dry-run.")
    args = parser.parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    vault = args.vault_root or configured_vault(project_root)
    result = run(
        vault_root=vault,
        archive_after_days=args.archive_after_days,
        delete_after_days=args.delete_after_days,
        dry_run=not args.apply,
        query_after_days=args.query_after_days,
        response_after_days=args.response_after_days,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
