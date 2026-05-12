"""
Nightly self-learning digest.

Reads recent indexed Q&A pairs, summarizes them with the fast OpenRouter model,
and writes the digest back into the local Obsidian vault.
"""

from __future__ import annotations

from datetime import datetime
import logging

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
    return str(note_path)


def start_scheduler(scheduler: AsyncIOScheduler | None = None) -> AsyncIOScheduler | None:
    settings = get_settings()
    if not settings.enable_nightly_digest:
        logger.info("[DIGEST] Nightly digest scheduler disabled.")
        return None

    scheduler = scheduler or AsyncIOScheduler()
    scheduler.add_job(run_digest, "cron", hour=2, minute=0, id="nightly_digest", replace_existing=True)
    scheduler.start()
    logger.info("[DIGEST] Nightly digest scheduler started at 02:00 local time.")
    return scheduler

