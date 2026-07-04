from __future__ import annotations

from agent.organization.models import MemoryRecord
from agent.organization.store import OrganizationStore


class MemoryBroker:
    def __init__(self, store: OrganizationStore, *, departments: dict[str, str]) -> None:
        self.store = store
        self.departments = departments

    def write(self, *, actor: str, scope: str, text: str, confidence: float) -> MemoryRecord:
        if not self._allowed(actor, scope, write=True):
            raise PermissionError("memory unavailable")
        return self.store.add_memory(actor, scope, text, confidence)

    def search(self, *, actor: str, query: str) -> list[MemoryRecord]:
        return [record for record in self.store.search(query) if self._allowed(actor, record.scope, write=False)]

    def get(self, *, actor: str, record_id: str) -> MemoryRecord:
        record = self.store.get(record_id)
        if record is None or not self._allowed(actor, record.scope, write=False):
            raise PermissionError("memory unavailable")
        return record

    def promote(self, *, actor: str, record_id: str, target_scope: str) -> MemoryRecord:
        if actor not in {"VellumAgent", "MemoryAgent"}:
            raise PermissionError("memory unavailable")
        source = self.store.get(record_id)
        if source is None:
            raise PermissionError("memory unavailable")
        return self.store.add_memory(source.owner, target_scope, source.text, source.confidence, parent_id=source.id)

    def _allowed(self, actor: str, scope: str, *, write: bool) -> bool:
        if scope == f"agent:{actor}":
            return True
        if scope.startswith("department:"):
            return self.departments.get(actor) == scope.split(":", 1)[1]
        if scope == "organization:shared":
            return not write or actor in {"VellumAgent", "MemoryAgent"}
        return False
