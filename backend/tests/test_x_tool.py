import json

from agent.agents.base import SpecialistResponse
from agent.tools import x as x_tool


class FakeXAgent:
    def __init__(self, response):
        self.response = response
        self.queries = []

    def answer(self, query):
        self.queries.append(query)
        return self.response


def test_x_agent_tool_delegates_to_specialist(monkeypatch):
    runtime = FakeXAgent(
        SpecialistResponse(
            agent="XAgent",
            status="answered",
            summary="X result",
            analysis="Used Agent-Reach.",
            confidence=0.8,
        )
    )
    monkeypatch.setattr(x_tool, "_build_x_agent", lambda: runtime)

    result = json.loads(x_tool.x_agent.func(query="Search X for Vellum"))

    assert runtime.queries == ["Search X for Vellum"]
    assert result["agent"] == "XAgent"
    assert result["summary"] == "X result"


def test_x_agent_tool_preserves_confirmation_request(monkeypatch):
    runtime = FakeXAgent(
        SpecialistResponse(
            agent="XAgent",
            status="blocked",
            summary="Confirm before posting.",
            action_request={"action": "x.publish_post", "payload": {"text": "hello"}},
        )
    )
    monkeypatch.setattr(x_tool, "_build_x_agent", lambda: runtime)

    result = json.loads(x_tool.x_agent.func(query='Post "hello" on X'))

    assert result["status"] == "blocked"
    assert result["action_request"]["action"] == "x.publish_post"


def test_x_agent_tool_rejects_empty_queries_without_building_runtime(monkeypatch):
    monkeypatch.setattr(x_tool, "_build_x_agent", lambda: (_ for _ in ()).throw(AssertionError("not called")))

    result = json.loads(x_tool.x_agent.func(query="   "))

    assert result["status"] == "blocked"
    assert result["summary"] == "XAgent requires a query."


def test_x_agent_tool_does_not_expose_runtime_errors(monkeypatch):
    class FailingXAgent:
        def answer(self, _query):
            raise RuntimeError("TEST_MARKER_NOT_A_CREDENTIAL")

    monkeypatch.setattr(x_tool, "_build_x_agent", FailingXAgent)

    result = x_tool.x_agent.func(query="Search X")

    assert "TEST_MARKER_NOT_A_CREDENTIAL" not in result
    assert json.loads(result)["status"] == "error"


def test_x_agent_tool_persists_pending_confirmation_with_thread_config(monkeypatch):
    runtime = FakeXAgent(
        SpecialistResponse(
            agent="XAgent",
            status="blocked",
            summary="Confirm before posting.",
            action_request={"action": "x.publish_post", "payload": {"text": "hello"}},
        )
    )

    class FakePendingStore:
        def __init__(self):
            self.calls = []

        def set_pending_action(self, thread_id, action):
            self.calls.append((thread_id, action))

    store = FakePendingStore()
    monkeypatch.setattr(x_tool, "_build_x_agent", lambda: runtime)
    monkeypatch.setattr(x_tool, "_pending_action_store", store)

    result = json.loads(
        x_tool.x_agent.func(
            query='Post "hello" on X',
            config={"configurable": {"thread_id": "thread-1"}},
        )
    )

    assert result["status"] == "blocked"
    assert store.calls == [
        (
            "thread-1",
            {
                "agent": "XAgent",
                "action": "x.publish_post",
                "payload": {"text": "hello"},
            },
        )
    ]
