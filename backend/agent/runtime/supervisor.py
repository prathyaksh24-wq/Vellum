from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable
from uuid import uuid4


TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "timed_out"})


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    run_id: str
    parent_task_id: str | None
    agent_name: str
    department: str
    state: str
    deadline: str | None
    iterations: int
    heartbeat_at: str | None
    exit_reason: str | None
    result: Any = None


class IterationBudgetExceeded(RuntimeError):
    pass


class TaskControl:
    def __init__(self, supervisor: "AgentSupervisor", task_id: str, cancellation: threading.Event, max_iterations: int) -> None:
        self._supervisor = supervisor
        self.task_id = task_id
        self._cancellation = cancellation
        self.max_iterations = max_iterations

    @property
    def cancelled(self) -> bool:
        return self._cancellation.is_set()

    def heartbeat(self) -> None:
        self._supervisor.wait_if_paused(self.task_id)
        self._supervisor._heartbeat(self.task_id)

    def operation(self, kind: str) -> int:
        self._supervisor.wait_if_paused(self.task_id)
        if kind not in {"model", "tool"}:
            raise ValueError("only completed model and tool operations count as iterations")
        count = self._supervisor._increment(self.task_id)
        if count > self.max_iterations:
            self._cancellation.set()
            raise IterationBudgetExceeded("iteration budget exceeded")
        return count

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError("task cancelled")


