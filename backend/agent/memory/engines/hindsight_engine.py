"""Hindsight as an embedded engine: its own runtime, Vellum's database and embeddings.

Hindsight's packages conflict with Vellum's (mcp 2.x, an older transformers),
so it runs from its own Python environment as a child process:

- packaged app: ``resources/engine-runtimes/hindsight/python/python.exe``
- development:  ``<repo>/.engines/hindsight/.venv`` (``scripts/setup_memory_engines.py``)

It uses the slim server (``hindsight-api-slim[embedded-db]`` plus
``flashrank``), so there is no PyTorch: embeddings come from Vellum's
``/api/v1/embeddings`` route and reranking uses flashrank (ONNX). Verified
end to end on Windows: ready in about 12 s, retain about 6 s, recall about
0.1 s, forget removes the document.
"""
from __future__ import annotations

import sys
from pathlib import Path

from agent.memory.engines.llm_routing import hindsight_llm_env, memory_engine_llm
from agent.memory.engines.postgres import free_loopback_port
from agent.memory.engines.runtime import EngineContext, register_engine
from agent.memory.engines.supervisor import EngineNotReady, EngineSpec, child_env

ENGINE = "hindsight"
PACKAGES = ("hindsight-api-slim[embedded-db]==1.2.1", "flashrank")


def engine_python(name: str) -> Path | None:
    """Locate an engine's own Python, packaged or development."""
    import os

    from agent.config import REPO_ROOT

    explicit = os.environ.get(f"VELLUM_{name.upper()}_PYTHON")
    candidates = [Path(explicit)] if explicit else []
    # Packaged: <resources>/backend-runtime/python/python.exe -> <resources>/engine-runtimes/<name>
    resources = Path(sys.executable).resolve().parents[2]
    candidates.append(resources / "engine-runtimes" / name / "python" / "python.exe")
    candidates.append(Path(REPO_ROOT) / ".engines" / name / ".venv" / "Scripts" / "python.exe")
    candidates.append(Path(REPO_ROOT) / ".engines" / name / ".venv" / "bin" / "python")
    return next((path for path in candidates if path.is_file()), None)


def build_spec(context: EngineContext) -> EngineSpec:
    python = engine_python(ENGINE)
    if python is None:
        raise EngineNotReady("off", "Hindsight isn't installed in this build.")
    llm = memory_engine_llm()
    if not llm.ready:
        raise EngineNotReady("needs_model", llm.reason or "Choose a model for memory.")

    from agent.rag.embedder import get_embedder

    database_url = context.postgres.ensure_database("hindsight")
    port = free_loopback_port()
    folder = context.engine_dir(ENGINE)
    env = child_env({
        "HINDSIGHT_API_HOST": "127.0.0.1",
        "HINDSIGHT_API_PORT": str(port),
        "HINDSIGHT_API_DATABASE_URL": database_url,
        "HINDSIGHT_API_WORKER_ID": "vellum",
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "openai",
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY": "vellum-local",
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL": context.embeddings_base_url,
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL": "vellum-embedding",
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS": str(get_embedder().dimensions),
        "HINDSIGHT_API_RERANKER_PROVIDER": "flashrank",
        "HF_HOME": str(folder / "models"),
        **hindsight_llm_env(llm),
    })
    url = f"http://127.0.0.1:{port}"
    return EngineSpec(
        name=ENGINE,
        argv=[str(python), "-c", "from hindsight_api.main import main; main()"],
        env=env,
        cwd=str(folder),
        url=url,
        health_url=f"{url}/health",
        log_path=folder / "hindsight.log",
    )


register_engine(ENGINE, build_spec)
