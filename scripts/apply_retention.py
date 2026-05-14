#!/usr/bin/env python3
"""Archive and distill raw ingestion notes before deleting old source files."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RAW_ROOTS = ("X", "Youtube", "Sports")
AGENT_DIRECT_RETENTION_ROOTS = ("Agent/Queries", "Agent/Responses")
ARCHIVE_ROOT = "Archive"
MEMORY_ROOT = Path("Agent") / "Memories"
RETENTION_NOTE = "Archived from:"


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
    env_path = project_root / ".env"
    if not env_path.exists():
        return project_root / "Vault"
    load_dotenv(env_path)
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(configured).expanduser() if configured else project_root / "Vault"


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def file_datetime(path: Path) -> datetime:
    text = path.read_text(encoding="utf-8", errors="ignore")
    metadata = parse_frontmatter(text)
    for key in ("captured_at", "captured_utc", "created", "posted_utc", "published_at"):
        value = metadata.get(key)
        if not value:
            continue
        parsed = parse_datetime(value)
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def retention_keep(path: Path) -> bool:
    metadata = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    pinned = metadata.get("pinned", "").casefold()
    retention = metadata.get("retention", "").casefold()
    return pinned in {"true", "yes", "1"} or retention in {"keep", "never", "permanent"}


def parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def discover_hot_files(vault: Path) -> list[RetentionFile]:
    files: list[RetentionFile] = []
    for root in RAW_ROOTS:
        base = vault / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            rel = path.relative_to(vault).as_posix()
            if should_skip_hot(rel) or retention_keep(path):
                continue
            files.append(RetentionFile(path=path, rel_path=rel, captured_at=file_datetime(path)))
    return files


def should_skip_hot(rel_path: str) -> bool:
    name = Path(rel_path).name
    if name.startswith("_") or name in {"agent-guide.md", "latest-5.md", "latest-50.md"}:
        return True
    return rel_path.endswith("/_index.md")


def discover_archive_files(vault: Path) -> list[RetentionFile]:
    base = vault / ARCHIVE_ROOT
    if not base.exists():
        return []
    files = []
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(vault).as_posix()
        if rel.endswith("/_index.md") or retention_keep(path):
            continue
        files.append(RetentionFile(path=path, rel_path=rel, captured_at=file_datetime(path)))
    return files


def discover_agent_direct_files(vault: Path) -> list[RetentionFile]:
    files: list[RetentionFile] = []
    for root in AGENT_DIRECT_RETENTION_ROOTS:
        base = vault / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            rel = path.relative_to(vault).as_posix()
            if rel.endswith("/_index.md") or retention_keep(path):
                continue
            files.append(RetentionFile(path=path, rel_path=rel, captured_at=file_datetime(path)))
    return files


def agent_retention_days(rel_path: str, *, query_days: int, response_days: int) -> int | None:
    if rel_path.startswith("Agent/Queries/"):
        return query_days
    if rel_path.startswith("Agent/Responses/"):
        return response_days
    return None


def archive_target(vault: Path, item: RetentionFile) -> Path:
    return vault / ARCHIVE_ROOT / item.rel_path


def archived_item(vault: Path, item: RetentionFile) -> RetentionFile:
    target = archive_target(vault, item)
    return RetentionFile(path=target, rel_path=relative(target, vault), captured_at=item.captured_at)


def relative(path: Path, vault: Path) -> str:
    return path.relative_to(vault).as_posix()


def archive_note_text(original_text: str, original_rel_path: str, archived_at: datetime) -> str:
    marker = f"{RETENTION_NOTE} {original_rel_path}"
    if marker in original_text:
        return original_text
    return f"{original_text.rstrip()}\n\n---\n\n## Retention\n\n- {marker}\n- Archived at: {archived_at.isoformat()}\n"


def memory_target(vault: Path, item: RetentionFile) -> Path:
    rel = item.rel_path
    if rel.startswith(f"{ARCHIVE_ROOT}/"):
        rel = rel[len(ARCHIVE_ROOT) + 1 :]
    parts = rel.split("/")
    root = parts[0] if parts else "Unknown"
    month = item.captured_at.strftime("%Y-%m")
    if root == "X" and len(parts) > 1:
        return vault / MEMORY_ROOT / "X" / parts[1] / f"{month}-memory.md"
    if root == "Youtube" and "channels" in parts:
        index = parts.index("channels")
        channel = parts[index + 1] if len(parts) > index + 1 else "unknown"
        return vault / MEMORY_ROOT / "Youtube" / channel / f"{month}-memory.md"
    if root == "Sports":
        category = parts[1] if len(parts) > 1 else "general"
        return vault / MEMORY_ROOT / "Sports" / category / f"{month}-memory.md"
    if root == "Agent" and len(parts) > 1 and parts[1] in {"Queries", "Responses"}:
        category = parts[1].casefold()
        return vault / MEMORY_ROOT / "Conversations" / category / f"{month}-memory.md"
    return vault / MEMORY_ROOT / root / f"{month}-memory.md"


def distill_text(items: list[RetentionFile], vault: Path, now: datetime) -> str:
    source_paths = [item.rel_path for item in items]
    bodies = []
    for item in items:
        bodies.append(extract_body(item.path.read_text(encoding="utf-8", errors="ignore")))
    combined = "\n\n".join(bodies)
    themes = extract_keywords(combined)
    source_root = source_paths[0].split("/")[1] if source_paths[0].startswith("Archive/") and len(source_paths[0].split("/")) > 1 else source_paths[0].split("/")[0]
    focus = memory_focus(source_paths[0])
    sample = clean_excerpt(combined, max_words=90)
    sources = "\n".join(f"- `{path}`" for path in source_paths)
    theme_lines = "\n".join(f"- {theme}" for theme in themes) if themes else "- general"
    is_conversation_memory = source_paths[0].startswith("Agent/")
    retention_policy = "agent_queries_30_days_agent_responses_90_days" if is_conversation_memory else "archive_after_30_delete_after_90"
    source_heading = "Conversation Sources Distilled" if is_conversation_memory else "Archived Sources Distilled"
    return f"""---
