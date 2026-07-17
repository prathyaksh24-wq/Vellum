"""SQLite-backed token-usage ledger for `vellum usage`."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.telemetry.prices import compute_cost_usd

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  model TEXT NOT NULL,
  in_tokens INTEGER NOT NULL,
  out_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
PRAGMA user_version = 1;
"""


class UsageLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        return conn

    def record(
        self,
        *,
        thread_id: str,
        model: str,
        in_tokens: int,
        out_tokens: int,
        source: str,
        ts: str | None = None,
    ) -> None:
        ts = ts or datetime.now(timezone.utc).isoformat()
        cost = compute_cost_usd(model, in_tokens, out_tokens)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO usage (ts, thread_id, model, in_tokens, out_tokens, cost_usd, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, thread_id, model, in_tokens, out_tokens, cost, source),
            )

    def all_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM usage ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    def summarize(self, *, days: int = 7) -> list[dict[str, Any]]:
        """Aggregate by model over the last `days` days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT model,
                       SUM(in_tokens)  AS in_tokens,
                       SUM(out_tokens) AS out_tokens,
                       SUM(cost_usd)   AS cost_usd
                FROM usage
                WHERE ts >= ?
                GROUP BY model
                ORDER BY cost_usd DESC
                """,
                (cutoff,),
            )
            return [dict(r) for r in cur.fetchall()]

    def observability_summary(self, *, days: int | None = 7) -> dict[str, Any]:
        """Return real usage aggregates for the observability surface."""

        cutoff = None if days is None else (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        where = "" if cutoff is None else "WHERE ts >= ?"
        params: tuple[Any, ...] = () if cutoff is None else (cutoff,)
        with self._connect() as conn:
            totals = conn.execute(
                f"""
                SELECT COALESCE(SUM(in_tokens), 0) AS input_tokens,
                       COALESCE(SUM(out_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost_usd), 0) AS cost_usd,
                       COUNT(*) AS calls,
                       COUNT(DISTINCT thread_id) AS sessions
                FROM usage {where}
                """,
                params,
            ).fetchone()
            models = conn.execute(
                f"""
                SELECT model,
                       SUM(in_tokens) AS input_tokens,
                       SUM(out_tokens) AS output_tokens,
                       SUM(cost_usd) AS cost_usd,
                       COUNT(*) AS calls
                FROM usage {where}
                GROUP BY model ORDER BY (SUM(in_tokens) + SUM(out_tokens)) DESC
                """,
                params,
            ).fetchall()
            daily = conn.execute(
                f"""
                SELECT substr(ts, 1, 10) AS day,
                       SUM(in_tokens) AS input_tokens,
                       SUM(out_tokens) AS output_tokens,
                       SUM(cost_usd) AS cost_usd
                FROM usage {where}
                GROUP BY substr(ts, 1, 10) ORDER BY day
                """,
                params,
            ).fetchall()
            recent = conn.execute(
                f"""
                SELECT id, ts, thread_id, model, in_tokens AS input_tokens,
                       out_tokens AS output_tokens, cost_usd, source
                FROM usage {where}
                ORDER BY id DESC LIMIT 20
                """,
                params,
            ).fetchall()
        result = dict(totals)
        result["total_tokens"] = int(result["input_tokens"] or 0) + int(result["output_tokens"] or 0)
        result["models"] = [dict(row) for row in models]
        result["daily"] = [dict(row) for row in daily]
        result["recent"] = [dict(row) for row in recent]
        result["state"] = "ready" if int(result["calls"] or 0) else "empty"
        return result

    def user_version(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("PRAGMA user_version")
            return int(cur.fetchone()[0])
