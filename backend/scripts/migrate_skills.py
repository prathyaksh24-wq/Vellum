from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.skills import JsonSkillMigrator


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Vellum JSON skills to SKILL.md packages.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / ".skills")
    args = parser.parse_args()
    report = JsonSkillMigrator(args.root).migrate()
    print(json.dumps({"created": report.created, "skipped": report.skipped, "invalid": report.invalid}))
    return 0 if not report.invalid else 1


if __name__ == "__main__":
    raise SystemExit(main())
