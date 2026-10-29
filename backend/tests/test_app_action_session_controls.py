from datetime import datetime, timezone
from types import SimpleNamespace

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.app_actions.session_controls import (
    AGENT_SELECT_ACTION_ID,
    MEMORY_CONVERSATION_SET_ACTION_ID,
    MODEL_SELECT_ACTION_ID,
    REASONING_SET_ACTION_ID,
    SessionControlService,
)
from agent.master.state import MasterThreadStateStore
from agent.profiles import AgentCatalog, AgentProfile


class FakeProviderRegistry:
    def __init__(self) -> None:
        self.models = [
            SimpleNamespace(id="google/gemma-4-31b-it", label="Gemma 4 31B", provider="google"),
        ]

    def resolve(self, query: str):
        normalized = query.strip().casefold()
        return next(
            (model for model in self.models if normalized in {model.id.casefold(), model.label.casefold(), "gemma"}),
            None,
        )

    def list_models(self):
        return list(self.models)


def make_runtime(tmp_path):
    state_store = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    x_profile = AgentProfile(id="XAgent")
    calendar_profile = AgentProfile(id="CalendarAgent")
    market_research_profile = AgentProfile(id="MarketResearchAgent")
    catalog = AgentCatalog(
        profile_dir=tmp_path / "profiles",
        builtins={
            "XAgent": x_profile,
            "CalendarAgent": calendar_profile,
            "MarketResearchAgent": market_research_profile,
        },
        executors={
            "XAgent": SimpleNamespace(),
            "CalendarAgent": SimpleNamespace(),
            "MarketResearchAgent": SimpleNamespace(),
        },
    )
    service = SessionControlService(
        agent_catalog=catalog,
        state_store=state_store,
        provider_registry=FakeProviderRegistry(),
    )
    runtime = AppActionRuntime(
        clock=lambda: datetime(2026, 9, 12, tzinfo=timezone.utc),
        confirmation_token_factory=lambda: "confirm-memory",
        session_control_handler=service.execute,
    )
    return runtime, state_store


def context(thread_id="chat-1", source="nlp"):
    return AppActionContext(source=source, invocation_conversation_id=thread_id)


def test_nlp_matcher_exposes_agent_model_reasoning_and_chat_memory_actions(tmp_path) -> None:
    runtime, _store = make_runtime(tmp_path)

    assert runtime.match_submission("switch to X agent").action_id == AGENT_SELECT_ACTION_ID
    assert runtime.match_submission("switch to Calendar agent").arguments == {"agent": "calendar"}
    assert runtime.match_submission("open Market Research agent").arguments == {"agent": "market research"}
    assert runtime.match_submission("use the model Gemma 4 31B").action_id == MODEL_SELECT_ACTION_ID
    assert runtime.match_submission("set reasoning to extra high").arguments == {"mode": "extra high"}
    assert runtime.match_submission("turn memory off for this chat").arguments == {"enabled": False}
    assert runtime.match_submission("what do you remember about me?") is None


def test_catalog_agents_resolve_from_spoken_names_without_fixed_aliases(tmp_path) -> None:
    runtime, state_store = make_runtime(tmp_path)

    calendar = runtime.dispatch(
        AppActionRequest(action_id=AGENT_SELECT_ACTION_ID, arguments={"agent": "calendar"}),
        context(),
    )
    market_research = runtime.dispatch(
        AppActionRequest(action_id=AGENT_SELECT_ACTION_ID, arguments={"agent": "market research"}),
        context(),
    )

    assert calendar.status == "applied"
    assert calendar.result["active_agent"] == "CalendarAgent"
    assert calendar.result["session_control_patch"] == {"agent_id": "calendar"}
    assert market_research.status == "applied"
    assert market_research.result["active_agent"] == "MarketResearchAgent"
    assert market_research.result["session_control_patch"] == {"agent_id": "marketresearch"}
    assert state_store.get("chat-1").active_agent == "MarketResearchAgent"


def test_session_controls_persist_to_the_existing_thread_state_owner(tmp_path) -> None:
    runtime, state_store = make_runtime(tmp_path)

    receipts = runtime.dispatch_many(
        [
            AppActionRequest(action_id=AGENT_SELECT_ACTION_ID, arguments={"agent": "x"}),
            AppActionRequest(action_id=MODEL_SELECT_ACTION_ID, arguments={"model": "Gemma"}),
            AppActionRequest(action_id=REASONING_SET_ACTION_ID, arguments={"mode": "high"}),
            AppActionRequest(action_id=MEMORY_CONVERSATION_SET_ACTION_ID, arguments={"enabled": False}),
        ],
        context(),
    )

    assert [receipt.status for receipt in receipts] == ["applied"] * 4
    persisted = MasterThreadStateStore(sessions_db=state_store.sessions_db).get("chat-1")
    assert persisted.active_agent == "XAgent"
    assert persisted.agent_selected is True
    assert persisted.selected_model == "google/gemma-4-31b-it"
    assert persisted.reasoning_mode == "high"
    assert persisted.store_to_memory is False
    assert receipts[0].result["session_control_patch"] == {"agent_id": "x"}
    assert receipts[1].result["turn_overrides"] == {"model": "google/gemma-4-31b-it"}


def test_enabling_chat_memory_requires_operation_bound_confirmation(tmp_path) -> None:
    runtime, state_store = make_runtime(tmp_path)
    state_store.set_store_to_memory("chat-1", False)
    request = AppActionRequest(
        request_id="memory-on",
        action_id=MEMORY_CONVERSATION_SET_ACTION_ID,
        arguments={"enabled": True},
    )

    pending = runtime.dispatch(request, context())
    mismatched = runtime.confirm("confirm-memory", request, context("another-chat"))
    still_disabled = state_store.get("chat-1").store_to_memory
    confirmed = runtime.confirm("confirm-memory", request, context())

    assert pending.status == "confirmation_required"
    assert pending.authorization.confirmation_required is True
    assert mismatched.error_code == "CONFIRMATION_MISMATCH"
    assert still_disabled is False
    assert confirmed.status == "applied"
    assert state_store.get("chat-1").store_to_memory is True


def test_unavailable_agents_and_models_return_truthful_receipts(tmp_path) -> None:
    runtime, _store = make_runtime(tmp_path)

    agent = runtime.dispatch(
        AppActionRequest(action_id=AGENT_SELECT_ACTION_ID, arguments={"agent": "research"}),
        context(),
    )
    model = runtime.dispatch(
        AppActionRequest(action_id=MODEL_SELECT_ACTION_ID, arguments={"model": "Imaginary 9000"}),
        context(),
    )

    assert (agent.status, agent.error_code) == ("unavailable", "AGENT_UNAVAILABLE")
    assert (model.status, model.error_code) == ("unavailable", "MODEL_UNAVAILABLE")
