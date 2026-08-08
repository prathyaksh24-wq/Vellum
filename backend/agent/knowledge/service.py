"""Application service for Vellum's canonical Personal Intelligence store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.knowledge.adapters import ConversationAdapter, MemoryAdapter, ObsidianAdapter, RetrievalIndexAdapter
from agent.knowledge.models import (
    BootstrapRequest,
    ContextPackRequest,
    ExternalPolicy,
    ObservationActor,
    ObservationInput,
    Sensitivity,
    SourceItemInput,
)
from agent.knowledge.store import KnowledgeStore


class KnowledgeCore:
    def __init__(
        self,
        store: KnowledgeStore,
        *,
        conversations_path: Path,
        vault_root: Path,
        memory_db_path: Path | None = None,
        fts5_db_path: Path | None = None,
        memory_snapshot_dir: Path | None = None,
        vector_path: Path | None = None,
        vector_reader: Any | None = None,
        shadow_write: bool = True,
        read_enabled: bool = False,
        tool_learning_enabled: bool = False,
    ) -> None:
        self.store = store
        self.conversations_path = Path(conversations_path)
        self.vault_root = Path(vault_root)
        data_root = self.conversations_path.parent.parent
        self.memory_db_path = Path(memory_db_path) if memory_db_path is not None else data_root / "memory" / "sessions.db"
        self.fts5_db_path = Path(fts5_db_path) if fts5_db_path is not None else data_root / "memory" / "fts5.db"
        self.memory_snapshot_dir = (
            Path(memory_snapshot_dir) if memory_snapshot_dir is not None else self.memory_db_path.parent
        )
        self.vector_path = Path(vector_path) if vector_path is not None else None
        self.vector_reader = vector_reader
        self.shadow_write = bool(shadow_write)
        self.read_enabled = bool(read_enabled)
        self.tool_learning_enabled = bool(tool_learning_enabled)

    def status(self) -> dict[str, Any]:
        return {
            **self.store.status(),
            "mode": "shadow" if self.shadow_write and not self.read_enabled else "active",
            "flags": {
                "shadow_write": self.shadow_write,
                "read_enabled": self.read_enabled,
                "tool_learning_enabled": self.tool_learning_enabled,
            },
            "ownership": self.ownership(),
        }

    @staticmethod
    def ownership() -> dict[str, dict[str, str]]:
        return {
            "conversations": {
                "current": "data/ui/conversations.json",
                "future": "Knowledge Core source records",
                "migration": "shadow_import",
            },
            "durable_memories": {
                "current": "Memory Orchestrator SQLite",
                "future": "Memory Orchestrator SQLite",
                "migration": "preserve",
            },
            "user_model": {"current": "Honcho", "future": "Honcho", "migration": "preserve"},
            "knowledge_wiki": {
                "current": "Vault/Knowledge",
                "future": "Obsidian projection of Knowledge Core insights",
                "migration": "shadow_import_then_project",
            },
            "raw_sources": {
                "current": "Vault/Library and legacy source folders",
                "future": "Knowledge Core blobs and source records",
                "migration": "content_hash_import",
            },
            "obsidian": {
                "current": "mixed canonical and projections",
                "future": "optional readable projection and explicit user-authored source",
                "migration": "classify_before_cutover",
            },
            "retrieval_indexes": {
                "current": "FTS5 and Chroma",
                "future": "FTS5 and Chroma",
                "migration": "rebuildable",
            },
        }

    def record_turn(
        self,
        *,
        thread_id: str,
        query: str,
        answer: str,
        tools: list[dict[str, Any]] | None = None,
        sources: list[str] | None = None,
        agent_name: str = "VellumAgent",
    ) -> dict[str, Any]:
        if not self.shadow_write:
            return {"stored": False, "reason": "shadow_write_disabled"}
        payload = {
            "thread_id": thread_id,
            "query": query,
            "answer": answer,
            "tools": tools or [],
            "sources": sources or [],
            "agent_name": agent_name,
        }
        result = self.store.upsert_source(
            SourceItemInput(
                kind="conversation_turn",
                external_id=f"{thread_id}:{self._digest(payload)}",
                title=f"Conversation turn in {thread_id}",
                content=json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
                source_path=f"data/ui/conversations.json#{thread_id}",
                sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                external_policy=ExternalPolicy.DENY_RAW,
                trust="canonical_conversation_event",
                metadata={"thread_id": thread_id, "agent_name": agent_name},
            )
        )
        observation = self.store.record_observation(
            ObservationInput(
                origin="memory_orchestrator",
                actor=ObservationActor.USER,
                trigger="completed_turn",
                action="conversation.turn_recorded",
                source_id=result["source_id"],
                event_key=f"turn:{thread_id}:{result['content_hash']}",
                payload={
                    "agent_name": agent_name,
                    "tool_names": [str(tool.get("name") or tool.get("tool") or "") for tool in tools or []],
                    "source_count": len(sources or []),
                },
                sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                confidence=1.0,
            )
        )
        return {"stored": True, **result, **observation}

    def record_tool_result(
        self,
        *,
        tool_name: str,
        payload: dict[str, Any],
        result: dict[str, Any],
        actor: ObservationActor,
        trigger: str,
    ) -> dict[str, Any]:
        if not self.tool_learning_enabled:
            return {"stored": False, "reason": "tool_learning_disabled"}
        return self.store.record_observation(
            ObservationInput(
                origin=tool_name,
                actor=actor,
                trigger=trigger,
                action="tool.result_observed",
                payload={"request": payload, "result": result},
                sensitivity=Sensitivity.PRIVATE,
                confidence=0.5,
            )
        )

    def bootstrap(self, request: BootstrapRequest) -> dict[str, Any]:
        conversation_stats = {
            "scanned": 0,
            "imported": 0,
            "versions": 0,
            "projections": 0,
            "archived": 0,
            "skipped": 0,
            "errors": [],
        }
        memory_stats = dict(conversation_stats)
        vault_stats = dict(conversation_stats)
        index_stats = dict(conversation_stats)
        if request.conversations:
            adapter = ConversationAdapter(self.store)
            conversation_stats = adapter.import_records(
                adapter.load(self.conversations_path),
                apply=request.apply,
                limit=request.limit,
            ).as_dict()
        if request.memories:
            adapter = MemoryAdapter(
                self.store,
                self.memory_db_path,
                snapshot_dir=self.memory_snapshot_dir,
            )
            memory_stats = adapter.import_records(apply=request.apply, limit=request.limit).as_dict()
        if request.vault_library or request.knowledge_wiki or request.agent_projections or request.archives:
            adapter = ObsidianAdapter(self.store, self.vault_root)
            paths = adapter.candidate_paths(
                library=request.vault_library,
                knowledge_wiki=request.knowledge_wiki,
                agent_projections=request.agent_projections,
                archives=request.archives,
            )
            vault_stats = adapter.import_paths(paths, apply=request.apply, limit=request.limit).as_dict()
        if request.retrieval_indexes:
            adapter = RetrievalIndexAdapter(
                self.store,
                fts5_path=self.fts5_db_path,
                vector_path=self.vector_path,
                vector_reader=self.vector_reader,
            )
            index_stats = adapter.import_records(apply=request.apply, limit=request.limit).as_dict()
        return {
            "mode": "apply" if request.apply else "preview",
            "conversations": conversation_stats,
            "memories": memory_stats,
            "vault": vault_stats,
            "retrieval_indexes": index_stats,
            "status": self.store.status() if request.apply else None,
        }

    def create_context_pack(self, request: ContextPackRequest) -> dict[str, Any]:
        return self.store.create_context_pack(request)

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        import hashlib

        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
