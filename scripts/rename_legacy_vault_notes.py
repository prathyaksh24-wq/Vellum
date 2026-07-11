"""Rename archived machine-generated Obsidian notes to human-readable titles."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


SECTION_PATTERNS = (
    re.compile(r"^## Query\s*\n+([^\n]+)", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^## Question\s*\n+([^\n]+)", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^# (?!#)([^\n]+)", re.MULTILINE),
)


def readable_title(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    for pattern in SECTION_PATTERNS:
        match = pattern.search(text)
        if match and match.group(1).strip():
            return match.group(1).strip()
    stem = re.sub(r"^QA\s+\d{8}_\d{6}$", "Conversation", path.stem, flags=re.IGNORECASE)
    stem = re.sub(r"^\d{8}-\d{6}(?:-\d{6})?-", "", stem)
    return stem.replace("-", " ").strip() or "Archived note"


def safe_filename(title: str, *, max_length: int = 96) -> str:
    title = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" .")
    if title:
        title = title[0].upper() + title[1:]
    for token, display in {
        "f1": "F1",
        "fifa": "FIFA",
        "nba": "NBA",
        "ksi": "KSI",
        "youtube": "YouTube",
        "x": "X",
    }.items():
        title = re.sub(rf"(?i)(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", display, title)
    if len(title) > max_length:
        title = title[:max_length].rstrip(" .")
    return f"{title or 'Archived note'}.md"


def rename_tree(root: Path, *, dry_run: bool = True, generated_only: bool = False) -> dict[str, int]:
    stats = {"renamed": 0, "unchanged": 0, "errors": 0}
    if not root.exists():
        return stats
    for source in sorted(root.rglob("*.md")):
        if source.name.casefold() in {"readme.md", "_index.md"}:
            stats["unchanged"] += 1
            continue
        if generated_only and not re.match(r"^(?:QA\s+)?\d{8}[-_]\d{6}", source.stem, re.IGNORECASE):
            stats["unchanged"] += 1
            continue
        try:
            base = safe_filename(readable_title(source))
            target = source.with_name(base)
            case_only = target.name.casefold() == source.name.casefold()
            suffix = 2
            while target.exists() and target.name != source.name and not case_only:
                target = source.with_name(f"{Path(base).stem} ({suffix}).md")
                suffix += 1
            if target.name == source.name:
                stats["unchanged"] += 1
                continue
            if not dry_run:
                if case_only:
                    temporary = source.with_name(f".{source.stem}.rename-tmp.md")
                    source.rename(temporary)
                    temporary.rename(target)
                else:
                    source.rename(target)
            stats["renamed"] += 1
        except OSError:
            stats["errors"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("vault", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--sports", action="store_true", help="Also rename generated Sports snapshots")
    args = parser.parse_args()
    roots = (
        args.vault / "Archive" / "Legacy Agent Logs",
        args.vault / "Archive" / "Legacy Memory Cards",
    )
    total = {"renamed": 0, "unchanged": 0, "errors": 0}
    for root in roots:
        result = rename_tree(root, dry_run=not args.apply)
        for key, value in result.items():
            total[key] += value
    if args.sports:
        result = rename_tree(args.vault / "Library" / "Sports", dry_run=not args.apply, generated_only=True)
        for key, value in result.items():
            total[key] += value
    print({"mode": "apply" if args.apply else "dry-run", **total})


if __name__ == "__main__":
    main()
