"""Monthly Apify spend ledger with $5/mo cap warnings."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CAP_USD = 5.00
WARN_USD = 4.50


class BudgetExhausted(Exception):
    """Raised when cumulative spend for the month is at or above CAP_USD."""


class BudgetLedger:
    """Tracks cumulative Apify spend per calendar month at a JSON path."""

    def __init__(self, path: Path, month: str | None = None) -> None:
        self.path = path
        self.month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def used(self) -> float:
        return float(self._load().get(self.month, {}).get("used_usd", 0.0))

    def near_cap(self) -> bool:
        return self.used() >= WARN_USD

    def record(self, *, handle: str, run_usd: float) -> None:
        data = self._load()
        bucket = data.setdefault(self.month, {"used_usd": 0.0, "runs": []})
        bucket["used_usd"] = round(bucket.get("used_usd", 0.0) + float(run_usd), 6)
        bucket["runs"].append({
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "handle": handle,
            "cost_usd": float(run_usd),
        })
        self._save(data)

    def pre_call_check(self) -> None:
        used = self.used()
        if used >= CAP_USD:
            raise BudgetExhausted(
                f"Monthly Apify cap reached: ${used:.2f}/${CAP_USD:.2f}. "
                f"Swap APIFY_API_TOKEN or wait for next month."
            )

    def announce(self) -> None:
        """Print the budget line to stdout, and a warning to stderr if near cap."""
        used = self.used()
        print(f"[budget: ${used:.2f}/${CAP_USD:.2f} used this month]")
        if used >= WARN_USD:
            print(
                "BUDGET NEAR CAP - swap APIFY_API_TOKEN in .env when convenient",
                file=sys.stderr,
            )


def parse_run_usage(run: dict | None) -> float:
    """Extract billed USD from an Apify run dict.

    Tolerates both legacy field names (`usageTotalUsd`, `usageUsd`).
    Returns 0.0 if neither is present.
    """
    if not run:
        return 0.0
    return float(run.get("usageTotalUsd") or run.get("usageUsd") or 0.0)
