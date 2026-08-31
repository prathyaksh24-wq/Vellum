from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.knowledge.book_ingestion import WindowsDefenderScanner
from agent.knowledge.book_library import BookLibrary, RIGHTS_ATTESTATION_VERSION
from agent.knowledge.models import BookImportRequest, BookRetrievalRequest
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore


class AcceptanceEmbedder:
    model_name = "acceptance-book-embedding-v1"

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [
            [float(len(text)), float(sum(character.isalpha() for character in text))]
            for text in texts
        ]


class AcceptanceIndex:
    collection_name = "acceptance-books"

    def __init__(self) -> None:
        self.points: dict[str, dict[str, object]] = {}

    def upsert(self, **kwargs: object) -> str:
        point_id = f"point-{kwargs['materialization_id']}-{kwargs['chunk_id']}"
        self.points[point_id] = dict(kwargs)
        return point_id

    def delete_materialization(self, *, user_id: str, materialization_id: str) -> None:
        self.points = {
            point_id: point
            for point_id, point in self.points.items()
            if point["user_id"] != user_id or point["materialization_id"] != materialization_id
        }

    def search(
        self,
        *,
        embedding: list[float],
        top_k: int,
        filters: dict[str, object],
    ) -> list[dict[str, object]]:
        _ = embedding
        allowed = set(dict(filters["materialization_id"])["$in"])
        matches = [
            {
                "text": point["text"],
                "score": 1.0,
                "metadata": {
                    key: point[key]
                    for key in (
                        "user_id",
                        "materialization_id",
                        "edition_id",
                        "document_id",
                        "chunk_id",
                    )
                },
            }
            for point in self.points.values()
            if point["user_id"] == filters["user_id"]
            and point["materialization_id"] in allowed
        ]
        return matches[:top_k]


@pytest.mark.skipif(
    not os.environ.get("VELLUM_ACCEPTANCE_EPUB"),
    reason="Set VELLUM_ACCEPTANCE_EPUB to run the real local EPUB acceptance test.",
)
def test_real_epub_compiles_book_to_skill_and_is_retrievable(tmp_path: Path) -> None:
    source = Path(os.environ["VELLUM_ACCEPTANCE_EPUB"])
    content = source.read_bytes()
    core = KnowledgeCore(
        KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs"),
        conversations_path=tmp_path / "data" / "ui" / "conversations.json",
        vault_root=tmp_path / "Vault",
        book_malware_scanner=WindowsDefenderScanner(),
        book_embedding_provider=AcceptanceEmbedder(),
        book_retrieval_index=AcceptanceIndex(),
    )
    imported = core.import_book_epub(
        BookImportRequest(
            user_id="acceptance-user",
            rights_attestation_version=RIGHTS_ATTESTATION_VERSION,
            scan_approved=True,
            local_only=False,
            requested_by="acceptance-test",
        ),
        content,
    )

    assert imported.status == "validated", imported.error_code
    result = BookLibrary(core, "acceptance-user").materialize(imported.import_id)
    assert result["error_code"] == "", result
    assert result["book"]["skill_status"] == "compiled"
    assert result["book"]["title"] == "David and Goliath"
    skills = core.list_active_book_skills(user_id="acceptance-user")
    assert len(skills) == 1
    assert skills[0]["compiler"] == "book-to-skill-v1.3.0-vellum.1"

    retrieved = core.search_active_book_materializations(
        BookRetrievalRequest(
            user_id="acceptance-user",
            query="What does the book say about underdogs and apparent disadvantages?",
            destination="external",
            max_chunks=3,
            token_budget=8000,
        )
    )
    assert retrieved["evidence"]
    assert all(item["citations"] for item in retrieved["evidence"])
    assert retrieved["policy"]["source_content"] == "untrusted_evidence"
