#!/usr/bin/env python3
"""One-shot: rename naval manifest files to the handle-agnostic names.

Vault/Library/X/naval/naval-tweets.json   -> tweets.json
Vault/Library/X/naval/naval-tweets.jsonl  -> tweets.jsonl

Idempotent: if the new name already exists, leaves things alone.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def vault_path(project_root: Path) -> Path:
    load_dotenv(project_root / ".env")
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(configured) if configured else project_root / "Vault"


def run(project_root: Path) -> int:
    vault = vault_path(project_root)
    base = vault / "Library" / "X" / "naval"
    if not base.exists():
        print(f"Naval folder not found at {base}; nothing to rename.")
        return 0

    pairs = [
        ("naval-tweets.json",  "tweets.json"),
        ("naval-tweets.jsonl", "tweets.jsonl"),
    ]
    renamed_any = False
    for old_name, new_name in pairs:
        old = base / old_name
        new = base / new_name
        if not old.exists():
            print(f"skip: {old_name} does not exist")
            continue
        if new.exists():
            print(f"skip: {new_name} already exists; leaving {old_name} in place")
            continue
        old.rename(new)
        print(f"renamed: {old_name} -> {new_name}")
        renamed_any = True
    if not renamed_any:
        print("Nothing to do.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        return run(args.project_root.resolve())
    except Exception as exc:
        print(f"naval rename failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
