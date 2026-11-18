"""Stage the memory engines' own Python runtimes for Forge (publisher-side only).

Each engine runs from its own environment because its dependencies conflict
with the backend's. This copies, per engine, a relocatable Windows Python
(the base interpreter of the engine's development venv) plus that venv's
site-packages into ``desktop/resources/engine-runtimes/<engine>/python``.
Honcho also needs its source tree (``.../honcho/src``), copied without
docs, tests, SDKs or git history. The embedding model bundled for users
without Ollama goes to ``engine-runtimes/embedding-models``.

Prepare the development environments first:

    python backend/scripts/setup_memory_engines.py

Nothing here reads .env or copies user data.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "desktop" / "resources"
DESTINATION = PARENT / "engine-runtimes"

ENGINES = {
    # Lazily imported provider SDKs Vellum never configures (Claude-Code-style and LiteLLM providers).
    "hindsight": {"venv": ROOT / ".engines/hindsight/.venv", "strip": ("claude_agent_sdk", "litellm")},
    "honcho": {"venv": ROOT / ".engines/honcho/src/.venv", "source": ROOT / ".engines/honcho/src", "strip": ()},
}
EMBEDDING_MODELS = ROOT / ".engines" / "embedding-models"
SOURCE_SKIP = {".git", ".venv", "docs", "tests", "sdks", "honcho-cli", ".github", "examples", "__pycache__"}


def base_prefix(venv: Path) -> Path:
    for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            return Path(value.strip())
    raise RuntimeError(f"{venv} has no base interpreter in pyvenv.cfg")


def skip(strip: tuple[str, ...]):
    def ignore(_directory, names):
        return {name for name in names if name in {"__pycache__", "tests", "test"}
                or name.endswith((".pyc", ".pyo"))
                # Keep ordinary .pth files (pywin32.pth registers win32 paths, relative so
                # relocatable); drop the venv-only and editable-install ones.
                or name.startswith(("__editable__", "_virtualenv"))
                or any(name == pkg or name.startswith(f"{pkg}-") for pkg in strip)}
    return ignore


def stage_python(venv: Path, target: Path, strip: tuple[str, ...]) -> None:
    base = base_prefix(venv)
    target.mkdir(parents=True)
    for file in base.iterdir():
        if file.is_file() and (file.suffix.lower() in {".exe", ".dll", ".zip"} or file.name.startswith("LICENSE")):
            shutil.copy2(file, target / file.name)
    for directory in ("DLLs", "Lib"):
        source = base / directory
        if source.is_dir():
            def base_ignore(directory_path, names, _source=source):
                skipped = skip(())(directory_path, names)
                if Path(directory_path) == _source and directory == "Lib":
                    skipped.add("site-packages")
                return skipped
            shutil.copytree(source, target / directory, ignore=base_ignore)
    shutil.copytree(venv / "Lib" / "site-packages", target / "Lib" / "site-packages", ignore=skip(strip))


def build() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Engine runtimes are staged for Windows x64 releases only.")
    missing = [name for name, spec in ENGINES.items() if not (spec["venv"] / "pyvenv.cfg").is_file()]
    if not any(EMBEDDING_MODELS.glob("*/modules.json")):
        missing.append("embedding-model")
    if missing:
        raise RuntimeError("Set up the engines first (python backend/scripts/setup_memory_engines.py): "
                           + ", ".join(missing))
    PARENT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="engines-staging-", dir=PARENT))
    try:
        for name, spec in ENGINES.items():
            stage_python(spec["venv"], staging / name / "python", spec["strip"])
            if "source" in spec:
                shutil.copytree(spec["source"], staging / name / "src",
                                ignore=lambda _d, names: {n for n in names if n in SOURCE_SKIP or n.endswith(".pyc")})
            size = sum(p.stat().st_size for p in (staging / name).rglob("*") if p.is_file())
            print(f"{name}: {size / 1024**3:.2f} GiB")
        shutil.copytree(EMBEDDING_MODELS, staging / "embedding-models")
        size = sum(p.stat().st_size for p in (staging / "embedding-models").rglob("*") if p.is_file())
        print(f"embedding models: {size / 1024**3:.2f} GiB")
        if DESTINATION.exists():
            if not DESTINATION.resolve().is_relative_to(PARENT.resolve()):
                raise RuntimeError("Refusing to remove a path outside desktop/resources.")
            shutil.rmtree(DESTINATION)
        staging.rename(DESTINATION)
        total = sum(p.stat().st_size for p in DESTINATION.rglob("*") if p.is_file())
        print(f"Staged memory engines ({total / 1024**3:.2f} GiB) at {DESTINATION}.")
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    build()
