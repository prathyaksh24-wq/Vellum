from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.knowledge.models import (
    BookRelationshipEventInput,
    BookUserLearningCandidateInput,
    BookUserLearningEvidenceReference,
    BookUserLearningRequest,
    ObservationActor,
)
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore


def build_core(tmp_path: Path) -> KnowledgeCore:
    vault = tmp_path / "Vault"
    vault.mkdir()
    conversations = tmp_path / "data" / "ui" / "conversations.json"
    conversations.parent.mkdir(parents=True)
    conversations.write_text('{"conversations": []}\n', encoding="utf-8")
    return KnowledgeCore(
        KnowledgeStore(
            tmp_path / "data" / "knowledge" / "core.db",
            tmp_path / "data" / "knowledge" / "blobs",
        ),
        conversations_path=conversations,
        vault_root=vault,
    )


def learning_request() -> BookUserLearningRequest:
    return BookUserLearningRequest(
        relationship=BookRelationshipEventInput(
            user_id="user-1",
            event_key="books:question:turn-17",
            action="book.questioned",
            actor=ObservationActor.USER,
            evidence_basis="interaction",
            book_ids=["work-meditations"],
            source_anchor_ids=["anchor-control"],
            conversation_ids=["turn-17"],
        ),
        candidates=[
            BookUserLearningCandidateInput(
                user_id="user-1",
                proposition_type="practical_need",
                proposition="The user may currently value ways to separate controllable from uncontrollable events.",
                basis="inferred",
                actor=ObservationActor.USER,
                evidence=[
                    BookUserLearningEvidenceReference(
                        kind="book_anchor",
                        reference_id="anchor-control",
                        stance="supports",
                    ),
                    BookUserLearningEvidenceReference(
                        kind="conversation",
                        reference_id="turn-17",
                        stance="supports",
                    ),
                    BookUserLearningEvidenceReference(
                        kind="book",
                        reference_id="work-opposing-view",
                        stance="conflicts",
                    ),
                ],
                confidence=0.62,
                scope="books",
                permitted_uses=["context", "wisdom"],
                derivation="books-agent-discussion",
                model_version="gpt-5.6-luna",
                prompt_version="books-user-learning-v1",
                policy_version="books-user-learning-policy-v1",
            )
        ],
    )


def test_records_relationship_and_proposed_candidate_idempotently(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    request = learning_request()

    first = core.record_book_user_learning(request)
    replay = core.record_book_user_learning(request)

    assert first["relationship"]["created"] is True
    assert replay["relationship"]["created"] is False
    assert first["candidates"][0]["created"] is True
    assert replay["candidates"][0]["created"] is False
    assert replay["candidates"][0]["candidate_id"] == first["candidates"][0]["candidate_id"]
    assert first["candidates"][0]["lifecycle"] == "proposed"
    assert "proposition" not in first["candidates"][0]

    stored = core.store.get_user_learning_candidate(
        user_id="user-1",
        candidate_id=first["candidates"][0]["candidate_id"],
    )
    assert stored is not None
    assert stored["lifecycle"] == "proposed"
    assert stored["basis"] == "inferred"
    assert {item["kind"] for item in stored["evidence"]} == {
        "book",
        "book_anchor",
        "conversation",
        "observation",
    }
    assert [item for item in stored["evidence"] if item["stance"] == "conflicts"] == [
        {
            "kind": "book",
            "reference_id": "work-opposing-view",
            "stance": "conflicts",
        }
    ]
    assert core.store.status()["counts"]["user_learning_candidates"] == 1
    assert core.store.status()["counts"]["user_learning_candidate_evidence"] == 4


def test_agent_processing_cannot_become_user_learning(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    request = learning_request().model_copy(
        update={
            "relationship": learning_request().relationship.model_copy(
                update={
                    "event_key": "books:processed:run-1",
                    "action": "book.processed",
                    "actor": ObservationActor.AGENT,
                    "evidence_basis": "agent_activity",
                }
            )
        }
    )

    with pytest.raises(ValueError, match="Agent Book activity cannot create user-learning candidates"):
        core.record_book_user_learning(request)

    assert core.store.count_observations(origin="books.user_learning") == 0
    assert core.store.status()["counts"]["user_learning_candidates"] == 0


@pytest.mark.parametrize(
    "action",
    ["book.imported", "book.questioned", "citation.inspected", "interface.page_flipped"],
)
def test_reading_status_requires_explicit_user_or_connector_evidence(
    tmp_path: Path,
    action: str,
) -> None:
    core = build_core(tmp_path)
    inferred_reading = learning_request().candidates[0].model_copy(
        update={
            "proposition_type": "reading_status",
            "proposition": "The user completed the Book.",
        }
    )
    request = learning_request().model_copy(
        update={
            "relationship": learning_request().relationship.model_copy(update={"action": action}),
            "candidates": [inferred_reading],
        }
    )

    with pytest.raises(ValueError, match="Reading status requires explicit user or connector evidence"):
        core.record_book_user_learning(request)

    assert core.store.count_observations(origin="books.user_learning") == 0


def test_sensitive_learning_requires_explicit_user_evidence() -> None:
    with pytest.raises(ValidationError, match="Sensitive learning requires explicit user evidence"):
        BookUserLearningCandidateInput.model_validate(
            {
                **learning_request().candidates[0].model_dump(),
                "sensitivity": "sensitive",
            }
        )


def test_temporary_learning_requires_a_time_bound() -> None:
    with pytest.raises(ValidationError, match="Temporary user learning requires a time bound"):
        BookUserLearningCandidateInput.model_validate(
            {
                **learning_request().candidates[0].model_dump(),
                "proposition_type": "current_situation",
            }
        )


def test_user_learning_contract_has_no_raw_evidence_field() -> None:
    with pytest.raises(ValidationError):
        BookUserLearningEvidenceReference.model_validate(
            {
                "kind": "conversation",
                "reference_id": "turn-17",
                "stance": "supports",
                "raw_text": "Private conversation text must not be copied here.",
            }
        )
