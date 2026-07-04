from langchain_core.messages import AIMessage

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.master.hybrid import HybridExecutor

from test_agent_execution_context import context


def test_hybrid_preserves_acquisition_evidence_and_uses_identity() -> None:
    calls = []

    class Model:
        def invoke(self, messages):
            calls.append(messages)
            return AIMessage(content="Independent tactical assessment")

    acquisition = SpecialistResponse(
        agent="SportsAgent",
        status="answered",
        summary="Raw result",
        confidence=0.9,
        sources=[SpecialistSource(kind="web", title="Official", path_or_url="https://example.com")],
    )

    result = HybridExecutor(lambda _model=None: Model()).refine(context(), acquisition)

    assert result.summary == "Independent tactical assessment"
    assert result.sources == acquisition.sources
    assert calls


def test_hybrid_never_replays_pending_actions() -> None:
    class FailingModel:
        def invoke(self, messages):
            raise AssertionError("model must not run for actions")

    acquisition = SpecialistResponse(
        agent="XAgent",
        status="answered",
        summary="Confirm post",
        action_request={"action": "x.post"},
    )

    assert HybridExecutor(lambda _model=None: FailingModel()).refine(context(), acquisition) == acquisition


def test_hybrid_falls_back_on_model_failure() -> None:
    class FailingModel:
        def invoke(self, messages):
            raise RuntimeError("offline")

    acquisition = SpecialistResponse(agent="SportsAgent", status="answered", summary="Raw result")

    result = HybridExecutor(lambda _model=None: FailingModel()).refine(context(), acquisition)

    assert result.summary == "Raw result"
    assert "hybrid fallback" in result.analysis
