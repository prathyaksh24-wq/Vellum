"""User-owned automation store.

Persists automations and their bounded run history to a JSON file with
atomic writes (temp file + rename), following the conventions of
``agent.skills.suggestions.BlueprintSuggestionStore``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Literal

MAX_RUN_HISTORY = 100

AutomationState = Literal["active", "paused"]
RunStatus = Literal["running", "complete", "failed"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutomationStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / "automations.json"
        self._lock = RLock()

    def create(
        self,
        *,
        name: str,
        description: str = "",
        instructions: str,
        schedule: dict[str, Any],
        destination: dict[str, Any],
        project_id: str | None = None,
        model_profile: dict[str, Any] | None = None,
        permission: dict[str, Any] | None = None,
        notifications: dict[str, Any] | None = None,
        builtin: bool = False,
        builtin_key: str | None = None,
        state: str = "active",
    ) -> dict[str, Any]:
        automation_id = self._new_id(name)
        now = utc_now()
        record: dict[str, Any] = {
            "id": automation_id,
            "name": name,
            "description": description,
            "instructions": instructions,
            "schedule": dict(schedule),
            "destination": dict(destination),
            "project_id": project_id,
            "model_profile": dict(model_profile) if model_profile else {},
            "permission": dict(permission) if permission else {"full_access": False},
            "notifications": dict(notifications) if notifications else {"level": "all"},
            "state": state,
            "builtin": bool(builtin),
            "created_at": now,
            "updated_at": now,
            "run_history": [],
        }
        if builtin_key is not None:
            record["builtin_key"] = builtin_key
        with self._lock:
            data = self._read()
            data[automation_id] = record
            self._write(data)
        return dict(record)

    def list(self, *, state: str | None = None) -> list[dict[str, Any]]:
        records = [dict(item) for item in self._read().values()]
        if state:
            records = [record for record in records if record.get("state") == state]
        return sorted(records, key=lambda item: str(item.get("created_at") or ""))

    def get(self, automation_id: str) -> dict[str, Any]:
        record = self._read().get(automation_id)
        if record is None:
            raise ValueError(f"automation not found: {automation_id}")
        return dict(record)

    def update(self, automation_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "name",
            "description",
            "instructions",
            "schedule",
            "destination",
            "project_id",
            "model_profile",
            "permission",
            "notifications",
            "state",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot update fields: {sorted(unknown)}")
        if fields.get("state") not in (None, "active", "paused"):
            raise ValueError(f"invalid state: {fields.get('state')!r}")
        with self._lock:
            data = self._read()
            if automation_id not in data:
                raise ValueError(f"automation not found: {automation_id}")
            record = data[automation_id]
            for key, value in fields.items():
                record[key] = dict(value) if isinstance(value, dict) else value
            record["updated_at"] = utc_now()
            self._write(data)
        return dict(data[automation_id])

    def remove(self, automation_id: str) -> None:
        with self._lock:
            data = self._read()
            if automation_id not in data:
                raise ValueError(f"automation not found: {automation_id}")
            del data[automation_id]
            self._write(data)

    def record_run(self, automation_id: str, run_id: str) -> dict[str, Any]:
        run: dict[str, Any] = {
            "id": run_id,
            "started_at": utc_now(),
            "finished_at": None,
            "status": "running",
            "output": None,
            "error": None,
        }
        with self._lock:
            data = self._read()
            if automation_id not in data:
                raise ValueError(f"automation not found: {automation_id}")
            history = data[automation_id].setdefault("run_history", [])
            history.append(run)
            data[automation_id]["run_history"] = self._prune(history)
            data[automation_id]["updated_at"] = utc_now()
            self._write(data)
        return dict(run)

    def finish_run(
        self,
        automation_id: str,
        run_id: str,
        *,
        status: RunStatus,
        output: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            if automation_id not in data:
                raise ValueError(f"automation not found: {automation_id}")
            history = data[automation_id].setdefault("run_history", [])
            for run in history:
                if run.get("id") == run_id:
                    run["status"] = status
                    run["finished_at"] = utc_now()
                    if output is not None:
                        run["output"] = output
                    if error is not None:
                        run["error"] = error
                    data[automation_id]["run_history"] = self._prune(history)
                    data[automation_id]["updated_at"] = utc_now()
                    self._write(data)
                    return dict(run)
        raise ValueError(f"run not found: {run_id}")

    def runs(self, automation_id: str) -> list[dict[str, Any]]:
        record = self.get(automation_id)
        return [dict(run) for run in record.get("run_history", [])]

    @staticmethod
    def _new_id(name: str) -> str:
        digest = hashlib.sha256(f"{name}\0{utc_now()}".encode("utf-8")).hexdigest()[:16]
        return f"automation-{digest}"

    @staticmethod
    def _prune(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return history[-MAX_RUN_HISTORY:]

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            corrupted = self.path.with_suffix(".json.corrupt")
            try:
                os.replace(self.path, corrupted)
            except OSError:
                pass
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
