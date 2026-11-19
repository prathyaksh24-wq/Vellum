"""Durable run metadata and a lightweight live-event fan-out.

Only operational metadata is stored here. Prompt text, response text, tool
arguments, source contents, and local paths are deliberately excluded.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import time
from typing import Any
from zoneinfo import ZoneInfo

from agent.contracts.profile import ProfileActivity, ProfileActivityDay, ProfileActivityItem


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
  response_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  event_count INTEGER NOT NULL DEFAULT 0,
  tool_count INTEGER NOT NULL DEFAULT 0,
  source_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_observability_runs_started ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_observability_runs_thread ON runs(thread_id, started_at DESC);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'in_progress'
);
CREATE INDEX IF NOT EXISTS idx_observability_events_run ON events(response_id, id);
CREATE TABLE IF NOT EXISTS run_context (
  response_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  context_window INTEGER NOT NULL,
  input_used INTEGER NOT NULL,
  input_limit INTEGER NOT NULL,
  output_reserved INTEGER NOT NULL,
  safety_margin INTEGER NOT NULL,
  layers_json TEXT NOT NULL,
  compacted INTEGER NOT NULL DEFAULT 0,
  removed_messages INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_observability_context_thread ON run_context(thread_id, ts DESC);
PRAGMA user_version = 2;
"""

# Context layers Vellum's context projection reports, in prompt order.
CONTEXT_LAYERS = ("instructions", "tool_schemas", "personal_memory", "retrieved_history",
                  "compacted_history", "recent_conversation")

# Paired lifecycle events that become spans in a run trace: start type -> (end types, kind).
_SPAN_PAIRS = {
    "context_preparing": (("context_ready",), "context"),
    "runtime_preparing": (("runtime_prepared",), "runtime"),
    "thinking_started": ((), "thinking"),
    "sub_agent_started": (("sub_agent_completed", "sub_agent_failed"), "agent"),
    "tool_call_started": (("tool_call_completed", "tool_call_failed"), "tool"),
    "source_reading": (("source_read",), "source"),
    "final_answer_started": (("final_answer_completed",), "answer"),
    "context_compacting": (("context_compacted",), "compaction"),
}
_SPAN_PAIRS_END = {kind: ends for ends, kind in _SPAN_PAIRS.values()}
_POINT_EVENTS = {"memory_retrieved": "memory", "source_discovered": "source", "run_failed": "error",
                 "context_compacted": "compaction"}


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _ms(row: dict[str, Any]) -> float:
    if row.get("at_ms"):
        return float(row["at_ms"])
    try:
        return datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).timestamp() * 1000
    except (TypeError, ValueError):
        return 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_text(value: Any, limit: int) -> str:
    """Keep labels useful without allowing content-shaped payloads to persist."""

    text = " ".join(str(value or "").split())
    return text[:limit]


