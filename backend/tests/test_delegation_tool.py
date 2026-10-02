from __future__ import annotations

import json
from types import SimpleNamespace

from agent.agents.base import SpecialistResponse
from agent.profiles import AgentProfile
from agent.tools import delegation


class _Catalog:
    def __init__(self, profile):
        self.profile = profile

    def try_resolve(self, profile_id):
        if self.profile is None or self.profile.id != profile_id:
            return None
        return SimpleNamespace(profile=self.profile, executor=object())


class _PendingActions:
    def __init__(self):
        self.actions = []

    def set_pending_action(self, thread_id, action, *, replace=True):
        self.actions.append((thread_id, action, replace))
        return True


class _Runtime:
    def __init__(self, profile, response):
        self.agent_catalog = _Catalog(profile)
        self.pending_action_store = _PendingActions()
        self.response = response
        self.request = None

    def delegate(self, request):
        self.request = request
        return SimpleNamespace(response=self.response)


def test_delegation_tool_schema_is_small_and_excludes_runtime_state():
    fields = delegation.delegate_to_agent.args_schema.model_fields
    schema = delegation.delegate_to_agent.args_schema.model_json_schema()

    assert set(fields) == {"agent_id", "task", "context"}
    assert schema["properties"]["task"]["maxLength"] == 4000
    assert schema["properties"]["context"]["maxLength"] == 8000


def test_delegation_uses_shared_runtime_and_configured_thread(monkeypatch):
    profile = AgentProfile(id="ResearchAgent", description="Focused public research.")
    runtime = _Runtime(
        profile,
        SpecialistResponse(agent="ResearchAgent", status="answered", summary="Verified result."),
    )
    monkeypatch.setattr(delegation, "get_delegation_runtime", lambda: runtime)

    result = json.loads(
        delegation.delegate_to_agent.invoke(
            {
                "agent_id": "ResearchAgent",
                "task": "Check the launch date.",
                "context": "Use the official release page.",
            },
            config={"configurable": {"thread_id": "thread-7", "user_id": "user-3"}},
        )
    )

    assert result["agent"] == "ResearchAgent"
    assert result["summary"] == "Verified result."
    assert runtime.request.parent_thread_id == "thread-7"
    assert runtime.request.user_id == "user-3"
    assert runtime.request.context == "Use the official release page."


def test_summary_only_profile_withholds_private_result_content_and_stores_confirmation(monkeypatch):
    profile = AgentProfile(
        id="CalendarAgent",
        result_visibility="summary",
        tools={"allow": ["calendar.create_event"], "require_confirmation": ["calendar.create_event"]},
    )
    response = SpecialistResponse(
        agent="CalendarAgent",
        status="needs_fetch",
        summary="Create a confidential appointment for 10:30.",
        sources=[{"kind": "api", "title": "Private calendar", "path_or_url": "local-event-42"}],
        action_request={"action": "calendar.create_event", "title": "Private appointment"},
        structured_payload={"event_title": "Private appointment"},
    )
    runtime = _Runtime(profile, response)
    monkeypatch.setattr(delegation, "get_delegation_runtime", lambda: runtime)

    result_text = delegation.delegate_to_agent.invoke(
        {"agent_id": "CalendarAgent", "task": "Prepare the appointment change."},
        config={"configurable": {"thread_id": "calendar-thread"}},
    )
    result = json.loads(result_text)

    assert "confidential appointment" not in result_text
    assert "Private appointment" not in result_text
    assert "local-event-42" not in result_text
    assert result["privacy"] == "summary_only"
    assert result["action_request"] == {
        "action": "calendar.create_event",
        "requires_confirmation": True,
    }
    assert runtime.pending_action_store.actions == [
        (
            "calendar-thread",
            {"agent": "CalendarAgent", "action": "calendar.create_event", "title": "Private appointment"},
            False,
        )
    ]


def test_books_delegation_hides_memory_learning_candidates(monkeypatch):
    profile = AgentProfile(id="BooksAgent", response_schema="books-agent-response-v1")
    response = SpecialistResponse(
        agent="BooksAgent",
        status="answered",
        summary="The passage argues for patience.",
        structured_payload={
            "books_agent": {
                "answer": "Supported by chapter 2.",
                "user_learning_events": [{"statement": "Private belief candidate."}],
                "wisdom_proposals": [{"statement": "Private wisdom candidate."}],
            }
        },
    )
    runtime = _Runtime(profile, response)
    monkeypatch.setattr(delegation, "get_delegation_runtime", lambda: runtime)

    result_text = delegation.delegate_to_agent.invoke(
        {"agent_id": "BooksAgent", "task": "Explain this passage."},
    )
    result = json.loads(result_text)

    assert "Supported by chapter 2." in result_text
    assert "Private belief candidate." not in result_text
    assert "Private wisdom candidate." not in result_text
    assert result["structured_payload"]["books_agent"]["user_learning_events"] == []
    assert result["structured_payload"]["books_agent"]["wisdom_proposals"] == []


def test_delegation_rejects_profiles_outside_the_catalog(monkeypatch):
    runtime = _Runtime(None, SpecialistResponse(agent="Other", status="blocked", summary="No."))
    monkeypatch.setattr(delegation, "get_delegation_runtime", lambda: runtime)

    result = json.loads(
        delegation.delegate_to_agent.invoke(
            {"agent_id": "UnlistedAgent", "task": "Do work."},
        )
    )

    assert result["status"] == "blocked"
    assert runtime.request is None
