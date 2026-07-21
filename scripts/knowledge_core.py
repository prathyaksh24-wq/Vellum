"""Operational CLI for previewing migration and backing up Knowledge Core."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agent.knowledge.backup import KnowledgeBackupService  # noqa: E402
from agent.knowledge.models import BootstrapRequest  # noqa: E402
from agent.knowledge.service import KnowledgeCore  # noqa: E402
from agent.knowledge.store import KnowledgeStore  # noqa: E402


try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault",
        type=Path,
        default=Path(os.getenv("OBSIDIAN_VAULT_PATH") or REPO_ROOT / "Vault"),
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.getenv("KNOWLEDGE_CORE_DB_PATH") or REPO_ROOT / "data" / "knowledge" / "core.db"),
    )
    parser.add_argument(
        "--blobs",
        type=Path,
        default=Path(os.getenv("KNOWLEDGE_BLOB_PATH") or REPO_ROOT / "data" / "knowledge" / "blobs"),
    )
    parser.add_argument(
        "--conversations",
        type=Path,
        default=REPO_ROOT / "data" / "ui" / "conversations.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("--apply", action="store_true")
    bootstrap.add_argument("--confirm", default="")
    bootstrap.add_argument("--limit", type=int)
    bootstrap.add_argument("--no-conversations", action="store_true")
    bootstrap.add_argument("--no-library", action="store_true")
    bootstrap.add_argument("--no-wiki", action="store_true")
    bootstrap.add_argument("--no-agent-projections", action="store_true")

    backup = subparsers.add_parser("backup")
    backup.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("archive", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    core = KnowledgeCore(
        KnowledgeStore(args.database, args.blobs),
        conversations_path=args.conversations,
        vault_root=args.vault,
    )
    if args.command == "status":
        result = {"knowledge": core.status(), "integrity": core.store.integrity_check()}
    elif args.command == "bootstrap":
        if args.apply and args.confirm != "APPLY_KNOWLEDGE_BOOTSTRAP":
            raise SystemExit("Apply requires --confirm APPLY_KNOWLEDGE_BOOTSTRAP")
        result = core.bootstrap(
            BootstrapRequest(
                conversations=not args.no_conversations,
                vault_library=not args.no_library,
                knowledge_wiki=not args.no_wiki,
                agent_projections=not args.no_agent_projections,
                apply=args.apply,
                confirm=args.apply,
                limit=args.limit,
            )
        )
    elif args.command == "backup":
        result = KnowledgeBackupService(core.store).create(args.output)
    else:
        result = KnowledgeBackupService(core.store).verify(args.archive)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
