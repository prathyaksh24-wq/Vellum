from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any


class BlueprintSuggestionStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / ".suggestions.json"
        self._lock = RLock()

    def observe(
        self,
        *,
        skill_name: str,
        schedule: str,
        deliver: str,
        prompt: str | None,
        no_agent: bool,
    ) -> dict[str, Any]:
        identifier = self._id(skill_name, schedule)
        with self._lock:
            data = self._read()
            existing = data.get(identifier)
            if existing is not None:
                return dict(existing)
            record = {
                "id": identifier,
                "source": "blueprint",
                "skill_name": skill_name,
                "schedule": schedule,
                "deliver": deliver,
                "prompt": prompt,
                "no_agent": no_agent,
                "state": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            data[identifier] = record
            self._write(data)
            return dict(record)

    def list(self, *, state: str | None = None) -> list[dict[str, Any]]:
        records = [dict(item) for item in self._read().values()]
        if state:
            records = [record for record in records if record.get("state") == state]
        return sorted(records, key=lambda item: str(item.get("created_at") or ""))

    def get(self, identifier: str) -> dict[str, Any]:
        record = self._read().get(identifier)
        if record is None:
            raise ValueError(f"suggestion not found: {identifier}")
        return dict(record)

    def accept(self, identifier: str) -> dict[str, Any]:
        return self._set_state(identifier, "accepted")

    def dismiss(self, identifier: str) -> dict[str, Any]:
        return self._set_state(identifier, "dismissed")

    def _set_state(self, identifier: str, state: str) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            if identifier not in data:
                raise ValueError(f"suggestion not found: {identifier}")
            data[identifier]["state"] = state
            data[identifier]["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write(data)
            return dict(data[identifier])

    @staticmethod
    def _id(skill_name: str, schedule: str) -> str:
        digest = hashlib.sha256(f"{skill_name}\0{schedule}".encode("utf-8")).hexdigest()[:16]
        return f"blueprint-{digest}"

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
