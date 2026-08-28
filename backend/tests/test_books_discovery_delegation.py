from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import json

import pytest
from pydantic import ValidationError

from agent.agents.books import BooksAgent
from agent.contracts.books import BooksDiscoveryTask
from agent.master.runtime import DelegationRequest, DelegationRuntime
from agent.master.state import MasterThreadStateStore
from agent.profiles import AgentCatalog, profile_policy
from agent.tools.capabilities.books_service import BooksCapabilityService
from agent.tools.registry import CapabilityAccess, ToolInvocation, ToolPermissionError
from agent.knowledge.tool_observer import KnowledgeToolObserver
from agent.tools.books import _response_json


class DiscoveryCore:
    def __init__(self):
        self.calls = []

    def discover_books(self, request, *, policy):
        self.calls.append((request, policy))
        return {"status": "completed", "mode": "shadow", "candidates": [
            {"title": "Unreleased candidate", "source_url": "https://openlibrary.org/works/OL1W"},
        ]}

    def verify_book_discovery_candidate(self, request, *, policy):
        self.calls.append((request, policy))
        return {"status": "completed", "mode": "shadow", "candidates": []}


def build_runtime(tmp_path, *, enabled=True, now=None):
    core = DiscoveryCore()
    service = BooksCapabilityService(knowledge_core_provider=lambda: core)
    base = AgentCatalog(profile_dir=tmp_path / "empty-profiles").get("BooksAgent")
    profile = base.model_copy(update={"book_discovery_network": enabled})
    agent = BooksAgent(tool_registry=service.build_registry())
    catalog = AgentCatalog(
        profile_dir=tmp_path / "profiles", builtins={"BooksAgent": profile}, executors={"BooksAgent": agent},
    )
    state = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    runtime = DelegationRuntime(
        agent_catalog=catalog, memory_orchestrator=None,
        pending_action_store=state, audit_path=tmp_path / "audit.jsonl", now=now,
    )
    return SimpleNamespace(core=core, service=service, runtime=runtime, state=state, profile=profile, agent=agent)


def proposal(**changes):
    return DelegationRequest(**{
        "agent_id": "BooksAgent", "task": "Run a shadow discovery evaluation.",
        "parent_thread_id": "thread-one", "user_id": "user-one",
        "book_discovery": BooksDiscoveryTask(operation="discover", query="philosophy"), **changes,
    })


def confirmation(**changes):
    return DelegationRequest(**{
        "agent_id": "BooksAgent", "task": "Confirm the pending action.",
        "parent_thread_id": "thread-one", "user_id": "user-one",
        "confirm_pending_action": True, **changes,
    })


def test_discovery_requires_one_shot_confirmation_and_returns_only_shadow_receipt(tmp_path):
    parts = build_runtime(tmp_path)
    prepared = parts.runtime.delegate(proposal())
    assert prepared.response.status == "blocked"
    assert prepared.response.action_request
    assert "philosophy" in prepared.response.summary
    assert parts.state.get_pending_action("thread-one")
    assert not parts.core.calls

    completed = parts.runtime.delegate(confirmation())
    assert completed.response.status == "answered"
    assert completed.cache_status == "bypass"
    assert len(parts.core.calls) == 1
    request, policy = parts.core.calls[0]
    assert request.user_id == "user-one"
    assert request.objective == "user_discovery"
    assert policy.network_allowed and policy.public_query_approved
    assert "Unreleased candidate" not in completed.response.model_dump_json()
    assert completed.response.sources == []
    assert completed.response.structured_payload["books_agent"]["claims"] == []
    assert completed.response.structured_payload["books_discovery"]["candidate_count"] == 1
    assert parts.runtime.delegate(confirmation()).response.status == "blocked"
    assert len(parts.core.calls) == 1


def test_new_profile_network_permission_defaults_off(tmp_path):
    assert not AgentCatalog(profile_dir=tmp_path).get("BooksAgent").book_discovery_network
    parts = build_runtime(tmp_path, enabled=False)
    result = parts.runtime.delegate(proposal())
    assert result.response.status == "blocked" and not result.response.action_request
    assert not parts.state.get_pending_action("thread-one")
    assert not parts.core.calls


@pytest.mark.parametrize("user,thread", [("other-user", "thread-one"), ("user-one", "other-thread")])
def test_other_user_or_thread_cannot_claim_confirmation(tmp_path, user, thread):
    parts = build_runtime(tmp_path)
    parts.runtime.delegate(proposal())
    result = parts.runtime.delegate(confirmation(user_id=user, parent_thread_id=thread))
    assert result.response.status == "blocked"
    assert parts.state.get_pending_action("thread-one")
    assert not parts.core.calls
    assert parts.runtime.delegate(confirmation()).response.status == "answered"


def test_approval_expiry_blocks_network(tmp_path):
    clock = [datetime(2026, 8, 28, tzinfo=UTC)]
    parts = build_runtime(tmp_path, now=lambda: clock[0])
    parts.runtime.delegate(proposal())
    clock[0] += timedelta(minutes=6)
    assert parts.runtime.delegate(confirmation()).response.status == "blocked"
    assert not parts.core.calls


@pytest.mark.parametrize("override", [{"book_discovery_network": False}, {"source_egress": "local"},
                                       {"tools": {"allow": ["books.knowledge_query"], "require_confirmation": []}},
                                       {"instructions": {"inline": "Changed profile instructions"}}])
def test_profile_change_revokes_pending_approval(tmp_path, override):
    parts = build_runtime(tmp_path)
    parts.runtime.delegate(proposal())
    profile_dir = parts.runtime.agent_catalog.profile_dir
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "BooksAgent.yaml").write_text(json.dumps({"id": "BooksAgent", **override}), encoding="utf-8")
    assert parts.runtime.delegate(confirmation()).response.status == "blocked"
    assert not parts.core.calls


