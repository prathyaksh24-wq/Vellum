#!/usr/bin/env python3
"""One-shot: backfill X aphorisms across configured handles."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


BACKFILL_MONTHS = 12
MAX_ITEMS_PER_WINDOW = 1000
INTER_REQUEST_SLEEP_SECS = 2
BUDGET_LEDGER_PATH_REL = Path("data") / "apify-budget.json"


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
    windows = []
    end = now
    for _ in range(months):
        start = end - timedelta(days=30)
        windows.append((start, end))
        end = start
    return list(reversed(windows))


def run(project_root: Path, only_handle: str | None, months: int, max_per_window: int) -> int:
    vault = vault_path(project_root)  # loads .env
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN missing from environment", file=sys.stderr)
        return 3

    client = _load("apify_tweet_client")
    ingest_mod = _load("x_ingest")
    hc = _load("handle_config")
    budget_mod = _load("x_budget")
    ledger = budget_mod.BudgetLedger(project_root / BUDGET_LEDGER_PATH_REL)

    handles = hc.HANDLES if only_handle is None else [hc.get_handle(only_handle)]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    windows = month_windows(now, months)

    for handle in handles:
        print(f"\n=== {handle.name} ===")
        for start, end in windows:
            try:
                ledger.pre_call_check()
            except budget_mod.BudgetExhausted as exc:
                print(f"BUDGET CAP REACHED: {exc}", file=sys.stderr)
                ledger.announce()
                return 5
            try:
                items = client.fetch_tweets(
                    handle=handle.name,
                    start=start,
                    end=end,
                    max_items=max_per_window,
                    token=token,
                )
            except Exception as exc:
                print(f"[{handle.name}] {start.date()}..{end.date()} failed: {exc}", file=sys.stderr)
                continue
            estimated_cost = round(0.0004 * len(items), 6)
            ledger.record(handle=handle.name, run_usd=estimated_cost)
            result = ingest_mod.ingest(handle=handle, vault_root=vault, items=items)
            print(
                f"[{handle.name}] {start.date()}..{end.date()}: "
                f"fetched {result.fetched}, filtered {result.filtered}, added {result.added}"
            )
            time.sleep(INTER_REQUEST_SLEEP_SECS)

    ledger.announce()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="Backfill all configured handles")
    g.add_argument("--handle", type=str, help="Single handle name")
    parser.add_argument("--months", type=int, default=BACKFILL_MONTHS)
    parser.add_argument("--max-per-window", type=int, default=MAX_ITEMS_PER_WINDOW)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()

    only = args.handle if args.handle else None

    try:
        return run(args.project_root.resolve(), only, args.months, args.max_per_window)
    except Exception as exc:
        print(f"backfill_x failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