class AgentSupervisor:
    def __init__(self, db_path: str | Path, *, monitor_interval: float = 0.1, stale_heartbeat_seconds: float = 30.0) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.monitor_interval = monitor_interval
        self.stale_heartbeat_seconds = stale_heartbeat_seconds
        self._lock = threading.RLock()
        self._cancellations: dict[str, threading.Event] = {}
        self._pauses: dict[str, threading.Event] = {}
        self._results: dict[str, Any] = {}
        self._initialize()
        threading.Thread(target=self._monitor, daemon=True, name="vellum-agent-supervisor").start()

    def submit(
        self,
        *,
        run_id: str,
        agent_name: str,
        department: str,
        work: Callable[[TaskControl], Any],
        parent_task_id: str | None = None,
        task_id: str | None = None,
        timeout_seconds: float = 0,
        max_iterations: int = 30,
    ) -> str:
        identifier = task_id or str(uuid4())
        now = _now()
        deadline = now + timedelta(seconds=timeout_seconds) if timeout_seconds > 0 else None
        event = threading.Event()
        with self._lock, self._connection() as conn:
            conn.execute(
                """INSERT INTO agent_tasks
                   (task_id, run_id, parent_task_id, agent_name, department, state,
                    deadline, iterations, heartbeat_at, exit_reason, result_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, run_id, parent_task_id, agent_name, department, "queued", deadline.isoformat() if deadline else None, 0, now.isoformat(), None, None, now.isoformat()),
            )
            self._cancellations[identifier] = event
            pause = threading.Event()
            pause.set()
            self._pauses[identifier] = pause
        threading.Thread(
            target=self._run,
            args=(identifier, work, event, max_iterations),
            daemon=True,
            name=f"vellum-task-{identifier[:8]}",
        ).start()
        return identifier

    def status(self, task_id: str) -> TaskRecord:
        with self._lock, self._connection() as conn:
            row = conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        data = dict(row)
        result = self._results.get(task_id)
        if result is None and data["result_json"]:
            result = json.loads(data["result_json"])
        return TaskRecord(
            task_id=data["task_id"], run_id=data["run_id"], parent_task_id=data["parent_task_id"],
            agent_name=data["agent_name"], department=data["department"], state=data["state"],
            deadline=data["deadline"], iterations=data["iterations"], heartbeat_at=data["heartbeat_at"],
            exit_reason=data["exit_reason"], result=result,
        )

    def wait(self, task_id: str, timeout: float | None = None) -> TaskRecord:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            record = self.status(task_id)
            if record.state in TERMINAL_STATES:
                return record
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"task {task_id} did not complete")
            time.sleep(min(self.monitor_interval, 0.05))

    def cancel(self, task_id: str, *, recursive: bool = True) -> None:
        targets = [task_id]
        if recursive:
            targets.extend(self._descendants(task_id))
        for identifier in targets:
            event = self._cancellations.get(identifier)
            if event is not None:
                event.set()
            self._set_terminal(identifier, "cancelled", "cancelled_by_supervisor")

    def pause(self, task_id: str) -> TaskRecord:
        record = self.status(task_id)
        if record.state != "running":
            raise RuntimeError("task cannot be paused")
        self._pauses[task_id].clear()
        self._set_state(task_id, "paused")
        return self.status(task_id)

    def resume(self, task_id: str) -> TaskRecord:
        record = self.status(task_id)
        if record.state != "paused":
            raise RuntimeError("task cannot be resumed")
        self._pauses[task_id].set()
        self._set_state(task_id, "running")
        self._heartbeat(task_id)
        return self.status(task_id)

    def wait_if_paused(self, task_id: str) -> None:
        pause = self._pauses.get(task_id)
        cancellation = self._cancellations.get(task_id)
        while pause is not None and not pause.wait(timeout=self.monitor_interval):
            if cancellation is not None and cancellation.is_set():
                return

    def list_tasks(self, *, run_id: str | None = None) -> list[TaskRecord]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT task_id FROM agent_tasks" + (" WHERE run_id = ?" if run_id else "") + " ORDER BY created_at, task_id",
                (run_id,) if run_id else (),
            ).fetchall()
        return [self.status(row["task_id"]) for row in rows]

    def _run(self, task_id: str, work: Callable[[TaskControl], Any], event: threading.Event, max_iterations: int) -> None:
        self._set_state(task_id, "starting")
        if event.is_set():
            return
        self._set_state(task_id, "running")
        control = TaskControl(self, task_id, event, max_iterations)
        control.heartbeat()
        try:
            result = work(control)
            current = self.status(task_id)
            if current.state in TERMINAL_STATES:
                return
            if event.is_set():
                self._set_terminal(task_id, "cancelled", "cancelled")
                return
            self._results[task_id] = result
            self._set_terminal(task_id, "completed", None, result=result)
        except Exception as exc:
            current = self.status(task_id)
            if current.state not in TERMINAL_STATES:
                self._set_terminal(task_id, "failed", exc.__class__.__name__)

    def _monitor(self) -> None:
        while True:
            now = _now()
            for record in self.list_tasks():
                if record.state != "running":
                    continue
                if record.deadline and datetime.fromisoformat(record.deadline) <= now:
                    event = self._cancellations.get(record.task_id)
                    if event:
                        event.set()
                    self._set_terminal(record.task_id, "timed_out", "deadline_exceeded")
                    continue
                if record.heartbeat_at and self.stale_heartbeat_seconds > 0:
                    age = (now - datetime.fromisoformat(record.heartbeat_at)).total_seconds()
                    if age > self.stale_heartbeat_seconds:
                        event = self._cancellations.get(record.task_id)
                        if event:
                            event.set()
                        self._set_terminal(record.task_id, "failed", "heartbeat_stale")
            time.sleep(self.monitor_interval)

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, parent_task_id TEXT,
                    agent_name TEXT NOT NULL, department TEXT NOT NULL, state TEXT NOT NULL,
                    deadline TEXT, iterations INTEGER NOT NULL, heartbeat_at TEXT,
                    exit_reason TEXT, result_json TEXT, created_at TEXT NOT NULL
                )
                """
            )

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _set_state(self, task_id: str, state: str) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("UPDATE agent_tasks SET state = ? WHERE task_id = ? AND state NOT IN ('completed','failed','cancelled','timed_out')", (state, task_id))
            conn.commit()

    def _set_terminal(self, task_id: str, state: str, reason: str | None, *, result: Any = None) -> None:
        encoded = json.dumps(result, default=str) if result is not None else None
        with self._lock, self._connection() as conn:
            conn.execute(
                "UPDATE agent_tasks SET state = ?, exit_reason = ?, result_json = COALESCE(?, result_json) WHERE task_id = ? AND state NOT IN ('completed','failed','cancelled','timed_out')",
                (state, reason, encoded, task_id),
            )
            conn.commit()

    def _heartbeat(self, task_id: str) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("UPDATE agent_tasks SET heartbeat_at = ? WHERE task_id = ?", (_now().isoformat(), task_id))
            conn.commit()

    def _increment(self, task_id: str) -> int:
        with self._lock, self._connection() as conn:
            conn.execute("UPDATE agent_tasks SET iterations = iterations + 1 WHERE task_id = ?", (task_id,))
            row = conn.execute("SELECT iterations FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
            conn.commit()
        return int(row["iterations"])

    def _descendants(self, task_id: str) -> list[str]:
        found: list[str] = []
        frontier = [task_id]
        with self._lock, self._connection() as conn:
            while frontier:
                parent = frontier.pop()
                rows = conn.execute("SELECT task_id FROM agent_tasks WHERE parent_task_id = ?", (parent,)).fetchall()
                children = [row["task_id"] for row in rows]
                found.extend(children)
                frontier.extend(children)
        return found


def _now() -> datetime:
    return datetime.now(UTC)
