#!/usr/bin/env python3
"""Poll Apify for configured X handles and ingest into the vault.

Iterates HANDLES from handle_config, polling each in sequence.
Fast-aborts if monthly budget is reached.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_WINDOW_HOURS = 8       # 6h cadence + 2h cushion
DEFAULT_MAX_ITEMS = 100
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


def read_state(base: Path) -> dict:
    state_file = base / ".state" / "naval_x_scraper_state.json"
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def compute_window(state: dict, window_hours: int, now: datetime) -> tuple[datetime, datetime]:
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
    vault = vault_path(project_root)  # loads .env as a side effect
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN missing from environment", file=sys.stderr)
        return 3

    client = _load("apify_tweet_client")
    ingest_mod = _load("x_ingest")
    hc = _load("handle_config")
    budget_mod = _load("x_budget")

    ledger = budget_mod.BudgetLedger(project_root / BUDGET_LEDGER_PATH_REL)

    overall_added = 0
    overall_filtered = 0
    overall_fetched = 0
    failed_handles: list[str] = []

    for handle in hc.HANDLES:
        try:
            ledger.pre_call_check()
        except budget_mod.BudgetExhausted as exc:
            print(f"BUDGET CAP REACHED before {handle.name}: {exc}", file=sys.stderr)
            ledger.announce()
            return 5

        base = hc.vault_base_for(handle, vault)
        base.mkdir(parents=True, exist_ok=True)
        state = read_state(base)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        start, end = compute_window(state, window_hours, now)

        if dry_run:
            print(json.dumps({
                "handle": handle.name,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
            }, indent=2))
            continue

        try:
            items = client.fetch_tweets(
                handle=handle.name,
                start=start,
                end=end,
                max_items=max_items,
                token=token,
            )
        except Exception as exc:
            print(f"[{handle.name}] Apify fetch failed: {exc}", file=sys.stderr)
            failed_handles.append(handle.name)
            continue

        estimated_cost = round(0.0004 * len(items), 6)
        ledger.record(handle=handle.name, run_usd=estimated_cost)

        result = ingest_mod.ingest(handle=handle, vault_root=vault, items=items)
        overall_fetched += result.fetched
        overall_filtered += result.filtered
        overall_added += result.added
        print(
            f"[{handle.name}] fetched {result.fetched}, "
            f"filtered {result.filtered}, added {result.added}, total {result.total}"
        )

    ledger.announce()

    print(
        f"\nDone. fetched={overall_fetched}, filtered={overall_filtered}, "
        f"added={overall_added}, failed={failed_handles or 'none'}"
    )
    return 0 if not failed_handles else 2


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
        print(f"poll_x failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
