from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.agents.books import BooksAgent
from agent.contracts.books import BookClaim, BookEvidenceAnchor, BooksAgentEnvelope
from agent.master.runtime import DelegationRequest, DelegationRuntime
from agent.profiles import AgentCatalog, profile_policy
from agent.tools.capabilities.books_service import BooksCapabilityService


class FakeKnowledgeCore:
    def __init__(self, evidence: list[dict] | None = None) -> None:
        self.evidence = list(evidence or [])
        self.requests = []

    def create_context_pack(self, request):
        self.requests.append(request)
        return {
            "id": "ctx-books-1",
            "purpose": request.purpose,
            "destination": request.destination,
            "evidence": list(self.evidence),
            "policy": {"raw_private_content": "withheld"},
        }


class FakeSkillRegistry:
    def __init__(self, packages: list | None = None) -> None:
        self.packages = list(packages or [])

    def list_packages(self):
        return list(self.packages)


def build_agent(core: FakeKnowledgeCore, skills: FakeSkillRegistry | None = None) -> BooksAgent:
    service = BooksCapabilityService(
        knowledge_core_provider=lambda: core,
        skill_registry_provider=lambda: skills or FakeSkillRegistry(),
    )
    return BooksAgent(tool_registry=service.build_registry())


def test_books_agent_abstains_without_installed_book_evidence() -> None:
    core = FakeKnowledgeCore()
    response = build_agent(core).answer("What did the 45th law mean?")

    envelope = BooksAgentEnvelope.model_validate(response.structured_payload["books_agent"])
    assert response.agent == "BooksAgent"
    assert response.status == "needs_fetch"
    assert envelope.status == "abstained"
    assert envelope.claims == []
    assert envelope.evidence == []
    assert envelope.user_learning_events == []
    assert core.requests[0].destination == "external"
    assert core.requests[0].include_raw_content is False
    assert "book_page" in core.requests[0].source_kinds
    assert "obsidian" not in response.model_dump_json().casefold()


def test_books_agent_reports_matching_records_without_inventing_book_claims() -> None:
    core = FakeKnowledgeCore(
        [
            {
                "source_id": "src-book-1",
                "kind": "book_document",
                "title": "The 48 Laws of Power",
                "uri": "",
                "content_hash": "a" * 64,
                "observed_at": "2026-08-20T00:00:00+00:00",
                "published_at": "",
                "sensitivity": "private",
                "external_policy": "deny_raw",
                "content_withheld": True,
            }
        ]
    )

    response = build_agent(core).answer("What did the 45th law mean?")
    envelope = BooksAgentEnvelope.model_validate(response.structured_payload["books_agent"])

    assert response.status == "needs_fetch"
    assert envelope.status == "partial"
    assert envelope.claims == []
    assert response.sources[0].path_or_url == "knowledge://sources/src-book-1"
    assert "D:\\" not in response.model_dump_json()
    assert "C:\\" not in response.model_dump_json()


def test_books_skill_lookup_returns_only_hermes_skills_routed_to_books_agent() -> None:
    routed = SimpleNamespace(
        metadata=SimpleNamespace(
            name="naval-almanack",
            description="Book skill",
            version="1.0.0",
            metadata=SimpleNamespace(
                hermes=SimpleNamespace(category="books", tags=["naval"]),
                vellum=SimpleNamespace(route_to_agent="BooksAgent"),
            ),
        )
    )
    unrelated = SimpleNamespace(
        metadata=SimpleNamespace(
            name="sports-analysis",
            description="Sports skill",
            version="1.0.0",
            metadata=SimpleNamespace(
                hermes=SimpleNamespace(category="sports", tags=["sports"]),
                vellum=SimpleNamespace(route_to_agent="SportsAgent"),
            ),
        )
    )
    service = BooksCapabilityService(
        knowledge_core_provider=lambda: FakeKnowledgeCore(),
        skill_registry_provider=lambda: FakeSkillRegistry([routed, unrelated]),
    )

    with profile_policy(
        profile_id="BooksAgent",
        allowed_tools=frozenset({"books.skill_lookup"}),
        allowed_skills=frozenset({"naval-almanack"}),
    ):
        result = service.lookup_skills({"query": "Naval"})

    assert result == {
        "action": "books.skill_lookup",
        "skills": [
            {
                "name": "naval-almanack",
                "description": "Book skill",
                "version": "1.0.0",
                "category": "books",
                "tags": ["naval"],
            }
        ],
    }
    assert "package_root" not in str(result)


def test_books_envelope_rejects_quotation_without_validated_span() -> None:
    claim = BookClaim(
        id="claim-1",
        text="A direct quotation",
        origin="book",
        form="quotation",
        speaker="author",
        epistemic_status="asserted",
        evidence_ids=["evidence-1"],
    )

    with pytest.raises(ValidationError):
        BooksAgentEnvelope(
            answer="A direct quotation",
            answer_claim_ids=["claim-1"],
            claims=[claim],
            evidence=[
                BookEvidenceAnchor(
                    id="evidence-1",
                    source_id="src-book-1",
                    work_id="work-1",
                    locator_type="epub_cfi",
                    locator="epubcfi(/6/2)",
                )
            ],
            status="complete",
        )


def test_books_agent_reports_capability_failure_instead_of_missing_evidence() -> None:
    class FailingKnowledgeCore:
        def create_context_pack(self, request):
            _ = request
            raise RuntimeError("unavailable")

    response = build_agent(FailingKnowledgeCore()).answer("What does Meditations say?")
    envelope = BooksAgentEnvelope.model_validate(response.structured_payload["books_agent"])

    assert response.status == "error"
    assert envelope.status == "failed"
    assert "No matching" not in response.summary


def test_complete_books_envelope_requires_answer_claim_references() -> None:
    with pytest.raises(ValidationError):
        BooksAgentEnvelope(answer="A substantive answer", status="complete")


def test_delegation_runtime_executes_books_agent_under_profile_tool_policy(tmp_path) -> None:
    core = FakeKnowledgeCore(
        [
            {
                "source_id": "src-book-1",
                "kind": "book_document",
                "title": "Meditations",
                "uri": "",
                "content_hash": "b" * 64,
                "observed_at": "2026-08-20T00:00:00+00:00",
                "published_at": "",
                "sensitivity": "private",
                "external_policy": "deny_raw",
                "content_withheld": True,
            }
        ]
    )
    agent = build_agent(core)
    profile = AgentCatalog(profile_dir=tmp_path / "profiles").get("BooksAgent")
    runtime = DelegationRuntime(
        agent_catalog=AgentCatalog(
            profile_dir=tmp_path / "profiles",
            builtins={"BooksAgent": profile},
            executors={"BooksAgent": agent},
        ),
        memory_orchestrator=None,
        audit_path=tmp_path / "delegation-runs.jsonl",
    )

    result = runtime.delegate(
        DelegationRequest(
            agent_id="BooksAgent",
            task="What does Meditations say about control?",
            parent_thread_id="thread-books",
        )
    )

    assert result.response.status == "needs_fetch"
    assert result.response.structured_payload["books_agent"]["status"] == "partial"
    assert result.profile_id == "BooksAgent"
    assert result.cache_reason == "memory_orchestrator_unavailable"
