"""Application service for Vellum's canonical Personal Intelligence store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.knowledge.book_catalog import BookCatalog
from agent.knowledge.book_discovery import BookDiscoveryRuntime
from agent.knowledge.book_ingestion import BookIngestionPipeline, MalwareScanner
from agent.knowledge.book_documents import BookDocument, BookDocumentPipeline
from agent.knowledge.book_quality import (
    BookQualityAssessment,
    BookQualityPipeline,
)
from agent.knowledge.book_materialization import (
    BOOK_MATERIALIZATION_COMPILER_VERSION,
    BookEmbeddingProvider,
    BookMaterialization,
    BookMaterializationPipeline,
    BookRetrievalIndex,
)
from agent.knowledge.adapters import ConversationAdapter, MemoryAdapter, ObsidianAdapter, RetrievalIndexAdapter
from agent.knowledge.materialization import MaterializationCanary
from agent.knowledge.models import (
    BookDiscoveryPolicy,
    BookDiscoveryRequest,
    BookDiscoveryVerificationRequest,
    BookDocumentRequest,
    BookImportRequest,
    BookImportStatus,
    BookMaterializationRequest,
    BookMaterializationStatus,
    BookRetrievalRequest,
    BookQualityRequest,
    BookUserLearningRequest,
    BookWisdomRecordInput,
    BootstrapRequest,
    ContextPackRequest,
    ExternalPolicy,
    MaterializationCanaryRequest,
    ObservationActor,
    ObservationInput,
    PromotionStatus,
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
        book_malware_scanner: MalwareScanner | None = None,
        book_embedding_provider: BookEmbeddingProvider | None = None,
        book_materialization_compiler_version: str = BOOK_MATERIALIZATION_COMPILER_VERSION,
        book_embedding_model_revision: str = "default",
        book_retrieval_index: BookRetrievalIndex | None = None,
        book_catalog: BookCatalog | None = None,
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
        self.book_ingestion = BookIngestionPipeline(
            store,
            scanner=book_malware_scanner,
        )
        self.book_documents = BookDocumentPipeline(store)
        self.book_discovery = BookDiscoveryRuntime(store, self.book_documents, catalog=book_catalog)
        self.book_quality = BookQualityPipeline(store, self.book_documents)
        if book_embedding_provider is None:
            from agent.rag.embedder import get_embedder

            book_embedding_provider = get_embedder()
        self.book_materializations = BookMaterializationPipeline(
            store,
            self.book_quality,
            embedding_provider=book_embedding_provider,
            compiler_version=book_materialization_compiler_version,
            embedding_model_revision=book_embedding_model_revision,
            retrieval_index=book_retrieval_index,
        )

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
            "user_learning_candidates": {
                "current": "Knowledge Core",
                "future": "Knowledge Core",
                "migration": "canonical",
            },
            "book_wisdom": {
                "current": "Knowledge Core derived insights",
                "future": "Knowledge Core derived insights",
                "migration": "canonical",
            },
            "book_discovery": {
                "current": "Knowledge Core shadow candidates",
                "future": "Knowledge Core candidates separate from Library",
                "migration": "shadow_only",
            },
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

    def discover_books(self, request: BookDiscoveryRequest, *, policy: BookDiscoveryPolicy) -> dict[str, Any]:
        if not self.shadow_write:
            return {"status": "blocked", "mode": "shadow", "candidates": [], "error_code": "DISCOVERY_DISABLED"}
        return self.book_discovery.discover(request, policy=policy)

    def verify_book_discovery_candidate(
        self,
        request: BookDiscoveryVerificationRequest,
        *,
        policy: BookDiscoveryPolicy,
    ) -> dict[str, Any]:
        if not self.shadow_write:
            return {
                "status": "blocked",
                "mode": "shadow",
                "candidates": [],
                "metadata": {"reason_code": "DISCOVERY_DISABLED"},
                "error_code": "DISCOVERY_DISABLED",
            }
        return self.book_discovery.verify(request, policy=policy)

    def list_book_discovery_candidates(self, *, user_id: str, objective: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.book_discovery.list_candidates(user_id=user_id, objective=objective, limit=limit)

    def dismiss_book_discovery_candidate(self, *, user_id: str, candidate_id: str) -> bool:
        return self.store.dismiss_book_discovery_candidate(user_id=user_id, candidate_id=candidate_id)

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

    def record_book_user_learning(self, request: BookUserLearningRequest) -> dict[str, Any]:
        request = BookUserLearningRequest.model_validate(request.model_dump(mode="python"))
        relationship = request.relationship
        self._validate_book_user_learning(request)
        tenant_scope = self.store.book_tenant_scope(relationship.user_id)
        observation = self.store.record_observation(
            ObservationInput(
                origin="books.user_learning",
                actor=relationship.actor,
                trigger=relationship.trigger,
                action=relationship.action,
                event_key=(
                    f"books:relationship:{tenant_scope}:"
                    f"{self._digest({'event_key': relationship.event_key})}"
                ),
                payload={
                    "tenant_scope": tenant_scope,
                    "evidence_basis": relationship.evidence_basis,
                    "book_ids": relationship.book_ids,
                    "source_anchor_ids": relationship.source_anchor_ids,
                    "conversation_ids": relationship.conversation_ids,
                },
                sensitivity=relationship.sensitivity,
                confidence=relationship.confidence,
                observed_at=relationship.observed_at,
                promotion_status=PromotionStatus.DURABLE,
            )
        )
        candidates = [
            self.store.propose_user_learning_candidate(
                candidate,
                observation_id=observation["observation_id"],
            )
            for candidate in request.candidates
        ]
        return {"relationship": observation, "candidates": candidates}

    def propose_book_wisdom(self, request: BookWisdomRecordInput) -> dict[str, Any]:
        return self.store.propose_book_wisdom(request)

    @staticmethod
    def _validate_book_user_learning(request: BookUserLearningRequest) -> None:
        relationship = request.relationship
        if any(candidate.user_id != relationship.user_id for candidate in request.candidates):
            raise ValueError("Book relationship and candidate user identities must match")
        if request.candidates and (
            relationship.actor in {ObservationActor.AGENT, ObservationActor.SCHEDULED}
            or relationship.evidence_basis == "agent_activity"
        ):
            raise ValueError("Agent Book activity cannot create user-learning candidates")

        for candidate in request.candidates:
            if candidate.actor != relationship.actor:
                raise ValueError("Book relationship and candidate actors must match")
            if candidate.proposition_type == "reading_status":
                allowed_reading_evidence = (
                    candidate.basis == "explicit"
                    and (
                        (
                            relationship.action == "reading_status.stated"
                            and relationship.actor == ObservationActor.USER
                        )
                        or (
                            relationship.action == "reading_status.connector_observed"
                            and relationship.actor == ObservationActor.CONNECTOR
                        )
                    )
                )
                if not allowed_reading_evidence:
                    raise ValueError("Reading status requires explicit user or connector evidence")
            if (
                relationship.action == "book.imported"
                and candidate.basis == "inferred"
                and candidate.confidence > 0.25
            ):
                raise ValueError("Book import is only weak evidence of possible interest")

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

    def materialize_canary(self, request: MaterializationCanaryRequest) -> dict[str, Any]:
        return MaterializationCanary(
            self.store,
            conversations_path=self.conversations_path,
            vault_root=self.vault_root,
        ).run(request)

    def create_context_pack(self, request: ContextPackRequest) -> dict[str, Any]:
        return self.store.create_context_pack(request)

    def import_book_epub(self, request: BookImportRequest, content: bytes) -> BookImportStatus:
        return self.book_ingestion.import_epub(request, content)

    def construct_book_document(self, request: BookDocumentRequest) -> BookImportStatus:
        return self.book_documents.construct(request)

    def get_book_document(self, *, user_id: str, document_id: str) -> BookDocument:
        return self.book_documents.load(user_id=user_id, document_id=document_id)

    def evaluate_book_document_quality(self, request: BookQualityRequest) -> BookImportStatus:
        return self.book_quality.evaluate(request)

    def get_book_document_for_materialization(
        self,
        *,
        user_id: str,
        document_id: str,
    ) -> BookDocument:
        return self.book_quality.load_for_materialization(
            user_id=user_id,
            document_id=document_id,
        )

    def get_book_quality_assessment(
        self,
        *,
        user_id: str,
        document_id: str,
    ) -> BookQualityAssessment:
        return self.book_quality.load_assessment(
            user_id=user_id,
            document_id=document_id,
        )

    def materialize_book_document(
        self,
        request: BookMaterializationRequest,
    ) -> BookMaterializationStatus:
        return self.book_materializations.materialize(request)

    def get_book_materialization(
        self,
        *,
        user_id: str,
        materialization_id: str,
    ) -> BookMaterialization:
        return self.book_materializations.load(
            user_id=user_id,
            materialization_id=materialization_id,
        )

    def get_active_book_materialization(
        self,
        *,
        user_id: str,
        edition_id: str,
    ) -> BookMaterializationStatus:
        return BookMaterializationStatus.model_validate(
            self.store.get_active_book_materialization_status(
                user_id=user_id,
                edition_id=edition_id,
            )
        )

    def get_active_book_materialization_bundle(
        self,
        *,
        user_id: str,
        edition_id: str,
    ) -> BookMaterialization:
        return self.book_materializations.load_active(
            user_id=user_id,
            edition_id=edition_id,
        )

    def list_active_book_skills(
        self,
        *,
        user_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.book_materializations.list_active_skills(
            user_id=user_id,
            limit=limit,
        )

    def search_active_book_materializations(
        self,
        request: BookRetrievalRequest,
    ) -> dict[str, Any]:
        return self.book_materializations.search_active(request)

    def get_book_ingestion_status(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str = "",
    ) -> BookImportStatus:
        return BookImportStatus.model_validate(
            self.store.get_book_import_status(
                user_id=user_id,
                import_id=import_id,
                run_id=run_id,
            )
        )

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        import hashlib

        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
