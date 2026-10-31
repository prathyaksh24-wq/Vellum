"""User-owned automation store.

Persists automations and their bounded run history to a JSON file with
atomic writes (temp file + rename), following the conventions of
``agent.skills.suggestions.BlueprintSuggestionStore``.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import time
from pathlib import Path
from threading import RLock
from typing import Any, Literal

MAX_RUN_HISTORY = 100
MAX_NOTIFICATION_HISTORY = 200
NOTIFICATION_RECENT_HOURS = 24
_STORE_LOCKS: dict[str, RLock] = {}
_STORE_LOCKS_GUARD = RLock()

AutomationState = Literal["active", "paused"]
RunStatus = Literal["running", "complete", "failed"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutomationStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / "automations.json"
        with _STORE_LOCKS_GUARD:
            self._lock = _STORE_LOCKS.setdefault(str(self.path.resolve()).casefold(), RLock())

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
        with self._lock:
            records = [dict(item) for item in self._read().values()]
        if state:
            records = [record for record in records if record.get("state") == state]
        return sorted(records, key=lambda item: str(item.get("created_at") or ""))

    def get(self, automation_id: str) -> dict[str, Any]:
        with self._lock:
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

    def deliver_notification(self, automation_id: str, delivery_id: str, message: str,
                             *, title: str = "", url: str = "", read_at: str | None = None,
                             created_at: str | None = None) -> bool:
        """Persist once before the creator outbox is acknowledged; create no chat."""
        with self._lock:
            data = self._read()
            record = data.get(automation_id)
            if record is None:
                raise ValueError(f"automation not found: {automation_id}")
            if (record.get("notifications") or {}).get("level", "all") in {"none", "failures"}:
                return False
            history = record.setdefault("notification_history", [])
            if any(item.get("id") == delivery_id for item in history):
                return False
            history.append({"id": delivery_id, "automation_id": automation_id,
                "title": (title or record["name"])[:200], "message": message[:10000],
                "url": url, "created_at": created_at or utc_now(), "read_at": read_at})
            record["notification_history"] = history[-MAX_NOTIFICATION_HISTORY:]
            self._write(data)
            return True

    @staticmethod
    def _notification_recent(item: dict[str, Any], now: datetime) -> bool:
        try:
            created = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
            return created.tzinfo is not None and now-timedelta(hours=NOTIFICATION_RECENT_HOURS) <= created <= now
        except (KeyError, ValueError, TypeError):
            return False

    def notification_snapshot(self, *, limit: int = 200, view: str = 'all', offset: int = 0,
                              query: str = '', builtin_key: str = '') -> dict[str, Any]:
        if view not in {'all', 'recent', 'history'}:
            raise ValueError('Unknown notification view')
        now = datetime.now(timezone.utc)
        with self._lock:
            items = [dict(item) for record in self._read().values()
                     if not builtin_key or record.get('builtin_key') == builtin_key
                     for item in record.get("notification_history", [])]
        items.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
        recent = [item for item in items if not item.get('read_at') and self._notification_recent(item, now)]
        selected = recent if view == 'recent' else items
        term = query.strip().casefold()[:200]
        if term:
            selected = [item for item in selected if term in (item.get('title','')+' '+item.get('message','')).casefold()]
        start, size = max(0, min(offset, 10000)), max(1, min(limit, 200))
        return {"items": selected[start:start+size],
                "unread_count": sum(not item.get("read_at") for item in items),
                'recent_unread_count': len(recent), 'total_count': len(items), 'matched_count': len(selected),
                'offset': start, 'has_more': start+size < len(selected),
                'recent_hours': NOTIFICATION_RECENT_HOURS, 'retention_per_automation': MAX_NOTIFICATION_HISTORY}

    def mark_notifications_read(self, ids: list[str], *, all_items: bool = False, recent_only: bool = False) -> int:
        changed = 0
        now = utc_now()
        with self._lock:
            data = self._read()
            for record in data.values():
                for item in record.get("notification_history", []):
                    if not item.get("read_at") and (all_items or item["id"] in ids or
                            recent_only and self._notification_recent(item, datetime.fromisoformat(now))):
                        item["read_at"] = now
                        changed += 1
            if changed:
                self._write(data)
        return changed

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
        # Windows scanners/readers can briefly hold a sharing lock. Preserve
        # the old valid file and retry the atomic replacement, never truncate it.
        for attempt in range(5):
            try:
                os.replace(temporary, self.path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.025 * 2**attempt)
