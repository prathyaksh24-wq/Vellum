from agent.agents.base import SpecialistResponse
from agent.agents.orchestrator import SpecialistOrchestrator


class FakeAgent:
    name = "FakeAgent"

    def __init__(self, can_handle=True):
        self.calls = 0
        self._can_handle = can_handle

    def can_handle(self, query):
        return self._can_handle

    def answer(self, query):
        self.calls += 1
        return SpecialistResponse(agent=self.name, status="answered", summary=f"handled {query}", confidence=0.8)


def test_orchestrator_delegates_to_first_matching_agent():
    first = FakeAgent(can_handle=True)
    second = FakeAgent(can_handle=True)
    orchestrator = SpecialistOrchestrator([first, second], max_depth=1, max_concurrency=1)

    result = orchestrator.delegate("sports update")

    assert result.agent == "FakeAgent"
    assert result.summary == "handled sports update"
    assert first.calls == 1
    assert second.calls == 0


def test_orchestrator_returns_blocked_when_depth_exceeded():
    agent = FakeAgent(can_handle=True)
    orchestrator = SpecialistOrchestrator([agent], max_depth=1, max_concurrency=1)

    result = orchestrator.delegate("sports update", depth=1)

    assert result.status == "blocked"
    assert "depth" in result.summary.lower()
    assert agent.calls == 0


def test_orchestrator_returns_needs_fetch_when_no_agent_matches():
    agent = FakeAgent(can_handle=False)
    orchestrator = SpecialistOrchestrator([agent], max_depth=1, max_concurrency=1)

    result = orchestrator.delegate("general question")

    assert result.agent == "VellumAgent"
    assert result.status == "needs_fetch"
