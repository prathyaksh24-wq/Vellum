"""Vellum's harness: everything is a plugin (a port of DeepSeek Harness' Cordis model)."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from agent.harness.manager import PluginManager
from agent.harness.runtime import Context, Harness, HarnessError, InspectMethod, InspectProvider, Plugin


BASE_PATCH = Path(__file__).with_name("base.patch.yml")

_HARNESS: Harness | None = None
_LOCK = threading.Lock()


def harness_root() -> Path:
    configured = os.environ.get("VELLUM_HARNESS_DIR")
    if configured:
        return Path(configured)
    from agent.config import REPO_ROOT

    return REPO_ROOT / "data" / "harness"


def get_harness() -> Harness:
    """The process harness, composed on first use."""

    global _HARNESS
    with _LOCK:
        if _HARNESS is None:
            from agent.harness.builtins import builtin_plugins

            root = harness_root()
            harness = Harness(root, BASE_PATCH, builtin_plugins(root / "state"))
            harness.recompose("boot")
            _HARNESS = harness
        return _HARNESS


def get_plugin_manager() -> PluginManager:
    return PluginManager(get_harness())


def reset_harness() -> None:
    global _HARNESS
    with _LOCK:
        if _HARNESS is not None:
            for entry_id in reversed(_HARNESS.order):
                fiber = _HARNESS.fibers.get(entry_id)
                if fiber is not None and fiber.context is not None:
                    fiber.context.dispose()
        _HARNESS = None


__all__ = [
    "Context", "Harness", "HarnessError", "InspectMethod", "InspectProvider", "Plugin",
    "PluginManager", "get_harness", "get_plugin_manager", "harness_root", "reset_harness",
]
