"""On/off switches for skills Vellum does not own.

External and plugin-provided skills live in directories Vellum must not modify,
so they cannot be archived by moving files. Turning one off records its name
here instead; the registry then treats it as unavailable, so the agent does not
load it, and the catalog shows it as off. The skill's files are never touched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

_LOCK = Lock()


class ExternalSkillSwitches:
    def __init__(self, root: str | Path):
        self.path = Path(root) / "external-disabled.json"

    def disabled(self) -> set[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        names = data.get("disabled") if isinstance(data, dict) else None
        return {str(name) for name in names if isinstance(name, str)} if isinstance(names, list) else set()

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Record the switch; returns the resulting enabled state."""
        with _LOCK:
            names = self.disabled()
            if enabled:
                names.discard(name)
            else:
                names.add(name)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
            temporary.write_text(json.dumps({"disabled": sorted(names)}, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        return enabled
