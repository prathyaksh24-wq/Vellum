from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable


_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock_for(path: Path) -> RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, RLock())


def _default_record() -> dict[str, Any]:
    return {
        "view_count": 0,
        "use_count": 0,
        "patch_count": 0,
        "last_viewed_at": None,
        "last_used_at": None,
        "last_patched_at": None,
        "created_at": None,
        "created_by": None,
        "state": "active",
        "pinned": False,
        "archived_at": None,
    }


class SkillUsageStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / ".usage.json"
        self._lock = _lock_for(self.path)

    def all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return self._read()

    def get(self, name: str) -> dict[str, Any]:
        return dict(self.all().get(name, _default_record()))

    def mark_created(self, name: str, *, origin: str) -> None:
        def mutate(record: dict[str, Any]) -> None:
            record["created_at"] = record.get("created_at") or _now()
            record["created_by"] = "agent" if origin == "background_review" else None
            record["state"] = "active"
            record["archived_at"] = None

        self._update(name, mutate)

    def increment_view(self, name: str) -> None:
        self._increment(name, "view_count", "last_viewed_at")

    def increment_use(self, name: str) -> None:
        self._increment(name, "use_count", "last_used_at")

    def increment_patch(self, name: str) -> None:
        self._increment(name, "patch_count", "last_patched_at")

    def set_state(self, name: str, state: str) -> None:
        def mutate(record: dict[str, Any]) -> None:
            record["state"] = state
            record["archived_at"] = _now() if state == "archived" else None

        self._update(name, mutate)

    def pin(self, name: str) -> None:
        self._update(name, lambda record: record.__setitem__("pinned", True))

    def unpin(self, name: str) -> None:
        self._update(name, lambda record: record.__setitem__("pinned", False))

    def remove(self, name: str) -> None:
        with self._lock:
            data = self._read()
            data.pop(name, None)
            self._write(data)

    def _increment(self, name: str, counter: str, timestamp: str) -> None:
        def mutate(record: dict[str, Any]) -> None:
            record[counter] = int(record.get(counter) or 0) + 1
            record[timestamp] = _now()

        self._update(name, mutate)

    def _update(self, name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            data = self._read()
            record = {**_default_record(), **data.get(name, {})}
            mutate(record)
            data[name] = record
            self._write(data)

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
