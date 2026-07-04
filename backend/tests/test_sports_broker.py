from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from types import SimpleNamespace
from agent.agents.sports import SportsAgent
from agent.runtime.brokers import BrokerPermissionError, ToolBroker
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


def _search_result(query: str):
    return {
        "text": "NBA result",
        "sources": [{"title": "Official", "url": "https://nba.example/game", "snippet": query}],
    }


def test_sports_agent_uses_broker_in_supervised_context(tmp_path: Path):
    calls = []
    registry = ToolRegistry()
    registry.register(CapabilityRecord(
        name="sports.search", namespace="sports", access=CapabilityAccess.READ,
        allowed_agents=frozenset({"SportsAgent"}), stream_label="Searched sports",
        adapter=lambda payload: calls.append(payload) or _search_result(payload["query"]),
    ))
    broker = ToolBroker(registry)
    grant = broker.issue_grant(agent_name="SportsAgent", run_id="run", task_id="task", allowed_tools={"sports.search"}, expires_at=datetime.now(UTC) + timedelta(minutes=1))
    context = SimpleNamespace(run_id="run", task_id="task", capability_token=grant.token, tool_broker=broker)
    agent = SportsAgent(tmp_path, web_searcher=lambda query: (_ for _ in ()).throw(AssertionError("direct search called")))

    response = agent.answer("latest NBA score", context=context)

    assert response.status == "answered"
    assert calls


def test_sports_agent_rejects_disallowed_supervised_search(tmp_path: Path):
    broker = ToolBroker(ToolRegistry())
    grant = broker.issue_grant(agent_name="SportsAgent", run_id="run", task_id="task", allowed_tools=set())
    context = SimpleNamespace(run_id="run", task_id="task", capability_token=grant.token, tool_broker=broker)

    with pytest.raises(BrokerPermissionError, match="capability unavailable"):
        SportsAgent(tmp_path).answer("latest NBA score", context=context)
