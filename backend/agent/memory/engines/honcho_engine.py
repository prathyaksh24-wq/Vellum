"""Honcho as an embedded engine: its own Python 3.13 runtime, no Docker.

Two processes, supervised in order:

- ``honcho``: the API (health at ``/health``). Before it starts:
  ``alembic upgrade head``, and on first run (or when Vellum's embedding
  model changes) Honcho's ``configure_embeddings.py`` to size its vector
  columns to Vellum's embedding dimensions. Both API and deriver refuse to
  start if the dimensions don't match.
- ``honcho-deriver``: the background worker that turns messages into
  conclusions about the user. It has no HTTP port; it counts as ready once
  it stays up.

Honcho runs from its source tree (pinned commit) with its own environment:

- packaged app: ``resources/engine-runtimes/honcho/{python,src}``
- development:  ``.engines/honcho/src`` + ``.venv`` (``scripts/setup_memory_engines.py``)

``honcho_launcher.py`` applies the Windows fixes (proven in a native
Windows prototype: portrait correct over OpenRouter and Groq).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from agent.memory.engines.llm_routing import honcho_llm_env, memory_engine_llm
from agent.memory.engines.postgres import free_loopback_port
from agent.memory.engines.runtime import EngineContext, engine_dirs, engine_python, register_engine
from agent.memory.engines.supervisor import EngineNotReady, EngineSpec, child_env

API = "honcho"
DERIVER = "honcho-deriver"
COMMIT = "93dcf59c4a4225bb020b20c628799737fefae318"  # same as docker-compose.yml
LAUNCHER = Path(__file__).with_name("honcho_launcher.py")


def honcho_source() -> Path | None:
    explicit = os.environ.get("VELLUM_HONCHO_SOURCE")
    candidates = [Path(explicit)] if explicit else []
    candidates += [home / "src" for home in engine_dirs(API)]
    return next((path for path in candidates if (path / "src" / "main.py").is_file()), None)


def _environment(context: EngineContext) -> tuple[Path, Path, dict[str, str], dict[str, str]]:
    python, source = engine_python(API), honcho_source()
    if python is None or source is None:
        raise EngineNotReady("off", "Honcho isn't installed in this build.")
    llm = memory_engine_llm()
    if not llm.ready:
        raise EngineNotReady("needs_model", llm.reason or "Choose a model for memory.")

    from agent.rag.embedder import get_embedder

    embedder = get_embedder()
    context.postgres.ensure_database("honcho")
    marker = {"dimensions": int(embedder.dimensions), "fingerprint": str(embedder.fingerprint)}
    env = child_env({
        "DB_CONNECTION_URI": context.postgres.uri("honcho", driver="postgresql+psycopg"),
        "AUTH_USE_AUTH": "false",
        "CACHE_ENABLED": "false",           # no Redis
        "METRICS_ENABLED": "false",         # the deriver would bind a fixed :9090
        "TELEMETRY_ENABLED": "false",
        "COLLECT_METRICS_LOCAL": "false",
        "DREAM_ENABLED": "false",
        "EMBEDDING_VECTOR_DIMENSIONS": str(marker["dimensions"]),
        "EMBEDDING_MODEL_CONFIG__TRANSPORT": "openai",
        "EMBEDDING_MODEL_CONFIG__MODEL": "vellum-embedding",
        "EMBEDDING_MODEL_CONFIG__MAX_BATCH_SIZE": "16",
        "EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL": context.embeddings_base_url,
        "EMBEDDING_MODEL_CONFIG__OVERRIDES__API_KEY": "vellum-local",
        # Same deriver pacing as the Docker setup.
        "DERIVER_REPRESENTATION_BATCH_MAX_AGE_SECONDS": os.environ.get("VELLUM_HONCHO_BATCH_MAX_AGE", "300"),
        "DERIVER_REPRESENTATION_BATCH_TARGET_INPUT_TOKENS": "4096",
        "DERIVER_MAX_INPUT_TOKENS": "8000",
        **honcho_llm_env(llm),
    })
    return python, source, env, marker


def build_api_spec(context: EngineContext) -> EngineSpec:
    python, source, env, marker = _environment(context)
    folder = context.engine_dir(API)
    marker_path = folder / "embeddings.json"
    steps = [[str(python), "-m", "alembic", "upgrade", "head"]]
    if _read(marker_path) != marker:
        steps.append([str(python), str(LAUNCHER), "script", "scripts/configure_embeddings.py", "--yes"])
    port = free_loopback_port()
    url = f"http://127.0.0.1:{port}"
    return EngineSpec(
        name=API,
        argv=[str(python), str(LAUNCHER), "api", str(port)],
        env=env,
        cwd=str(source),
        url=url,
        health_url=f"{url}/health",
        log_path=folder / "honcho-api.log",
        before_start=steps,
        on_ready=lambda: marker_path.write_text(json.dumps(marker), encoding="utf-8"),
    )


def build_deriver_spec(context: EngineContext) -> EngineSpec:
    python, source, env, _marker = _environment(context)
    folder = context.engine_dir(API)
    return EngineSpec(
        name=DERIVER,
        argv=[str(python), str(LAUNCHER), "deriver"],
        env=env,
        cwd=str(source),
        health_url="",  # worker: ready once it stays up
        log_path=folder / "honcho-deriver.log",
    )


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


register_engine(API, build_api_spec)
register_engine(DERIVER, build_deriver_spec)
