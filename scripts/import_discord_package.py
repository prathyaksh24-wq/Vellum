"""Import authored messages from an official Discord data-package ZIP."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from agent.knowledge.store import KnowledgeStore  # noqa: E402
from agent.plugins.discord_package import DiscordPackageImporter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--account-id", default="default")
    parser.add_argument("--idempotency-key", default="")
    args = parser.parse_args()
    store = KnowledgeStore(
        Path(os.getenv("KNOWLEDGE_CORE_DB_PATH") or REPO_ROOT / "data" / "knowledge" / "core.db"),
        Path(os.getenv("KNOWLEDGE_BLOB_PATH") or REPO_ROOT / "data" / "knowledge" / "blobs"),
    )
    result = DiscordPackageImporter(store=store, account_id=args.account_id).run(
        args.archive,
        idempotency_key=args.idempotency_key,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
