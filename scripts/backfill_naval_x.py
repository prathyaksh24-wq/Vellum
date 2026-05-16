#!/usr/bin/env python3
"""One-shot: backfill naval's aphorisms for the last 12 months."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HANDLE = "naval"
BACKFILL_MONTHS = 12
MAX_ITEMS_PER_MONTH = 1000
INTER_REQUEST_SLEEP_SECS = 2


def _load(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


def month_windows(now: datetime, months: int) -> list[tuple[datetime, datetime]]:
    """Yield (start, end) pairs walking back `months` calendar months."""
    windows = []
    end = now
    for _ in range(months):
        start = end - timedelta(days=30)
        windows.append((start, end))
        end = start
    return list(reversed(windows))


def run(project_root: Path, months: int, max_per_window: int) -> int:
    vault = vault_path(project_root)
    base = vault / "X" / HANDLE
    base.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN missing from environment", file=sys.stderr)
        return 3

    client = _load("apify_tweet_client")
    ingest_mod = _load("naval_x_ingest")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    windows = month_windows(now, months)

    total_fetched = 0
    total_added = 0
    total_filtered = 0
    for start, end in windows:
        try:
            items = client.fetch_tweets(
                handle=HANDLE,
                start=start,
                end=end,
                max_items=max_per_window,
                token=token,
            )
        except Exception as exc:
            print(f"Window {start.date()}..{end.date()} failed: {exc}", file=sys.stderr)
            continue

        result = ingest_mod.ingest(base=base, items=items)
        total_fetched += result.fetched
        total_filtered += result.filtered
        total_added += result.added
        print(
            f"Window {start.date()}..{end.date()}: fetched {result.fetched}, "
            f"filtered {result.filtered}, added {result.added}"
        )
        time.sleep(INTER_REQUEST_SLEEP_SECS)

    print(
        f"\nBackfill done. Total fetched {total_fetched}, "
        f"filtered {total_filtered}, added {total_added}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=BACKFILL_MONTHS)
    parser.add_argument("--max-per-window", type=int, default=MAX_ITEMS_PER_MONTH)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        return run(args.project_root.resolve(), args.months, args.max_per_window)
    except Exception as exc:
        print(f"naval backfill failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
