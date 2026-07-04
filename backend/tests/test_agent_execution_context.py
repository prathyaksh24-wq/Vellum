from datetime import UTC, datetime

from agent.agents.base import SpecialistResponse
from agent.agents.context import AgentExecutionContext, CancellationView, invoke_specialist
from agent.profiles import AgentProfile, IdentityStack


def context(goal: str = "NBA update") -> AgentExecutionContext:
    return AgentExecutionContext(
        run_id="run-1",
        task_id="task-1",
        parent_task_id=None,
        goal=goal,
        explicit_context="Only official sources",
        profile=AgentProfile(id="SportsAgent"),
        prompt_stack=IdentityStack((), "hash"),
        skills=(),
        memory_refs=(),
        task_room_id=None,
        deadline=datetime.now(UTC),
        max_iterations=10,
        cancellation=CancellationView(lambda: False),
    )


def test_invoke_specialist_prefers_typed_context() -> None:
    class ContextPupil:
        def answer_task(self, execution_context):
            assert execution_context.goal == "NBA update"
            return SpecialistResponse(agent="SportsAgent", status="answered", summary="context")

    assert invoke_specialist(ContextPupil(), context()).summary == "context"


def test_invoke_specialist_preserves_legacy_answer_contract() -> None:
    class LegacyPupil:
        def answer(self, query):
            return SpecialistResponse(agent="SportsAgent", status="answered", summary=query)

    assert invoke_specialist(LegacyPupil(), context()).summary == "NBA update"
