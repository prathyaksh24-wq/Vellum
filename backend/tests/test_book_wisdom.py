from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.knowledge.models import (
    BookRelationshipEventInput,
    BookUserLearningCandidateInput,
    BookUserLearningEvidenceReference,
    BookUserLearningRequest,
    BookWisdomEvidenceReference,
    BookWisdomRecordInput,
    ObservationActor,
    UserLearningSensitivity,
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


def learning_candidate(
    core: KnowledgeCore,
    *,
    user_id: str = "user-1",
    wisdom_allowed: bool = True,
    sensitive: bool = False,
) -> str:
    result = core.record_book_user_learning(
        BookUserLearningRequest(
            relationship=BookRelationshipEventInput(
                user_id=user_id,
                event_key=f"books:question:{user_id}:turn-21",
                action="user.statement_recorded" if sensitive else "idea.discussed",
                actor=ObservationActor.USER,
                evidence_basis="explicit" if sensitive else "interaction",
                book_ids=["work-meditations"],
                source_anchor_ids=["anchor-control"],
                conversation_ids=["turn-21"],
            ),
            candidates=[
                BookUserLearningCandidateInput(
                    user_id=user_id,
                    proposition_type="practical_need",
                    proposition="The user may value a clearer boundary between control and external events.",
                    basis="explicit" if sensitive else "inferred",
                    actor=ObservationActor.USER,
                    evidence=[
                        BookUserLearningEvidenceReference(
                            kind="book_anchor",
                            reference_id="anchor-control",
                        ),
                        BookUserLearningEvidenceReference(
                            kind="conversation",
                            reference_id="turn-21",
                        ),
                    ],
                    confidence=0.64,
                    sensitivity="sensitive" if sensitive else "private",
                    permitted_uses=["context", "wisdom"] if wisdom_allowed else ["context"],
                    derivation="books-agent-discussion",
                    prompt_version="books-user-learning-v1",
                    policy_version="books-user-learning-policy-v1",
                )
            ],
        )
    )
    return str(result["candidates"][0]["candidate_id"])


def wisdom_input(candidate_id: str, *, user_id: str = "user-1") -> BookWisdomRecordInput:
    return BookWisdomRecordInput(
        user_id=user_id,
        wisdom_type="useful_principle",
        title="Separate agency from circumstance",
        content="The distinction may help frame the current situation without denying its difficulty.",
        author_perspective="The author argues that judgment and response remain within one's agency.",
        user_perspective="The user described the distinction as relevant to a current difficulty.",
        vellum_perspective="The principle is useful if it supports action rather than emotional avoidance.",
        explanation="This connects a source-grounded principle to the user's stated need while preserving a counterpoint.",
        evidence=[
            BookWisdomEvidenceReference(
                kind="book_anchor",
                reference_id="anchor-control",
                stance="supports",
            ),
            BookWisdomEvidenceReference(
                kind="user_learning_candidate",
                reference_id=candidate_id,
                stance="supports",
            ),
            BookWisdomEvidenceReference(
                kind="book_anchor",
                reference_id="anchor-avoidance-counterpoint",
                stance="conflicts",
            ),
        ],
        confidence=0.68,
        uncertainty=["The current situation may require external action as well as reframing."],
        permitted_uses=["context", "discussion"],
        derivation="books-wisdom-synthesis",
        model_version="gpt-5.6-luna",
        prompt_version="books-wisdom-v1",
        policy_version="books-wisdom-policy-v1",
    )


def test_proposes_private_wisdom_with_stable_identity_and_evidence(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    candidate_id = learning_candidate(core)
    request = wisdom_input(candidate_id)

    first = core.propose_book_wisdom(request)
    replay = core.propose_book_wisdom(request)

    assert first["created"] is True
    assert replay["created"] is False
    assert replay["wisdom_id"] == first["wisdom_id"]
    assert first["lifecycle"] == "proposed"
    assert first["evidence_count"] == 3
    assert "content" not in first
    assert "author_perspective" not in first
    assert "user_perspective" not in first
    assert "vellum_perspective" not in first

    stored = core.store.get_book_wisdom_record(
        user_id="user-1",
        wisdom_id=first["wisdom_id"],
    )
    assert stored is not None
    assert stored["insight_type"] == "book_wisdom"
    assert stored["classification"] == "useful_principle"
    assert stored["status"] == "proposed"
    assert stored["external_allowed"] is False
    assert stored["author_perspective"].startswith("The author argues")
    assert stored["user_perspective"].startswith("The user described")
    assert stored["vellum_perspective"].startswith("The principle is useful")
    assert {item["stance"] for item in stored["evidence"]} == {"supports", "conflicts"}
    assert core.store.status()["counts"]["derived_insights"] == 1
    assert core.store.status()["counts"]["derived_insight_evidence"] == 3


def test_wisdom_requires_book_and_user_evidence(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    candidate_id = learning_candidate(core)
    without_book = wisdom_input(candidate_id).model_copy(
        update={
            "evidence": [
                BookWisdomEvidenceReference(
                    kind="user_learning_candidate",
                    reference_id=candidate_id,
                ),
                BookWisdomEvidenceReference(
                    kind="conversation",
                    reference_id="turn-21",
                ),
            ]
        }
    )

    with pytest.raises(ValueError, match="Book Wisdom requires supporting Book anchor evidence"):
        core.propose_book_wisdom(without_book)

    assert core.store.status()["counts"]["derived_insights"] == 0


def test_wisdom_rejects_cross_user_or_unpermitted_learning(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    other_user_candidate = learning_candidate(core, user_id="user-2")

    with pytest.raises(ValueError, match="same-user learning candidate"):
        core.propose_book_wisdom(wisdom_input(other_user_candidate))

    local_candidate = learning_candidate(core, user_id="user-1", wisdom_allowed=False)
    with pytest.raises(ValueError, match="not permitted for Wisdom"):
        core.propose_book_wisdom(wisdom_input(local_candidate))

    assert core.store.status()["counts"]["derived_insights"] == 0


def test_wisdom_evidence_cannot_embed_raw_text_or_reference_wisdom() -> None:
    with pytest.raises(ValidationError):
        BookWisdomEvidenceReference.model_validate(
            {
                "kind": "book_anchor",
                "reference_id": "anchor-control",
                "stance": "supports",
                "raw_text": "Private source text must not be copied into the evidence link.",
            }
        )

    with pytest.raises(ValidationError):
        BookWisdomEvidenceReference.model_validate(
            {
                "kind": "wisdom",
                "reference_id": "wisdom-self-reference",
                "stance": "supports",
            }
        )


def test_wisdom_cannot_reduce_sensitivity_or_gain_proactive_permission(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    sensitive_candidate = learning_candidate(core, sensitive=True)

    with pytest.raises(ValueError, match="cannot reduce user-evidence sensitivity"):
        core.propose_book_wisdom(wisdom_input(sensitive_candidate))

    sensitive_wisdom = wisdom_input(sensitive_candidate).model_copy(
        update={"sensitivity": UserLearningSensitivity.SENSITIVE}
    )
    stored = core.propose_book_wisdom(sensitive_wisdom)
    assert stored["lifecycle"] == "proposed"

    with pytest.raises(ValidationError):
        BookWisdomRecordInput.model_validate(
            {
                **wisdom_input(sensitive_candidate).model_dump(),
                "permitted_uses": ["proactive"],
            }
        )


def test_situational_wisdom_requires_a_time_bound(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    candidate_id = learning_candidate(core)

    with pytest.raises(ValidationError, match="Situational Wisdom requires a time bound"):
        BookWisdomRecordInput.model_validate(
            {
                **wisdom_input(candidate_id).model_dump(),
                "wisdom_type": "situational_connection",
            }
        )
