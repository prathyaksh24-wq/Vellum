"""Idempotent control plane for connector ingestion operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agent.knowledge.models import IngestionJobInput, SyncCursorInput
from agent.knowledge.store import KnowledgeStore


@dataclass(frozen=True)
class IngestionResult:
    stats: dict[str, Any] = field(default_factory=dict)
    cursor: str = ""
    cursor_state: dict[str, Any] = field(default_factory=dict)


IngestionOperation = Callable[[dict[str, Any] | None], IngestionResult]


class IngestionCoordinator:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def run(
        self,
        request: IngestionJobInput,
        *,
        operation: IngestionOperation,
    ) -> dict[str, Any]:
        job = self.store.start_ingestion_job(request)
        if not job["should_run"]:
            return job
        current_cursor = self.store.get_sync_cursor(request.connector, request.account_id)
        try:
            result = operation(current_cursor)
        except Exception as exc:
            error_code = type(exc).__name__ or "INGESTION_FAILED"
            self.store.fail_ingestion_job(str(job["id"]), error_code=error_code)
            raise
        return self.store.complete_ingestion_job(
            str(job["id"]),
            stats=result.stats,
            cursor=SyncCursorInput(
                connector=request.connector,
                account_id=request.account_id,
                cursor=result.cursor,
                state=result.cursor_state,
            ),
        )