def test_model_confirmation_flag_has_no_authority(tmp_path):
    parts = build_runtime(tmp_path)
    payload = {**proposal().book_discovery.model_dump(), "confirm": True}
    with pytest.raises(ToolPermissionError):
        parts.service.discover(payload)
    with profile_policy(
        profile_id="BooksAgent", user_id="user-one", source_egress="external",
        allowed_tools=frozenset({"books.discover"}), book_discovery_network=True,
    ):
        with pytest.raises(ToolPermissionError):
            parts.service.build_registry().invoke("books.discover", payload, agent_name="BooksAgent")
    assert not parts.core.calls


def test_confirmed_call_uses_stored_intent_not_new_task_text(tmp_path):
    parts = build_runtime(tmp_path)
    parts.runtime.delegate(proposal())
    result = parts.runtime.delegate(confirmation(task="Instead search for another private topic."))
    assert result.response.status == "answered"
    assert parts.core.calls[0][0].query == "philosophy"


def test_new_proposal_does_not_overwrite_pending_action(tmp_path):
    parts = build_runtime(tmp_path)
    existing = {"agent": "XAgent", "action": "x.publish_post", "payload": {"text": "pending"}}
    parts.state.set_pending_action("thread-one", existing)
    result = parts.runtime.delegate(proposal())
    assert result.response.status == "blocked" and not result.response.action_request
    assert parts.state.get_pending_action("thread-one") == existing


def test_discovery_does_not_use_cache_or_user_learning_sinks(tmp_path):
    parts = build_runtime(tmp_path)
    class ForbiddenCache:
        def lookup_specialist_response(self, **kwargs):
            pytest.fail("Discovery must not read specialist cache")
        def store_specialist_response(self, **kwargs):
            pytest.fail("Discovery must not enter specialist cache")
    parts.runtime.memory_orchestrator = ForbiddenCache()
    parts.runtime.user_learning_sink = lambda _: pytest.fail("Discovery is not user evidence")
    parts.runtime.wisdom_sink = lambda _: pytest.fail("Discovery is not Book Wisdom")
    parts.runtime.delegate(proposal())
    assert parts.runtime.delegate(confirmation()).response.status == "answered"


def test_task_contract_cannot_carry_approval_or_change_agent():
    with pytest.raises(ValidationError):
        BooksDiscoveryTask(operation="discover", query="philosophy", confirm=True)
    with pytest.raises(ValueError):
        proposal(agent_id="XAgent")
    with pytest.raises(ValueError):
        proposal(confirm_pending_action=True)


def test_pending_action_internal_identity_is_not_sent_to_main_model(tmp_path):
    parts = build_runtime(tmp_path)
    prepared = parts.runtime.delegate(proposal()).response
    public = _response_json(prepared)
    for private in ("user-one", "thread-one", "profile_fingerprint", "approval_id", "expires_at"):
        assert private not in public


def test_malformed_pending_action_blocks_without_logging_private_input(tmp_path, caplog):
    parts = build_runtime(tmp_path)
    parts.runtime.delegate(proposal())
    pending = parts.state.get_pending_action("thread-one")
    pending["expires_at"] = "private@example.com"
    parts.state.set_pending_action("thread-one", pending)
    assert parts.runtime.delegate(confirmation()).response.status == "blocked"
    assert "private@example.com" not in caplog.text
    assert not parts.core.calls


@pytest.mark.parametrize("name", ["books.discover", "books.verify_candidate"])
def test_discovery_is_not_reingested_by_generic_tool_learning(name):
    calls = []
    observer = KnowledgeToolObserver(SimpleNamespace(record_tool_result=lambda **kwargs: calls.append(kwargs)))
    observer(ToolInvocation(
        name=name, namespace="books", access=CapabilityAccess.READ, agent_name="BooksAgent",
        payload={"query": "philosophy"}, result={"status": "completed", "candidates": [{"title": "Candidate"}]},
    ))
    assert calls == []


def test_verification_delegation_keeps_candidate_identity_and_user_in_host_scope(tmp_path):
    parts = build_runtime(tmp_path)
    candidate_id = "book-discovery_" + "a" * 32
    intent = BooksDiscoveryTask(operation="verify", candidate_id=candidate_id)
    prepared = parts.runtime.delegate(proposal(book_discovery=intent))
    assert prepared.response.action_request["action"] == "books.verify_candidate"
    assert not parts.core.calls
    completed = parts.runtime.delegate(confirmation())
    assert completed.response.status == "answered"
    request, policy = parts.core.calls[0]
    assert request.user_id == "user-one" and request.candidate_id == candidate_id
    assert policy.network_allowed and policy.public_query_approved
    assert completed.response.structured_payload["books_discovery"]["operation"] == "verify"


def test_profile_grant_cannot_be_reused_for_different_operation_or_payload(tmp_path):
    parts = build_runtime(tmp_path)
    intent = proposal().book_discovery
    with profile_policy(
        profile_id="BooksAgent", user_id="user-one", source_egress="external",
        allowed_tools=frozenset({"books.discover", "books.verify_candidate"}), book_discovery_network=True,
        book_discovery_approval=intent.fingerprint(), book_discovery_request_key="opaque-grant",
    ):
        with pytest.raises(ToolPermissionError):
            parts.service.discover({**intent.model_dump(), "query": "different topic", "confirm": True})
        with pytest.raises(ValidationError):
            parts.service.discover({**intent.model_dump(), "user_id": "another-user", "confirm": True})
    assert not parts.core.calls
