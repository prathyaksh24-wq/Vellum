#!/usr/bin/env python3
"""One-shot: backfill X posts across X folders via direct xAI OAuth."""
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
WINDOW_DAYS = 7
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


def day_windows(now: datetime, days: int, window_days: int = WINDOW_DAYS) -> list[tuple[datetime, datetime]]:
    windows = []
    end = now
    remaining = days
    while remaining > 0:
        span = min(window_days, remaining)
        start = end - timedelta(days=span)
        windows.append((start, end))
        end = start
        remaining -= span
    return list(reversed(windows))


def run(project_root: Path, only_handle: str | None, days: int, max_per_window: int, timeout_secs: int = DEFAULT_XAI_TIMEOUT_SECS) -> int:
    vault = vault_path(project_root)  # loads .env
    oauth_file = project_root / "data" / "xai-oauth.json"

    client = _load("xai_x_search_client")
    ingest_mod = _load("x_ingest")
    hc = _load("handle_config")
    auth_error_type = getattr(client, "XAIAuthError", None)

    all_handles = hc.handles_for_vault(vault) if hasattr(hc, "handles_for_vault") else hc.HANDLES
    handles = all_handles if only_handle is None else [hc.get_handle(only_handle)]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    windows = day_windows(now, days)
    failed_handles: list[str] = []

    for handle in handles:
        print(f"\n=== {handle.name} ===")
        for start, end in windows:
            try:
                items = client.fetch_tweets(
                    handle=handle.name,
                    start=start,
                    end=end,
                    max_items=max_per_window,
                    oauth_file=oauth_file,
                    timeout_secs=timeout_secs,
                )
            except Exception as exc:
                if auth_error_type and isinstance(exc, auth_error_type):
                    print(f"[{handle.name}] xAI OAuth unavailable: {exc}", file=sys.stderr)
                    return 3
                print(f"[{handle.name}] {start.date()}..{end.date()} failed: {exc}", file=sys.stderr)
                failed_handles.append(handle.name)
                continue
            result = ingest_mod.ingest(handle=handle, vault_root=vault, items=items)
            print(
                f"[{handle.name}] {start.date()}..{end.date()}: "
                f"fetched {result.fetched}, filtered {result.filtered}, added {result.added}"
            )
            time.sleep(INTER_REQUEST_SLEEP_SECS)

    return 0 if not failed_handles else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="Backfill all configured handles")
    g.add_argument("--handle", type=str, help="Single handle name")
    parser.add_argument("--months", type=int, default=BACKFILL_MONTHS)
    parser.add_argument("--days", type=int, help="Backfill depth in days; overrides --months")
    parser.add_argument("--max-per-window", type=int, default=MAX_ITEMS_PER_WINDOW)
    parser.add_argument("--timeout-secs", type=int, default=DEFAULT_XAI_TIMEOUT_SECS)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()

    only = args.handle if args.handle else None
    days = args.days if args.days is not None else args.months * 30

    try:
        return run(args.project_root.resolve(), only, days, args.max_per_window, args.timeout_secs)
    except Exception as exc:
        print(f"backfill_x failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
