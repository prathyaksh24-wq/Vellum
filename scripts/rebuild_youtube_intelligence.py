"""Rebuild local YouTube interest projections from Knowledge Core observations."""

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
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--mode",
        choices=("incremental", "backfill"),
        default="incremental",
        help="Use incremental ingestion, or explicitly reconcile the full history.",
    )
    args = parser.parse_args()

    intelligence = YouTubeIntelligenceService(KnowledgeStore(args.database, args.blobs))
    result = intelligence.rebuild(mode=args.mode)
    status = intelligence.snapshot(limit=1)
    print(
        json.dumps(
            {
                "rebuild": result,
                "projection_updated_at": status["projection_updated_at"],
                "counts": status["counts"],
                "readiness": status["readiness"],
                "local_only": status["local_only"],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
