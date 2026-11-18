"""Create the isolated Python environments the embedded memory engines run in.

Development only: the packaged app ships these under
``resources/engine-runtimes``. Each engine gets its own environment because
its dependencies conflict with Vellum's (e.g. Hindsight needs mcp 2.x).

    uv run python backend/scripts/setup_memory_engines.py            # all engines
    uv run python backend/scripts/setup_memory_engines.py hindsight  # one engine
    uv run python backend/scripts/setup_memory_engines.py embedding-model

``embedding-model`` fetches the EmbeddingGemma 2 copy bundled for installs
without it in Ollama, plus llama.cpp's llama-server that runs it (see
agent/rag/embedding_profile.py). Run it with Vellum's own Python.

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


# EmbeddingGemma 2 for installs without it in Ollama: ggml-org's official
# GGUF (Apache 2.0) and llama.cpp's CPU llama-server (MIT), both pinned by sha256.
GGUF_REPO_REVISION = "6ea3e3a309d12a4779cfda98b8c19800d2d5da71"
GGUF_URL = (f"https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/{GGUF_REPO_REVISION}/"
            "embeddinggemma-2-Q8_0.gguf")
LLAMA_RELEASE = "b12503"
LLAMA_ZIP_URL = (f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE}/"
                 f"llama-{LLAMA_RELEASE}-bin-win-cpu-x64.zip")
LLAMA_ZIP_SHA256 = "64bee9b6fece8e66c665c40290cbb84706af23c670041d024b56a71a39859d77"
LLAMA_LICENSE_URL = f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{LLAMA_RELEASE}/LICENSE"
APACHE_LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0.txt"
# Only what llama-server needs (47 MB of the 63 MB release).
LLAMA_SERVER_FILES = ("llama-server.exe", "llama-server-impl.dll", "llama-common.dll", "llama.dll", "mtmd.dll",
                      "ggml.dll", "ggml-base.dll", "libomp.dll", "LICENSE-LLVM-OpenMP")


def _download(url: str, target: Path, sha256: str | None = None) -> None:
    import hashlib
    import urllib.request

    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as out:  # noqa: S310 - pinned https
        while chunk := response.read(1 << 20):
            digest.update(chunk)
            out.write(chunk)
    if sha256 and digest.hexdigest() != sha256:
        partial.unlink()
        sys.exit(f"Checksum mismatch for {url}; refusing to use it.")
    partial.replace(target)


def setup_embedding_model() -> None:
    """Fetch the bundled EmbeddingGemma 2 GGUF and the llama-server that runs it (Windows x64)."""
    import tempfile
    import zipfile

    sys.path.insert(0, str(REPO / "backend"))
    from agent.rag.embedding_profile import BUNDLED, BUNDLED_DIR, PROFILES
    from agent.rag.embedding_server import SERVER_DIR

    if sys.platform != "win32":
        sys.exit("The bundled embedding server is staged for Windows x64 only.")
    profile = PROFILES[BUNDLED]
    models = REPO / ".engines" / "embedding-models" / BUNDLED_DIR
    models.mkdir(parents=True, exist_ok=True)
    gguf = models / profile["embedding_model"]
    if not gguf.is_file():
        _download(GGUF_URL, gguf, profile["embedding_model_revision"])
    _download(APACHE_LICENSE_URL, models / "LICENSE")
    (models / "NOTICE").write_text(
        "EmbeddingGemma 2 by Google (https://huggingface.co/google/embeddinggemma-2), licensed under the\n"
        "Apache License 2.0 (see LICENSE). Q8_0 GGUF conversion by ggml-org\n"
        f"(https://huggingface.co/ggml-org/embeddinggemma-2-GGUF, revision {GGUF_REPO_REVISION}).\n",
        encoding="utf-8")

    server = REPO / ".engines" / SERVER_DIR
    if server.exists():
        shutil.rmtree(server)
    server.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="vellum-llama-") as work:
        archive = Path(work) / "llama.zip"
        _download(LLAMA_ZIP_URL, archive, LLAMA_ZIP_SHA256)
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.namelist():
                name = Path(member).name
                if name in LLAMA_SERVER_FILES or (name.startswith("ggml-cpu-") and name.endswith(".dll")):
                    (server / name).write_bytes(zipped.read(member))
    _download(LLAMA_LICENSE_URL, server / "LICENSE")
    missing = [name for name in LLAMA_SERVER_FILES if not (server / name).is_file()]
    if missing:
        sys.exit(f"llama.cpp {LLAMA_RELEASE} is missing {', '.join(missing)}")
    print(f"embedding model: ready at {gguf} (server {server})")


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
