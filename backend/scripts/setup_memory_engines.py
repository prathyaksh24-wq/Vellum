"""Create the isolated Python environments the embedded memory engines run in.

Development only: the packaged app ships these under
``resources/engine-runtimes``. Each engine gets its own environment because
its dependencies conflict with Vellum's (e.g. Hindsight needs mcp 2.x).

    uv run python backend/scripts/setup_memory_engines.py            # all engines
    uv run python backend/scripts/setup_memory_engines.py hindsight  # one engine

Requires ``uv`` on PATH.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINES = {
    "hindsight": {"python": "3.12", "packages": ["hindsight-api-slim[embedded-db]==1.2.1", "flashrank"]},
}


def setup(name: str) -> None:
    spec = ENGINES[name]
    venv = REPO / ".engines" / name / ".venv"
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("uv is required: https://docs.astral.sh/uv/")
    if not venv.exists():
        subprocess.run([uv, "venv", str(venv), "--python", spec["python"]], check=True)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([uv, "pip", "install", "--python", str(python), *spec["packages"]], check=True)
    print(f"{name}: ready at {python}")


if __name__ == "__main__":
    for engine in sys.argv[1:] or list(ENGINES):
        setup(engine)
