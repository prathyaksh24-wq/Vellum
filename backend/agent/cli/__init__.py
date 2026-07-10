"""Skill-aware CLI helpers and compatibility entry point."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from rich.console import Console

from agent.skills import SkillSurfaceService

_skill_surface_singleton: SkillSurfaceService | None = None


def _skill_surface() -> SkillSurfaceService:
    global _skill_surface_singleton
    if _skill_surface_singleton is None:
        _skill_surface_singleton = SkillSurfaceService(
            Path(".skills"), logs_root=Path("data/logs/curator"), sources=[]
        )
    return _skill_surface_singleton


async def handle_command(
    user_input: str,
    active_console: Console,
    *,
    current_thread_config: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    result = _skill_surface().slash(user_input)
    if not result["handled"]:
        return False, current_thread_config
    active_console.print(result.get("answer") or result.get("expanded") or "")
    return True, current_thread_config


def expand_skill_input(user_input: str) -> str:
    result = _skill_surface().slash(user_input)
    return str(result.get("expanded") or user_input)


def main() -> None:
    """Load the legacy module entry point despite the package/module name clash."""
    cli_path = Path(__file__).resolve().parent.parent / "cli.py"
    spec = importlib.util.spec_from_file_location("agent._fallback_cli", cli_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("CLI entry point unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


__all__ = ["expand_skill_input", "handle_command", "main"]
