"""Scheduled execution wrapper for the guarded Obsidian retention workflow."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from typing import Any

from agent.config import REPO_ROOT, get_settings


logger = logging.getLogger(__name__)


def _load_retention_runner():
    path = REPO_ROOT / "scripts" / "apply_retention.py"
    spec = importlib.util.spec_from_file_location("vellum_apply_retention", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load retention workflow from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module.run


apply_retention = _load_retention_runner()


async def run_retention() -> dict[str, Any]:
    settings = get_settings()
    result = await asyncio.to_thread(
        apply_retention,
        vault_root=settings.obsidian_vault_path,
        archive_after_days=settings.retention_archive_days,
        delete_after_days=settings.retention_delete_days,
        dry_run=False,
    )
    logger.info("[RETENTION] completed: %s", result)
    return result
