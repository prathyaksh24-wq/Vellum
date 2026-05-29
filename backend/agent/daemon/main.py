from __future__ import annotations

import argparse
import time

from agent.config import get_settings
from agent.daemon.loops.sports import SportsDaemonLoop


def parse_leagues(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def run_once(dry_run: bool = False) -> dict:
    settings = get_settings()
    loop = SportsDaemonLoop(
        vault_root=settings.obsidian_vault_path,
        enabled_leagues=parse_leagues(settings.daemon_sports_enabled_leagues),
        dry_run=dry_run,
    )
    return loop.tick()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vellum background daemon loops.")
    parser.add_argument("--once", action="store_true", help="Run one daemon tick and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate curiosity without fetching.")
    args = parser.parse_args()

    settings = get_settings()
    if args.once:
        result = run_once(dry_run=args.dry_run)
        print(result)
        return 0

    while True:
        result = run_once(dry_run=args.dry_run)
        print(result, flush=True)
        time.sleep(settings.daemon_sports_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
