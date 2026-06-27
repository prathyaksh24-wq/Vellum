#!/usr/bin/env python3
"""Poll xAI X Search for X folders using direct xAI OAuth.

Discovers handles from Vault/Library/X and polls each in sequence.
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
DEFAULT_XAI_TIMEOUT_SECS = 180


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


def run(project_root: Path, dry_run: bool, max_items: int, window_hours: int, timeout_secs: int = DEFAULT_XAI_TIMEOUT_SECS) -> int:
    vault = vault_path(project_root)  # loads .env as a side effect
    oauth_file = project_root / "data" / "xai-oauth.json"

    client = _load("xai_x_search_client")
    ingest_mod = _load("x_ingest")
    hc = _load("handle_config")
    handles = hc.handles_for_vault(vault) if hasattr(hc, "handles_for_vault") else hc.HANDLES
    auth_error_type = getattr(client, "XAIAuthError", None)

    overall_added = 0
    overall_filtered = 0
    overall_fetched = 0
    failed_handles: list[str] = []

    for handle in handles:
        base = hc.vault_base_for(handle, vault)
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

        base.mkdir(parents=True, exist_ok=True)
        try:
            items = client.fetch_tweets(
                handle=handle.name,
                start=start,
                end=end,
                max_items=max_items,
                oauth_file=oauth_file,
                timeout_secs=timeout_secs,
            )
        except Exception as exc:
            if auth_error_type and isinstance(exc, auth_error_type):
                print(f"[{handle.name}] xAI OAuth unavailable: {exc}", file=sys.stderr)
                return 3
            print(f"[{handle.name}] xAI X Search failed: {exc}", file=sys.stderr)
            failed_handles.append(handle.name)
            continue

        result = ingest_mod.ingest(handle=handle, vault_root=vault, items=items)
        overall_fetched += result.fetched
        overall_filtered += result.filtered
        overall_added += result.added
        print(
            f"[{handle.name}] fetched {result.fetched}, "
            f"filtered {result.filtered}, added {result.added}, total {result.total}"
        )

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
    parser.add_argument("--window-days", type=float, help="Alias for --window-hours, expressed in days")
    parser.add_argument("--timeout-secs", type=int, default=DEFAULT_XAI_TIMEOUT_SECS)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    window_hours = int(args.window_days * 24) if args.window_days is not None else args.window_hours
    try:
        return run(args.project_root.resolve(), args.dry_run, args.max_items, window_hours, args.timeout_secs)
    except Exception as exc:
        print(f"poll_x failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
