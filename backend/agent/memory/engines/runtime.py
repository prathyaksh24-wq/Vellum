"""The process-wide memory engine supervisor.

Engines register here (``register_engine``); the backend lifespan calls
``start_engines`` once serving and ``stop_engines`` on shutdown. The shared
Postgres starts only when at least one engine is registered.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.memory.engines.postgres import EnginePostgres
from agent.memory.engines.supervisor import EngineSpec, EngineSupervisor

logger = logging.getLogger(__name__)
_REGISTRY: list[tuple[str, Callable[["EngineContext"], EngineSpec]]] = []
_REGISTRY_LOCK = threading.Lock()


class EngineContext:
    """What an engine factory needs: workspace paths, the database, the API base."""

    def __init__(self, root: Path, postgres: EnginePostgres, api_base: str) -> None:
        self.root = root
        self.postgres = postgres
        self.api_base = api_base.rstrip("/")

    @property
    def embeddings_base_url(self) -> str:
        return f"{self.api_base}/api/v1"

    def engine_dir(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path


def engine_dirs(name: str) -> list[Path]:
    """Where an engine's own runtime can live, packaged app first."""
    import sys

    from agent.config import REPO_ROOT

    # Packaged: <resources>/backend-runtime/python/python.exe -> <resources>/engine-runtimes/<name>
    resources = Path(sys.executable).resolve().parents[2]
    return [resources / "engine-runtimes" / name, Path(REPO_ROOT) / ".engines" / name]


def engine_python(name: str) -> Path | None:
    """The engine's own Python: packaged copy, or a development venv."""
    import os

    explicit = os.environ.get(f"VELLUM_{name.upper()}_PYTHON")
    candidates = [Path(explicit)] if explicit else []
    for home in engine_dirs(name):
        candidates += [home / "python" / "python.exe",
                       home / ".venv" / "Scripts" / "python.exe", home / ".venv" / "bin" / "python",
                       home / "src" / ".venv" / "Scripts" / "python.exe", home / "src" / ".venv" / "bin" / "python"]
    return next((path for path in candidates if path.is_file()), None)


def register_engine(name: str, factory: Callable[[EngineContext], EngineSpec]) -> None:
    with _REGISTRY_LOCK:
        if all(existing != name for existing, _ in _REGISTRY):
            _REGISTRY.append((name, factory))


@lru_cache(maxsize=1)
def get_engine_context() -> EngineContext:
    import os

    from agent.config import REPO_ROOT

    root = Path(REPO_ROOT) / "data" / "engines"
    # The desktop shell passes API_PORT to the backend (desktop/electron/backend.cjs).
    api_base = f"http://127.0.0.1:{os.environ.get('API_PORT') or 8000}"
    return EngineContext(root, EnginePostgres(root), api_base)


ENGINE_MODULES = ("agent.memory.engines.hindsight_engine", "agent.memory.engines.honcho_engine")


def _load_engines() -> None:
    import importlib

    for module in ENGINE_MODULES:
        importlib.import_module(module)  # each module calls register_engine()


@lru_cache(maxsize=1)
def get_engine_supervisor() -> EngineSupervisor:
    _load_engines()
    supervisor = EngineSupervisor()
    context = get_engine_context()
    with _REGISTRY_LOCK:
        engines = list(_REGISTRY)
    if engines:
        supervisor.before_all(context.postgres.start)
        supervisor.after_all(context.postgres.stop)
    for name, factory in engines:
        supervisor.add_engine(name, lambda factory=factory: factory(context))
    return supervisor


def start_engines() -> None:
    from agent.config import get_settings

    if not get_settings().memory_engines_enabled:
        logger.info("[ENGINES] disabled by MEMORY_ENGINES_ENABLED")
        return
    get_engine_supervisor().start()


def restart_engines() -> None:
    """Re-read the user's model choice and restart every engine with it (in the background)."""
    from agent.config import get_settings

    get_settings.cache_clear()
    from agent.llm.providers import get_provider_registry

    get_provider_registry.cache_clear()
    if not get_engine_supervisor.cache_info().currsize or get_engine_supervisor()._thread is None:
        return  # engines never started in this process; the next launch reads the new choice
    supervisor = get_engine_supervisor()

    def run() -> None:
        supervisor.stop()
        if get_settings().memory_engines_enabled:
            supervisor.start()

    threading.Thread(target=run, name="memory-engines-restart", daemon=True).start()


def stop_engines() -> None:
    if get_engine_supervisor.cache_info().currsize:
        get_engine_supervisor().stop()


def engines_status() -> dict[str, Any]:
    from agent.memory.engines.llm_routing import memory_engine_llm

    llm = memory_engine_llm()
    supervisor = get_engine_supervisor()
    return {
        "engines": supervisor.status(),
        "llm": {"provider": llm.provider, "model": llm.model, "ready": llm.ready, "reason": llm.reason},
    }
