from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.skills import JsonSkillMigrator


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run, apply, recover, or roll back the canonical Vellum skill migration.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / ".skills")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report mappings and collisions without changing packages.")
    mode.add_argument("--rollback", metavar="SNAPSHOT", help="Restore a migration snapshot identifier.")
    mode.add_argument("--recover", action="store_true", help="Recover an interrupted migration from its recorded snapshot.")
    args = parser.parse_args()
    migrator = JsonSkillMigrator(args.root)
    if args.rollback:
        payload = migrator.rollback(args.rollback)
    elif args.recover:
        payload = migrator.recover_interrupted() or {"ok": True, "status": "no_interrupted_migration"}
    else:
        report = migrator.dry_run() if args.dry_run else migrator.apply()
        payload = report.to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not isinstance(payload, dict) or not payload.get("invalid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
