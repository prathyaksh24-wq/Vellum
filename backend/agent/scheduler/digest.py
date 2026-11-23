"""
Nightly self-learning digest.

Reads recent indexed Q&A pairs, summarizes them with the fast OpenRouter model,
and records the summary as a skill-learning signal.
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
    now: datetime | None = None,
) -> str | None:
    settings = get_settings()
    memory = memory or FTS5Memory()
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

    logger.info("[DIGEST] Summarized %d recent facts.", len(facts))

    try:
        from agent.skills.learning import SkillLearningWorkflow

        learning = SkillLearningWorkflow(Path(".skills"))
        learning.record_signal(summary, kind="nightly_digest", successful=True)
        learning.review_candidates()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DIGEST] skill learning review failed: %s", exc)

    return summary


def start_scheduler(
    scheduler: AsyncIOScheduler | None = None,
    *,
    dreaming_job: Callable[[], Awaitable[object]] | None = None,
    automation_store=None,
) -> AsyncIOScheduler | None:
    settings = get_settings()

    scheduler = scheduler or AsyncIOScheduler()
    # Legacy direct registration kept for callers that pass an explicit job;
    # otherwise the built-in background jobs live in the automation store
    # (seeded idempotently) and are registered from there.
    if dreaming_job is not None:
        scheduler.add_job(dreaming_job, "cron", hour=2, minute=0, id="memory_dreaming", replace_existing=True)
    from agent.automations.scheduler import install_automation_jobs

    install_automation_jobs(
        scheduler,
        store=automation_store,
        builtins_enabled={
            "nightly_digest": bool(getattr(settings, "enable_nightly_digest", True)),
            "discord_intelligence_sync": bool(getattr(settings, "discord_intelligence_sync_enabled", True)),
        },
    )
    # YouTube push: pull hosted upload events and deliver creator notifications
    # (every 5s) and keep the hosted channel list registered (every 30s).
    # Lost once in the 2026-11-15 branch switch; without it no push
    # notifications arrive. The tick itself no-ops when push is not configured.
    from agent.plugins.youtube_push import install_push_jobs

    install_push_jobs(scheduler)
    scheduler.start()
    logger.info("[SCHEDULER] Dreaming/digest scheduler started.")
    return scheduler

