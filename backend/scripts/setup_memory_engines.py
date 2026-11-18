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
HONCHO_REPO = "https://github.com/plastic-labs/honcho.git"
HONCHO_COMMIT = "93dcf59c4a4225bb020b20c628799737fefae318"  # same as docker-compose.yml
ENGINES = {
    "hindsight": {"python": "3.12", "packages": ["hindsight-api-slim[embedded-db]==1.2.1", "flashrank"]},
    "honcho": {"python": "3.13", "source": (HONCHO_REPO, HONCHO_COMMIT)},
}


def setup_source(name: str, uv: str) -> None:
    """Honcho is not a pip package: fetch the pinned commit and sync its lockfile."""
    repo, commit = ENGINES[name]["source"]
    src = REPO / ".engines" / name / "src"
    git = shutil.which("git")
    if git is None:
        sys.exit("git is required to fetch Honcho")
    if not (src / ".git").exists():
        src.mkdir(parents=True, exist_ok=True)
        subprocess.run([git, "init", "-q"], cwd=src, check=True)
        subprocess.run([git, "remote", "add", "origin", repo], cwd=src, check=True)
    subprocess.run([git, "fetch", "-q", "--depth", "1", "origin", commit], cwd=src, check=True)
    subprocess.run([git, "checkout", "-q", "--force", commit], cwd=src, check=True)
    subprocess.run([uv, "python", "install", ENGINES[name]["python"]], check=True)
    subprocess.run([uv, "sync", "--frozen", "--python", ENGINES[name]["python"], "--no-dev"], cwd=src, check=True)
    print(f"{name}: ready at {src / '.venv'}")


def setup(name: str) -> None:
    spec = ENGINES[name]
    if "source" in spec:
        uv = shutil.which("uv")
        if uv is None:
            sys.exit("uv is required: https://docs.astral.sh/uv/")
        setup_source(name, uv)
        return
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