class ObservabilityService:
    """Capture sanitized response lifecycle events and stream them to the UI."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        if "at_ms" not in columns:
            # Millisecond capture time; stream timestamps are second-precision.
            conn.execute("ALTER TABLE events ADD COLUMN at_ms REAL")
        return conn

    def capture(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Persist a safe projection of one response event and publish it live."""

        event_type = str(payload.get("type") or "")
        response_id = _safe_text(payload.get("response_id"), 96)
        thread_id = _safe_text(payload.get("thread_id"), 128)
        if not response_id or not thread_id:
            return None

        ts = _safe_text(payload.get("created_at"), 40) or _now()
        public_type = ""
        label = ""
        name = ""
        status = "in_progress"
        tool_count = 0
        source_count = 0
        context: dict[str, Any] | None = None

        if event_type == "response.created":
            public_type = "run_started"
            label = "Run started"
        elif event_type == "agent.activity":
            activity = payload.get("activity") if isinstance(payload.get("activity"), dict) else {}
            public_type = _safe_text(activity.get("type"), 64) or "activity"
            label = _safe_text(activity.get("label"), 160)
            name = _safe_text(activity.get("name"), 96)
            status = _safe_text(activity.get("status"), 32) or "in_progress"
            metadata = activity.get("metadata") if isinstance(activity.get("metadata"), dict) else {}
            if public_type in {"context_ready", "context_compacted"} and isinstance(metadata.get("context"), dict):
                context = metadata["context"]
        elif event_type == "response.completed":
            response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
            public_type = "run_completed"
            label = "Run completed"
            status = "completed"
            tool_count = len(response.get("tools") or [])
            source_count = len(response.get("sources") or [])
        elif event_type == "error":
            public_type = "run_failed"
            label = "Run failed"
            status = "failed"
        else:
            return None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(response_id, thread_id, status, started_at)
                VALUES (?, ?, 'in_progress', ?)
                ON CONFLICT(response_id) DO NOTHING
                """,
                (response_id, thread_id, ts),
            )
            cur = conn.execute(
                """
                INSERT INTO events(response_id, thread_id, ts, event_type, label, name, status, at_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (response_id, thread_id, ts, public_type, label, name, status, time.time() * 1000),
            )
            if context is not None:
                self._store_context(conn, response_id, thread_id, ts, context)
            if public_type == "run_completed":
                conn.execute(
                    """
                    UPDATE runs SET status='completed', completed_at=?,
                      event_count=event_count+1, tool_count=?, source_count=?
                    WHERE response_id=?
                    """,
                    (ts, tool_count, source_count, response_id),
                )
            elif public_type == "run_failed":
                conn.execute(
                    "UPDATE runs SET status='failed', completed_at=?, event_count=event_count+1 WHERE response_id=?",
                    (ts, response_id),
                )
            else:
                conn.execute(
                    "UPDATE runs SET event_count=event_count+1 WHERE response_id=?",
                    (response_id,),
                )
            event_id = int(cur.lastrowid)

        event = {
            "id": event_id,
            "response_id": response_id,
            "thread_id": thread_id,
            "ts": ts,
            "type": public_type,
            "label": label,
            "name": name,
            "status": status,
        }
        self._publish(event)
        return event

    def _publish(self, event: dict[str, Any]) -> None:
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def events_since(self, event_id: int, *, limit: int = 250) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, response_id, thread_id, ts, event_type AS type, label, name, status "
                "FROM events WHERE id > ? ORDER BY id LIMIT ?",
                (max(0, int(event_id)), max(1, min(int(limit), 1000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_runs(self, *, limit: int = 12) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def profile_activity(self, *, time_zone: str, selected_date: date | None = None, now: datetime | None = None) -> ProfileActivity:
        """Count each recorded response once, in the user's calendar time zone."""
        zone = ZoneInfo(time_zone)
        today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
        start = today - timedelta(days=(today.weekday() + 1) % 7 + 52 * 7)
        selected = selected_date or today
        if not start <= selected <= today:
            raise ValueError("Choose a day in the displayed year.")
        cutoff = datetime.combine(start, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc).isoformat()

        def local_day(timestamp):
            try:
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(zone).date().isoformat()
            except (ValueError, TypeError, AttributeError):
                return ""

        def item(row):
            status = str(row["status"])
            label = {"completed": "Completed a response", "failed": "Response failed"}.get(status, "Started a response")
            return ProfileActivityItem(id=row["response_id"], at=row["started_at"], label=label, status=status)

        with self._connect() as conn:
            conn.create_function("profile_day", 1, local_day)
            counts = conn.execute(
                "SELECT profile_day(started_at) AS day, COUNT(*) AS count FROM runs "
                "WHERE started_at >= ? GROUP BY day", (cutoff,),
            ).fetchall()
            recent = conn.execute(
                "SELECT response_id, started_at, status FROM runs WHERE started_at >= ? "
                "AND profile_day(started_at) BETWEEN ? AND ? ORDER BY started_at DESC LIMIT 8", (cutoff, start.isoformat(), today.isoformat()),
            ).fetchall()
            chosen = conn.execute(
                "SELECT response_id, started_at, status FROM runs WHERE started_at >= ? "
                "AND profile_day(started_at) = ? ORDER BY started_at LIMIT 50", (cutoff, selected.isoformat()),
            ).fetchall()
        return ProfileActivity(
            time_zone=time_zone, today=today,
            days=[ProfileActivityDay(date=row["day"], count=row["count"]) for row in counts
                  if row["day"] and start.isoformat() <= row["day"] <= today.isoformat()],
            recent=[item(row) for row in recent], selected_date=selected, selected_items=[item(row) for row in chosen],
        )

    def summary(self, *, days: int | None = 7) -> dict[str, Any]:
        cutoff = None if days is None else (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        where = "" if cutoff is None else "WHERE started_at >= ?"
        params: tuple[Any, ...] = () if cutoff is None else (cutoff,)
        with self._connect() as conn:
            totals = conn.execute(
                f"""
                SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                  SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) AS active
                FROM runs {where}
                """,
                params,
            ).fetchone()
            active = conn.execute(
                "SELECT * FROM runs WHERE status='in_progress' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        result = {key: int(totals[key] or 0) for key in ("total", "completed", "failed", "active")}
        result["success_rate"] = result["completed"] / max(result["completed"] + result["failed"], 1)
        result["active_run"] = dict(active) if active else None
        return result

    @staticmethod
    def _store_context(conn: sqlite3.Connection, response_id: str, thread_id: str, ts: str,
                       context: dict[str, Any]) -> None:
        """Keep only the numeric shape of a turn's context window: never its content."""
        raw_layers = context.get("layers") if isinstance(context.get("layers"), dict) else {}
        layers = {name: _int(raw_layers.get(name)) for name in CONTEXT_LAYERS}
        window = _int(context.get("window"))
        if not window:
            return
        conn.execute(
            """
            INSERT INTO run_context(response_id, thread_id, ts, context_window, input_used, input_limit,
              output_reserved, safety_margin, layers_json, compacted, removed_messages)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(response_id) DO UPDATE SET ts=excluded.ts, context_window=excluded.context_window,
              input_used=excluded.input_used, input_limit=excluded.input_limit,
              output_reserved=excluded.output_reserved, safety_margin=excluded.safety_margin,
              layers_json=excluded.layers_json,
              compacted=MAX(run_context.compacted, excluded.compacted),
              removed_messages=MAX(run_context.removed_messages, excluded.removed_messages)
            """,
            (response_id, thread_id, ts, window, _int(context.get("used")), _int(context.get("limit")),
             _int(context.get("output_reserved")), _int(context.get("margin")), json.dumps(layers),
             1 if context.get("compacted") else 0, _int(context.get("removed_messages"))),
        )

    @staticmethod
    def _context_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["layers"] = json.loads(item.pop("layers_json") or "{}")
        item["compacted"] = bool(item["compacted"])
        return item

    def thread_context(self, thread_id: str, *, history: int = 30) -> dict[str, Any]:
        """The latest context window of a conversation and how it filled turn by turn."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_context WHERE thread_id=? ORDER BY ts DESC, rowid DESC LIMIT ?",
                (_safe_text(thread_id, 128), max(1, min(int(history), 200))),
            ).fetchall()
        items = [self._context_row(row) for row in rows]
        return {
            "thread_id": thread_id,
            "latest": items[0] if items else None,
            "history": [{"response_id": item["response_id"], "ts": item["ts"], "input_used": item["input_used"],
                         "input_limit": item["input_limit"], "compacted": item["compacted"]}
                        for item in reversed(items)],
            "compactions": sum(1 for item in items if item["compacted"]),
        }

    def context_summary(self, *, days: int | None = 7) -> dict[str, Any]:
        cutoff = None if days is None else (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        where, params = ("", ()) if cutoff is None else ("WHERE ts >= ?", (cutoff,))
        with self._connect() as conn:
            totals = conn.execute(
                f"""
                SELECT COUNT(*) AS turns, COALESCE(AVG(input_used * 1.0 / NULLIF(context_window, 0)), 0) AS avg_fill,
                  COALESCE(MAX(input_used * 1.0 / NULLIF(context_window, 0)), 0) AS peak_fill,
                  COALESCE(SUM(compacted), 0) AS compactions,
                  COALESCE(SUM(CASE WHEN input_used >= input_limit * 0.8 THEN 1 ELSE 0 END), 0) AS near_limit
                FROM run_context {where}
                """,
                params,
            ).fetchone()
            latest = conn.execute(f"SELECT * FROM run_context {where} ORDER BY ts DESC, rowid DESC LIMIT 1",
                                  params).fetchone()
            rows = conn.execute(f"SELECT layers_json FROM run_context {where}", params).fetchall()
        averages = {name: 0 for name in CONTEXT_LAYERS}
        for row in rows:
            for name, value in json.loads(row["layers_json"] or "{}").items():
                if name in averages:
                    averages[name] += _int(value)
        count = max(len(rows), 1)
        return {
            **{key: totals[key] for key in ("turns", "compactions", "near_limit")},
            "avg_fill": round(float(totals["avg_fill"]), 4),
            "peak_fill": round(float(totals["peak_fill"]), 4),
            "avg_layers": {name: round(total / count) for name, total in averages.items()},
            "latest": self._context_row(latest),
        }

    def run_trace(self, response_id: str) -> dict[str, Any] | None:
        """Spans for one run, rebuilt from its lifecycle events (metadata only)."""
        response_id = _safe_text(response_id, 96)
        with self._connect() as conn:
            run = conn.execute("SELECT * FROM runs WHERE response_id=?", (response_id,)).fetchone()
            if run is None:
                return None
            events = [dict(row) for row in conn.execute(
                "SELECT id, ts, at_ms, event_type, label, name, status FROM events "
                "WHERE response_id=? AND event_type NOT IN ('final_answer_delta', 'tool_call_delta') ORDER BY id",
                (response_id,),
            ).fetchall()]
            context = self._context_row(conn.execute(
                "SELECT * FROM run_context WHERE response_id=?", (response_id,)).fetchone())
        run = dict(run)
        origin = _ms(events[0]) if events else _ms({"ts": run["started_at"]})
        end_ms = _ms(events[-1]) if events else origin
        if run.get("completed_at"):
            end_ms = max(end_ms, _ms({"ts": run["completed_at"]}))

        spans: list[dict[str, Any]] = []
        open_spans: list[dict[str, Any]] = []
        thinking: dict[str, Any] | None = None
        grouped_points: dict[tuple[str, str | None], dict[str, Any]] = {}

        def parent_id() -> str | None:
            for span in reversed(open_spans):
                if span["kind"] == "agent":
                    return span["id"]
            return None

        for event in events:
            at = _ms(event) - origin
            kind_type = event["event_type"]
            if thinking is not None and kind_type != "thinking_started":
                thinking["end_ms"] = max(thinking["start_ms"], at)
                thinking["status"] = "completed"
                thinking = None
            if kind_type in _SPAN_PAIRS:
                kind = _SPAN_PAIRS[kind_type][1]
                span = {"id": f"s{event['id']}", "parent": parent_id() if kind in {"tool", "agent", "source"} else None,
                        "kind": kind, "name": event["name"], "label": event["label"], "start_ms": at,
                        "end_ms": None, "status": "in_progress", "count": 1}
                spans.append(span)
                if kind == "thinking":
                    thinking = span
                else:
                    open_spans.append(span)
                continue
            closer = next((span for span in open_spans
                           if kind_type in _SPAN_PAIRS_END.get(span["kind"], ())
                           and (not span["name"] or not event["name"] or span["name"] == event["name"])), None)
            if closer is not None:
                closer["end_ms"] = max(closer["start_ms"], at)
                closer["status"] = "failed" if "failed" in kind_type or event["status"] == "failed" else "completed"
                open_spans.remove(closer)
                continue
            if kind_type in _POINT_EVENTS:
                kind = _POINT_EVENTS[kind_type]
                key = (kind, parent_id())
                if kind in {"source", "memory"} and key in grouped_points:
                    grouped_points[key]["count"] += 1
                    grouped_points[key]["end_ms"] = at
                    continue
                point = {"id": f"p{event['id']}", "parent": key[1], "kind": kind, "name": event["name"],
                         "label": event["label"], "start_ms": at, "end_ms": at,
                         "status": "failed" if kind == "error" else "completed", "count": 1}
                grouped_points[key] = point
                spans.append(point)

        finished = run["status"] != "in_progress"
        for span in spans:
            if span["end_ms"] is None:
                span["end_ms"] = end_ms - origin
                span["status"] = "unfinished" if finished else "in_progress"
        for point in grouped_points.values():
            if point["kind"] == "source" and point["count"] > 1:
                point["label"] = f"Found {point['count']} sources"
        return {
            "run": run,
            "duration_ms": max(0.0, end_ms - origin),
            # Wall-clock start, so a live view can extend open spans to "now".
            "origin_at_ms": origin,
            "precise": bool(events) and all(event.get("at_ms") for event in events),
            "spans": spans,
            "stats": {
                "events": run["event_count"],
                "tool_calls": sum(1 for span in spans if span["kind"] == "tool"),
                "agents": sum(1 for span in spans if span["kind"] == "agent"),
                "sources": sum(span["count"] for span in spans if span["kind"] == "source"),
                "errors": sum(1 for span in spans if span["status"] == "failed"),
            },
            "context": context,
        }

    def raw_event_rows(self) -> list[dict[str, Any]]:
        """Test/support helper; never exposed by the API."""

        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        return [dict(row) for row in rows]
