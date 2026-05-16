#!/usr/bin/env python3
"""Poll Apify for naval's latest tweets and ingest aphorisms into the vault."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HANDLE = "naval"
DEFAULT_WINDOW_HOURS = 2
DEFAULT_MAX_ITEMS = 200


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


def read_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def compute_window(state: dict, window_hours: int, now: datetime) -> tuple[datetime, datetime]:
    """Lower bound: max(last_run - cushion, now - 14 days). Upper: now."""
    cushion = timedelta(hours=window_hours)
    last_run_iso = state.get("last_run_utc")
    if last_run_iso:
        try:
            last_run = datetime.fromisoformat(last_run_iso)
        except ValueError:
            last_run = now - timedelta(days=1)
    else:
        last_run = now - timedelta(days=1)
    start = max(last_run - cushion, now - timedelta(days=14))
    return start, now


def run(project_root: Path, dry_run: bool, max_items: int, window_hours: int) -> int:
    vault = vault_path(project_root)
    base = vault / "X" / HANDLE
    state_file = base / ".state" / "naval_x_scraper_state.json"

    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN missing from environment", file=sys.stderr)
        return 3

    state = read_state(state_file)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start, end = compute_window(state, window_hours, now)

    client = _load("apify_tweet_client")
    ingest_mod = _load("naval_x_ingest")

    try:
        items = client.fetch_tweets(
            handle=HANDLE,
            start=start,
            end=end,
            max_items=max_items,
            token=token,
        )
    except Exception as exc:
        print(f"Apify fetch failed: {exc}", file=sys.stderr)
        return 2

    if dry_run:
        print(json.dumps({
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "fetched": len(items),
        }, indent=2))
        return 0

    result = ingest_mod.ingest(base=base, items=items)
    print(
        f"Fetched {result.fetched}, filtered {result.filtered}, "
        f"added {result.added}, total {result.total}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        return run(args.project_root.resolve(), args.dry_run, args.max_items, args.window_hours)
    except Exception as exc:
        print(f"naval polling failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
