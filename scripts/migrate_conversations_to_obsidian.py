#!/usr/bin/env python3
"""Project canonical UI conversations into a private Obsidian vault.

The command is a dry-run by default.  It prints a deterministic JSON manifest;
use ``--apply`` to create, update, or safely rename projection notes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.agent.obsidian.conversation_export import archive_legacy_agent_logs, run_migration  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--source", type=Path, help="Canonical conversations JSON path")
    parser.add_argument("--vault-root", "--vault", dest="vault_root", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write the projection; defaults to dry-run")
    parser.add_argument("--dry-run", action="store_true", help="Explicitly request the default dry-run")
    parser.add_argument("--manifest", type=Path, help="Also write the JSON manifest to this path")
    parser.add_argument(
        "--archive-legacy",
        action="store_true",
        help="Move legacy Agent/Queries and Agent/Responses notes into Archive without deleting them",
    )
    args = parser.parse_args(argv)

    project_root = args.project_root.expanduser().resolve()
    source = (args.source or project_root / "data" / "ui" / "conversations.json").expanduser()
    vault = (args.vault_root or configured_vault(project_root)).expanduser()
    manifest = run_migration(source_path=source, vault_root=vault, dry_run=not args.apply)
    if args.archive_legacy:
        manifest["legacy_archive"] = archive_legacy_agent_logs(vault_root=vault, dry_run=not args.apply)
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.manifest:
        manifest_path = args.manifest.expanduser()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
