"""Scheduled rebuild of local YouTube intelligence projections."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

from agent.knowledge.runtime import get_knowledge_core
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService


logger = logging.getLogger(__name__)


def run_projection(
    *,
    intelligence: YouTubeIntelligenceService | Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = now or datetime.now(UTC)
    service = intelligence or YouTubeIntelligenceService(get_knowledge_core().store)
    try:
        result = service.rebuild(now=reference)
    except Exception as exc:  # noqa: BLE001
        error_code = exc.__class__.__name__
        logger.warning("[YOUTUBE_INTELLIGENCE] Projection rebuild failed: %s", error_code)
        return {"status": "failed", "error_code": error_code}
    return {"status": "completed", **result}


def install_projection_job(scheduler: Any) -> None:
    scheduler.add_job(
        run_projection,
        "cron",
        hour=2,
        minute=30,
        id="youtube_intelligence_projection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
