"""Built-in background jobs as ordinary store automations.

The five hardcoded scheduler jobs (memory dreaming, nightly digest, vault
retention, YouTube intelligence projection, skill curator tick) migrate into
the automation store as ``builtin: true`` records, seeded idempotently on
startup. They stay visible, editable, and pausable like user automations;
deleting one restores its default schedule instead of removing it.

When a built-in's job fires, the automation scheduler dispatches to the
original backend function (``run_digest``, ``run_retention``, ...) rather than
a reasoning turn — these are maintenance jobs, not user automations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent.automations.schedules import parse_schedule
from agent.automations.store import AutomationStore

logger = logging.getLogger(__name__)

BUILTIN_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "memory_dreaming",
        "name": "Memory dreaming",
        "instructions": (
            "Dream over recent memory: distill new long-term insights from today's "
            "conversations and notes."
        ),
        "schedule": "0 2 * * *",
    },
    {
        "key": "nightly_digest",
        "name": "Nightly digest",
        "instructions": "Read recent learned facts and write a knowledge digest into the vault.",
        "schedule": "15 2 * * *",
    },
    {
        "key": "vault_retention",
        "name": "Vault retention",
        "instructions": "Run vault retention: archive or condense aging notes per policy.",
        "schedule": "0 3 * * *",
    },
    {
        "key": "youtube_intelligence_projection",
        "name": "YouTube intelligence projection",
        "instructions": "Rebuild local YouTube intelligence projections incrementally.",
        "schedule": "30 2 * * *",
    },
    {
        "key": "skill_curator_tick",
        "name": "Skill curator tick",
        "instructions": "Curate skills: review candidates, prune stale proposals, refresh the index.",
        "schedule": "every 1h",
    },
]


def _definitions_by_key() -> dict[str, dict[str, Any]]:
    return {definition["key"]: definition for definition in BUILTIN_DEFINITIONS}


def seed_builtins(
    store: AutomationStore,
    *,
    enabled: dict[str, bool] | None = None,
) -> list[str]:
    """Create missing built-in records (idempotent; never overwrites user edits)."""
    seeded: list[str] = []
    for definition in BUILTIN_DEFINITIONS:
        key = definition["key"]
        existing = next(
            (record for record in store.list() if record.get("builtin_key") == key),
            None,
        )
        if existing is not None:
            continue
        state = "active"
        if enabled is not None and enabled.get(key) is False:
            state = "paused"
        record = store.create(
            name=definition["name"],
            instructions=definition["instructions"],
            schedule=parse_schedule(definition["schedule"]).to_dict(),
            destination={"kind": "new_chat"},
            permission={"full_access": True},
            builtin=True,
            builtin_key=key,
            state=state,
        )
        seeded.append(record["id"])
    return seeded


def reset_builtin(store: AutomationStore, record: dict[str, Any]) -> dict[str, Any]:
    """Restore a built-in to its default schedule and fields (delete protection)."""
    definition = _definitions_by_key().get(str(record.get("builtin_key") or ""))
    if definition is None:
        raise ValueError(f"unknown built-in: {record.get('builtin_key')!r}")
    return store.update(
        record["id"],
        name=definition["name"],
        instructions=definition["instructions"],
        schedule=parse_schedule(definition["schedule"]).to_dict(),
        destination={"kind": "new_chat"},
        permission={"full_access": True},
        state="active",
    )


async def run_builtin(record: dict[str, Any]) -> None:
    """Dispatch a fired built-in to its original backend function."""
    key = str(record.get("builtin_key") or record.get("name") or "")
    handler = _HANDLERS.get(key)
    if handler is None:
        logger.warning("[AUTOMATIONS] no handler for built-in %r; skipping", key)
        return
    try:
        await handler()
    except Exception as exc:  # noqa: BLE001 — maintenance jobs never crash the API
        logger.warning("[AUTOMATIONS] built-in %s failed: %s", key, exc)


async def _memory_dreaming_handler() -> None:
    from agent import api  # lazy: the main api module mounts this package's router

    await api._maybe_run_dreaming(reason="scheduled", force=True)


async def _nightly_digest_handler() -> None:
    from agent.scheduler.digest import run_digest

    await run_digest()


async def _vault_retention_handler() -> None:
    from agent.scheduler.retention import run_retention

    await run_retention()


async def _youtube_projection_handler() -> None:
    from agent.scheduler.youtube_intelligence import run_projection

    await asyncio.to_thread(run_projection)


async def _curator_tick_handler() -> None:
    from agent.skills.curator_runtime import get_curator_runtime

    await asyncio.to_thread(get_curator_runtime().tick)


_HANDLERS: dict[str, Any] = {
    "memory_dreaming": _memory_dreaming_handler,
    "nightly_digest": _nightly_digest_handler,
    "vault_retention": _vault_retention_handler,
    "youtube_intelligence_projection": _youtube_projection_handler,
    "skill_curator_tick": _curator_tick_handler,
}
