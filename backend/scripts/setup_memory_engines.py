"""Create the isolated Python environments the embedded memory engines run in.

Development only: the packaged app ships these under
``resources/engine-runtimes``. Each engine gets its own environment because
its dependencies conflict with Vellum's (e.g. Hindsight needs mcp 2.x).

    uv run python backend/scripts/setup_memory_engines.py            # all engines
    uv run python backend/scripts/setup_memory_engines.py hindsight  # one engine
    uv run python backend/scripts/setup_memory_engines.py embedding-model

``embedding-model`` prepares the embedding model bundled for users without
Ollama (see agent/rag/embedding_profile.py). Run it with Vellum's own Python;
it needs sentence-transformers.

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


def setup_embedding_model() -> None:
    """Download the pinned bundled embedding model and store it as fp16 (vectors are unchanged)."""
    import tempfile

    sys.path.insert(0, str(REPO / "backend"))
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer

    from agent.rag.embedding_profile import BUNDLED, BUNDLED_DIR, PROFILES

    profile = PROFILES[BUNDLED]
    target = REPO / ".engines" / "embedding-models" / BUNDLED_DIR
    with tempfile.TemporaryDirectory(prefix="vellum-embed-") as cache:
        folder = snapshot_download(profile["embedding_model"], revision=profile["embedding_model_revision"],
                                   cache_dir=cache, allow_patterns=["*.json", "model.safetensors",
                                                                     "sentencepiece.bpe.model", "1_Pooling/*",
                                                                     "README.md"])
        model = SentenceTransformer(folder, device="cpu")
        if model.get_embedding_dimension() != profile["embedding_dimensions"]:
            sys.exit("The bundled embedding model has unexpected dimensions.")
        if target.exists():
            shutil.rmtree(target)
        model.half().save(str(target))
    print(f"embedding model: ready at {target}")


def setup(name: str) -> None:
    if name == "embedding-model":
        setup_embedding_model()
        return
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
    for engine in sys.argv[1:] or [*ENGINES, "embedding-model"]:
        setup(engine)
