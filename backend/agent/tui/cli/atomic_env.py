"""Atomic .env read/write. Never partial-writes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Missing file returns {}."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        result[key.strip()] = value.strip()
    return result


def write_env(path: Path, values: dict[str, str]) -> None:
    """Write the env file atomically. Crashes mid-write leave the original intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".env.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for key, value in values.items():
                f.write(f"{key}={value}\n")
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
