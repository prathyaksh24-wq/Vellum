from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

from agent.memory.sessions import SESSIONS_DB


@dataclass(frozen=True)
class MasterThreadState:
    thread_id: str
    active_agent: str = "VellumAgent"
    agent_selected: bool = False
    selected_model: str = ""
    reasoning_mode: str = ""
    store_to_memory: bool = True
    pending_reroute_target: str = ""
    pending_reroute_reason: str = ""


class MasterThreadStateStore:
    def __init__(self, *, sessions_db: Path = SESSIONS_DB) -> None:
        self.sessions_db = Path(sessions_db)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.sessions_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.sessions_db))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS master_thread_state (
                    thread_id TEXT PRIMARY KEY,
                    active_agent TEXT NOT NULL DEFAULT 'VellumAgent',
                    pending_reroute_target TEXT NOT NULL DEFAULT '',
                    pending_reroute_reason TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(master_thread_state)").fetchall()
            }
            if "selected_model" not in columns:
                conn.execute("ALTER TABLE master_thread_state ADD COLUMN selected_model TEXT NOT NULL DEFAULT ''")
            if "reasoning_mode" not in columns:
                conn.execute("ALTER TABLE master_thread_state ADD COLUMN reasoning_mode TEXT NOT NULL DEFAULT ''")
            if "store_to_memory" not in columns:
                conn.execute("ALTER TABLE master_thread_state ADD COLUMN store_to_memory INTEGER NOT NULL DEFAULT 1")
            if "agent_selected" not in columns:
                conn.execute("ALTER TABLE master_thread_state ADD COLUMN agent_selected INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS master_pending_actions (
                    thread_id TEXT PRIMARY KEY,
                    action_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get(self, thread_id: str) -> MasterThreadState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM master_thread_state WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return MasterThreadState(thread_id=thread_id)
        return MasterThreadState(
            thread_id=thread_id,
            active_agent=row["active_agent"],
            agent_selected=bool(row["agent_selected"]),
            selected_model=row["selected_model"],
            reasoning_mode=row["reasoning_mode"],
            store_to_memory=bool(row["store_to_memory"]),
            pending_reroute_target=row["pending_reroute_target"],
            pending_reroute_reason=row["pending_reroute_reason"],
        )

    def set_active_agent(self, thread_id: str, agent_name: str, *, selected: bool = False) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO master_thread_state (thread_id, active_agent, agent_selected, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    active_agent = excluded.active_agent,
                    agent_selected = excluded.agent_selected,
                    updated_at = excluded.updated_at
                """,
                (thread_id, agent_name, int(selected)),
            )

    def set_selected_model(self, thread_id: str, model_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO master_thread_state (thread_id, selected_model, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    selected_model = excluded.selected_model,
                    updated_at = excluded.updated_at
                """,
                (thread_id, model_id),
            )

    def set_reasoning_mode(self, thread_id: str, reasoning_mode: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO master_thread_state (thread_id, reasoning_mode, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    reasoning_mode = excluded.reasoning_mode,
                    updated_at = excluded.updated_at
                """,
                (thread_id, reasoning_mode),
            )

    def set_store_to_memory(self, thread_id: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO master_thread_state (thread_id, store_to_memory, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    store_to_memory = excluded.store_to_memory,
                    updated_at = excluded.updated_at
                """,
                (thread_id, int(enabled)),
            )

    def set_pending_reroute(self, thread_id: str, target: str, reason: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO master_thread_state (
                    thread_id,
                    pending_reroute_target,
                    pending_reroute_reason,
                    updated_at
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    pending_reroute_target = excluded.pending_reroute_target,
                    pending_reroute_reason = excluded.pending_reroute_reason,
                    updated_at = excluded.updated_at
                """,
                (thread_id, target, reason),
            )

    def clear_pending_reroute(self, thread_id: str) -> None:
        self.set_pending_reroute(thread_id, "", "")

    def set_pending_action(self, thread_id: str, action: dict[str, Any], *, replace: bool = True) -> bool:
        conflict = (
            "DO UPDATE SET action_json = excluded.action_json, updated_at = excluded.updated_at"
            if replace else "DO NOTHING"
        )
        with self._connect() as conn:
            result = conn.execute(
                f"""
                INSERT INTO master_pending_actions (thread_id, action_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) {conflict}
                """,
                (thread_id, json.dumps(action, ensure_ascii=False)),
            )
        return result.rowcount == 1

    def get_pending_action(self, thread_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT action_json FROM master_pending_actions WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            loaded = json.loads(row["action_json"])
        except json.JSONDecodeError:
            self.clear_pending_action(thread_id)
            return None
        return loaded if isinstance(loaded, dict) else None

    def claim_pending_action(
        self, thread_id: str, *, agent_id: str, user_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT action_json FROM master_pending_actions WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                loaded = json.loads(row["action_json"])
            except json.JSONDecodeError:
                conn.execute("DELETE FROM master_pending_actions WHERE thread_id = ?", (thread_id,))
                return None
            if not isinstance(loaded, dict):
                return None
            if str(loaded.get("agent") or "") != agent_id:
                return None
            if user_id is not None and loaded.get("user_id") != user_id:
                return None
            deleted = conn.execute(
                "DELETE FROM master_pending_actions WHERE thread_id = ?",
                (thread_id,),
            )
            if deleted.rowcount != 1:
                return None
        return loaded

    def clear_pending_action(self, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM master_pending_actions WHERE thread_id = ?", (thread_id,))
