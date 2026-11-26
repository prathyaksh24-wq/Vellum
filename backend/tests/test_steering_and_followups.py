"""Follow-up steering, smart background names, rail surface and routing fixes."""
import asyncio
import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.app_actions.runtime import AppActionRuntime, SurfaceActionError
from agent.app_actions.settings_runtime import resolve_background
from agent.graph.steering import SteeringInbox
from agent.privacy.scrubber import _looks_like_credit_card
from tests.test_routing_engine import FakeStatusError, add_credential, build_engine


def test_steer_waits_for_a_running_turn_and_is_drained_once():
    inbox = SteeringInbox()
    assert inbox.submit("t1", "also add a haiku") is None  # nothing running: send normally
    inbox.begin("t1")
    held = inbox.submit("t1", "also add a haiku", "s1")
    assert held is not None and held.id == "s1"
    assert [message.text for message in inbox.drain("t1")] == ["also add a haiku"]
    assert inbox.drain("t1") == []
    inbox.end("t1")
    assert not inbox.is_active("t1")


def test_unread_steer_is_reclaimed_after_the_turn():
    inbox = SteeringInbox()
    inbox.begin("t2")
    inbox.submit("t2", "one more thing", "s2")
    inbox.end("t2")
    reclaimed = inbox.reclaim("t2", "s2")
    assert reclaimed is not None and reclaimed.text == "one more thing"
    assert inbox.reclaim("t2", "s2") is None


@pytest.mark.parametrize(("request_text", "current", "expected"), [
    ("clouds", "galaxy", "drifting-clouds"),
    ("clouds", "drifting-clouds", "ember-clouds"),   # asking again moves to the other cloud background
    ("the clouds one", "ember-clouds", "drifting-clouds"),
    ("gold rays", "", "god-rays"),
    ("Ember Clouds", "", "ember-clouds"),
    ("forest", "", "evergreen"),
])
def test_background_names_resolve_to_registered_backgrounds(request_text, current, expected):
    assert resolve_background(request_text, current)[0] == expected


def test_unknown_background_has_no_match():
    assert resolve_background("xyzzy", "galaxy") == (None, [])


def test_navigation_rail_hides_registered_items_only():
    runtime = AppActionRuntime()
    rail = next(surface for surface in runtime.catalog().surfaces if surface.reference == "navigation-rail")
    schema = rail.configurable_properties["hidden_items"]
    assert runtime._validate_property(rail, "hidden_items", ["Search", "search", "notifications"], schema) == ["search", "notifications"]
    with pytest.raises(SurfaceActionError):
        runtime._validate_property(rail, "hidden_items", ["avatar"], schema)


def test_dates_are_not_card_numbers():
    text = "Python 3.13 released 2024-10-07 2029-10 end of life"
    match = re.search(r"\b(?:\d[ -]*){13,19}\b", text)
    assert match and not _looks_like_credit_card(text, match)
    card = "4111 1111 1111 1111"
    assert _looks_like_credit_card(card, re.search(r"\b(?:\d[ -]*){13,19}\b", card))


def test_tools_are_dropped_only_after_the_relaxed_route_also_fails(tmp_path):
    async def scenario():
        store, engine, adapter, openai = build_engine(
            tmp_path,
            openrouter_outcomes=[
                FakeStatusError(404, "no endpoints found that can handle the requested parameters"),
                FakeStatusError(404, "no endpoints found that can handle the requested parameters"),
                AIMessage(content="plain answer"),
            ],
        )
        add_credential(store, "openrouter", "or-key")
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
        result = await engine.ainvoke(messages=[HumanMessage(content="hello")], primary_model="google/primary", tools=tools)
        assert result.content == "plain answer"
        assert adapter.bound_tools_history == [tools, tools]  # strict + relaxed with tools, then without
        assert len(adapter.calls) == 3

    asyncio.run(scenario())


def test_skill_view_unlocks_the_hidden_tools_it_names():
    from agent.tools.tool_search import activate_discovered_tool_defs, build_catalog

    hidden = [{"type": "function", "function": {"name": "skill_hub", "description": "Search and install skills", "parameters": {"type": "object"}}}]
    catalog = build_catalog(hidden)
    messages = [
        HumanMessage(content="install a skill"),
        AIMessage(content="", tool_calls=[{"name": "skill_view", "args": {"name": "skill-installer"}, "id": "c1"}]),
        ToolMessage(content='{"content": "2. Use `skill_hub(action=\\"search\\")` for discovery."}', name="skill_view", tool_call_id="c1"),
    ]
    visible = activate_discovered_tool_defs([], catalog, messages)
    assert [item["function"]["name"] for item in visible] == ["skill_hub"]


def test_capability_denial_without_a_tool_call_is_sent_back():
    from agent.graph.agent import _denied_capability_without_trying

    denial = {"messages": [HumanMessage(content="remove search from the rail", id="h1"),
                           AIMessage(content="I can't change that because the Vellum settings action isn't available in this session.")]}
    assert _denied_capability_without_trying(denial)
    tried = {"messages": [HumanMessage(content="remove search", id="h1"),
                          AIMessage(content="", tool_calls=[{"name": "app_action", "args": {}, "id": "c1"}]),
                          ToolMessage(content='{"status":"unavailable"}', name="app_action", tool_call_id="c1"),
                          AIMessage(content="That control isn't available: app_action returned unavailable.")]}
    assert not _denied_capability_without_trying(tried)


def test_surface_reference_is_inferred_from_rail_only_properties():
    from agent.app_actions.models import AppActionContext
    runtime = AppActionRuntime()
    context = AppActionContext(source="nlp")
    assert runtime._infer_surface_reference({"properties": {"hidden_items": ["search"]}}, context) == "navigation-rail"
    with pytest.raises(SurfaceActionError) as raised:
        runtime._infer_surface_reference({"visible": False}, context)
    assert raised.value.code == "UI_REFERENCE_REQUIRED" and "navigation-rail" in str(raised.value)


def test_unrelated_unavailability_is_not_a_capability_denial():
    from agent.graph.agent import _denied_capability_without_trying
    state = {"messages": [HumanMessage(content="can I stream Dune?", id="h1"),
                          AIMessage(content="Dune is not available on Netflix in India right now.")]}
    assert not _denied_capability_without_trying(state)
