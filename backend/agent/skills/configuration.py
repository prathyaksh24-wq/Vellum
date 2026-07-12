from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
from typing import Any

import yaml

from agent.skills.models import SkillPackage


_MISSING = object()


class SkillConfigStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            value = self._lookup(self._read(), key)
            return default if value is _MISSING else value

    def set(self, key: str, value: Any) -> None:
        parts = self._parts(key)
        with self._lock:
            data = self._read()
            cursor = data.setdefault("skills", {}).setdefault("config", {})
            for part in parts[:-1]:
                next_value = cursor.setdefault(part, {})
                if not isinstance(next_value, dict):
                    raise ValueError(f"config key conflicts with scalar value: {key}")
                cursor = next_value
            cursor[parts[-1]] = value
            self._write(data)

    def get_option(self, key: str, default: Any = None) -> Any:
        """Read an option directly below the top-level ``skills`` mapping."""
        with self._lock:
            cursor: Any = self._read().get("skills", {})
            for part in self._parts(key):
                if not isinstance(cursor, dict) or part not in cursor:
                    return default
                cursor = cursor[part]
            return cursor

    def set_option(self, key: str, value: Any) -> None:
        """Persist an option directly below the top-level ``skills`` mapping."""
        parts = self._parts(key)
        with self._lock:
            data = self._read()
            cursor = data.setdefault("skills", {})
            for part in parts[:-1]:
                next_value = cursor.setdefault(part, {})
                if not isinstance(next_value, dict):
                    raise ValueError(f"config key conflicts with scalar value: {key}")
                cursor = next_value
            cursor[parts[-1]] = value
            self._write(data)

    def resolve(self, package: SkillPackage) -> dict[str, Any]:
        values: dict[str, Any] = {}
        missing: list[str] = []
        data = self._read()
        for setting in package.metadata.metadata.hermes.config:
            value = self._lookup(data, setting.key)
            if value is _MISSING:
                if setting.default is None:
                    missing.append(setting.key)
                    continue
                value = setting.default
            values[setting.key] = value
        return {"values": values, "missing": missing}

    def _lookup(self, data: dict[str, Any], key: str) -> Any:
        cursor: Any = data.get("skills", {}).get("config", {})
        for part in self._parts(key):
            if not isinstance(cursor, dict) or part not in cursor:
                return _MISSING
            cursor = cursor[part]
        return cursor

    @staticmethod
    def _parts(key: str) -> list[str]:
        parts = [part.strip() for part in key.split(".") if part.strip()]
        if not parts:
            raise ValueError("config key is required")
        return parts

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        loaded = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("skill config must be a YAML mapping")
        return loaded

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.replace(temporary, self.path)
