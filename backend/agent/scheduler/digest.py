"""
Nightly self-learning digest.

Reads recent indexed Q&A pairs, summarizes them with the fast OpenRouter model,
and writes the digest back into the local Obsidian vault.
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from collections.abc import Callable
from typing import Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agent.config import get_settings
from agent.llm.openrouter import openrouter_chat
from agent.memory.fts5 import FTS5Memory
from agent.obsidian.vault import ObsidianVault

logger = logging.getLogger(__name__)

DIGEST_SYSTEM_PROMPT = "You summarize knowledge into concise markdown insights."


def build_digest_prompt(facts: list[str]) -> str:
    facts_text = "\n".join(f"- {fact}" for fact in facts)
    return f"""Summarize these learned facts into 3-5 key insights about the user's interests and knowledge gaps.
Return a clean markdown summary.

Facts:
{facts_text}

Summary:"""


async def run_digest(
    *,
    memory: FTS5Memory | None = None,
    vault: ObsidianVault | None = None,
    now: datetime | None = None,
) -> str | None:
    settings = get_settings()
    memory = memory or FTS5Memory()
    vault = vault or ObsidianVault(settings.obsidian_vault_path)
    now = now or datetime.now()

    logger.info("[DIGEST] Starting nightly self-learning digest.")
    facts = [item["content"] for item in memory.recent_documents(limit=50)]
    if not facts:
        logger.info("[DIGEST] No new facts to digest.")
        return None

    summary = await openrouter_chat(
        system=DIGEST_SYSTEM_PROMPT,
        user=build_digest_prompt(facts),
        model_override=settings.fast_model,
        max_tokens=700,
        temperature=0.2,
        session_id=f"digest-{now.strftime('%Y-%m-%d')}",
    )

    date_str = now.strftime("%Y-%m-%d")
    content = f"# Knowledge Digest - {date_str}\n\n{summary}"
    note_path = vault.create_note(
        folder=f"{settings.agent_notes_folder}/Digests",
        title=f"Digest {date_str}",
        content=content,
    )

    logger.info("[DIGEST] Digest written to Obsidian: %s", note_path)

    # Sports curiosity self-calibration piggybacks on the nightly digest.
    # No separate schedule — it only runs when the digest runs.
    try:
        from agent.scheduler.sports_calibration import run_safely as run_sports_calibration

        run_sports_calibration(now=now if isinstance(now, datetime) else datetime.now())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DIGEST] sports calibration step failed: %s", exc)

    try:
        from agent.skills.learning import SkillLearningWorkflow

        learning = SkillLearningWorkflow(Path(".skills"))
        learning.record_signal(summary, kind="nightly_digest", successful=True)
        learning.review_candidates()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DIGEST] skill learning review failed: %s", exc)

    return str(note_path)


def start_scheduler(
    scheduler: AsyncIOScheduler | None = None,
    *,
    dreaming_job: Callable[[], Awaitable[object]] | None = None,
) -> AsyncIOScheduler | None:
    settings = get_settings()
    retention_enabled = bool(getattr(settings, "enable_vault_retention", True))
    if not settings.enable_nightly_digest and not retention_enabled and dreaming_job is None:
        logger.info("[SCHEDULER] Dreaming, digest, and retention are disabled.")
        return None

    scheduler = scheduler or AsyncIOScheduler()
    if dreaming_job is not None:
        scheduler.add_job(dreaming_job, "cron", hour=2, minute=0, id="memory_dreaming", replace_existing=True)
    if settings.enable_nightly_digest:
        scheduler.add_job(run_digest, "cron", hour=2, minute=15, id="nightly_digest", replace_existing=True)
    if retention_enabled:
        from agent.scheduler.retention import run_retention

        scheduler.add_job(run_retention, "cron", hour=3, minute=0, id="vault_retention", replace_existing=True)
    from agent.skills.curator_runtime import install_curator_ticker

    install_curator_ticker(scheduler)
    scheduler.start()
    logger.info("[SCHEDULER] Dreaming/digest/retention scheduler started.")
    return scheduler