type: retention_memory
created: {now.date().isoformat()}
source_root: {source_root}
source_count: {len(items)}
retention_policy: {retention_policy}
---

# {focus} Memory - {items[0].captured_at:%Y-%m}

## What Vellum Should Remember

{sample}

## Recurring Themes

{theme_lines}

## User Alignment

- Preserve what helps the agent become more truthful, kind, curious, articulate, and useful.
- For Naval/X material, keep attention on life, spirituality, clarity, judgment, agency, truth, and articulate expression.
- For YouTube and Sports material, keep preference patterns and meaning rather than raw transcripts or raw live data.
- For Queries and Responses, preserve stable preferences, decisions, corrections, values, and useful self-model updates instead of raw conversation clutter.

## {source_heading}

{sources}
"""


def memory_focus(rel_path: str) -> str:
    if "/X/naval/" in rel_path or rel_path.startswith("Archive/X/naval/"):
        return "Naval"
    if "/Youtube/" in rel_path or rel_path.startswith("Archive/Youtube/"):
        parts = rel_path.split("/")
        if "channels" in parts:
            index = parts.index("channels")
            if len(parts) > index + 1:
                return parts[index + 1].replace("-", " ").title()
        return "YouTube"
    if "/Sports/" in rel_path or rel_path.startswith("Archive/Sports/"):
        return "Sports"
    if rel_path.startswith("Agent/Queries/"):
        return "User Queries"
    if rel_path.startswith("Agent/Responses/"):
        return "Agent Responses"
    return "Source"


def extract_body(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def clean_excerpt(text: str, max_words: int) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'.-]*", text)
    excerpt = " ".join(words[:max_words]).strip()
    if not excerpt:
        return "This archived batch contained little readable text; preserve only its source metadata."
    if len(words) > max_words:
        excerpt += "..."
    return excerpt


def extract_keywords(text: str, limit: int = 10) -> list[str]:
    stop = {
        "about", "after", "again", "also", "and", "are", "because", "but", "for", "from",
        "has", "have", "into", "not", "that", "the", "their", "this", "with", "you", "your",
        "video", "transcript", "source", "note", "tweet", "youtube", "sports",
    }
    counts: dict[str, int] = defaultdict(int)
    for word in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text.casefold()):
        if word in stop:
            continue
        counts[word] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _count in ranked[:limit]]


def group_for_memory(items: list[RetentionFile], vault: Path) -> dict[Path, list[RetentionFile]]:
    groups: dict[Path, list[RetentionFile]] = defaultdict(list)
    for item in items:
        groups[memory_target(vault, item)].append(item)
    return groups


def write_memory_groups(
    groups: dict[Path, list[RetentionFile]],
    *,
    vault: Path,
    now: datetime,
    ingester: Any | None,
) -> int:
    written = 0
    for memory_path, items in groups.items():
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(distill_text(items, vault, now), encoding="utf-8", newline="\n")
        written += 1
        update_index(ingester, ingested=memory_path)
    return written


def run(
    *,
    vault_root: Path,
    now: datetime | None = None,
    archive_after_days: int = 30,
    delete_after_days: int = 90,
    query_after_days: int = 30,
    response_after_days: int = 90,
    dry_run: bool = True,
    ingester: Any | None = None,
) -> dict[str, int]:
    vault = Path(vault_root).expanduser().resolve()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    result = {
        "would_archive": 0,
        "would_distill": 0,
        "would_delete": 0,
        "archived": 0,
        "distilled": 0,
        "deleted": 0,
    }

    hot = discover_hot_files(vault)
    to_archive = [item for item in hot if (now - item.captured_at).days >= archive_after_days]
    result["would_archive"] = len(to_archive)

    archived = discover_archive_files(vault)
    to_delete = [item for item in archived if (now - item.captured_at).days >= delete_after_days]
    agent_direct = discover_agent_direct_files(vault)
    agent_to_delete = [
        item
        for item in agent_direct
        if (days := agent_retention_days(item.rel_path, query_days=query_after_days, response_days=response_after_days)) is not None
        and (now - item.captured_at).days >= days
    ]
    archive_memory_targets = set(group_for_memory([archived_item(vault, item) for item in to_archive], vault))
    delete_memory_targets = set(group_for_memory(to_delete, vault))
    agent_memory_targets = set(group_for_memory(agent_to_delete, vault))
    result["would_distill"] = len(archive_memory_targets | delete_memory_targets | agent_memory_targets)
    result["would_delete"] = len(to_delete) + len(agent_to_delete)

    if dry_run:
        return result

    newly_archived: list[RetentionFile] = []
    for item in to_archive:
        target = archive_target(vault, item)
        target.parent.mkdir(parents=True, exist_ok=True)
        original_text = item.path.read_text(encoding="utf-8", errors="ignore")
        target.write_text(archive_note_text(original_text, item.rel_path, now), encoding="utf-8", newline="\n")
        item.path.unlink()
        newly_archived.append(RetentionFile(path=target, rel_path=relative(target, vault), captured_at=item.captured_at))
        result["archived"] += 1
        update_index(ingester, deleted=item.rel_path, ingested=target)

    result["distilled"] += write_memory_groups(
        group_for_memory(newly_archived, vault),
        vault=vault,
        now=now,
        ingester=ingester,
    )

    result["distilled"] += write_memory_groups(
        group_for_memory(to_delete, vault),
        vault=vault,
        now=now,
        ingester=ingester,
    )
    result["distilled"] += write_memory_groups(
        group_for_memory(agent_to_delete, vault),
        vault=vault,
        now=now,
        ingester=ingester,
    )
    for item in to_delete:
        item.path.unlink()
        result["deleted"] += 1
        update_index(ingester, deleted=item.rel_path)
    for item in agent_to_delete:
        item.path.unlink()
        result["deleted"] += 1
        update_index(ingester, deleted=item.rel_path)

    return result


def update_index(ingester: Any | None, *, deleted: str | None = None, ingested: Path | None = None) -> None:
    if ingester is None:
        return
    if deleted:
        ingester.delete_file_records(deleted)
    if ingested is not None:
        ingester.ingest_file(ingested)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--vault-root", type=Path)
    parser.add_argument("--archive-after-days", type=int, default=30)
    parser.add_argument("--delete-after-days", type=int, default=90)
    parser.add_argument("--query-after-days", type=int, default=30)
    parser.add_argument("--response-after-days", type=int, default=90)
    parser.add_argument("--apply", action="store_true", help="Actually move/archive/delete files. Defaults to dry-run.")
    args = parser.parse_args()

    vault = args.vault_root or configured_vault(args.project_root.resolve())
    result = run(
        vault_root=vault,
        archive_after_days=args.archive_after_days,
        delete_after_days=args.delete_after_days,
        query_after_days=args.query_after_days,
        response_after_days=args.response_after_days,
        dry_run=not args.apply,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
