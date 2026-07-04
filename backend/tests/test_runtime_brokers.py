from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.runtime.brokers import (
    BrokerPermissionError,
    CredentialBroker,
    FilesystemBroker,
    NetworkBroker,
    TerminalBroker,
    ToolBroker,
)
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="sports.search",
            namespace="sports",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"SportsAgent"}),
            stream_label="Searched sports",
            adapter=lambda payload: {"query": payload["query"]},
        )
    )
    return registry


def test_tool_grant_binds_actor_run_task_expiry_and_can_be_revoked():
    broker = ToolBroker(_registry())
    grant = broker.issue_grant(
        agent_name="SportsAgent",
        run_id="run-1",
        task_id="task-1",
        allowed_tools={"sports.search"},
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    assert broker.invoke(grant.token, actor="SportsAgent", run_id="run-1", task_id="task-1", tool_name="sports.search", payload={"query": "nba"}) == {"query": "nba"}
    with pytest.raises(BrokerPermissionError, match="capability unavailable"):
        broker.invoke(grant.token, actor="XAgent", run_id="run-1", task_id="task-1", tool_name="sports.search", payload={"query": "nba"})
    broker.revoke(grant.token)
    with pytest.raises(BrokerPermissionError, match="capability unavailable"):
        broker.invoke(grant.token, actor="SportsAgent", run_id="run-1", task_id="task-1", tool_name="sports.search", payload={"query": "nba"})


def test_tool_grant_only_narrows_registry_policy_and_expired_grants_fail():
    broker = ToolBroker(_registry())
    narrow = broker.issue_grant(agent_name="SportsAgent", run_id="r", task_id="t", allowed_tools=set())
    with pytest.raises(BrokerPermissionError, match="capability unavailable"):
        broker.invoke(narrow.token, actor="SportsAgent", run_id="r", task_id="t", tool_name="sports.search", payload={"query": "nba"})

    expired = broker.issue_grant(
        agent_name="SportsAgent", run_id="r", task_id="t", allowed_tools={"sports.search"},
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(BrokerPermissionError, match="capability unavailable"):
        broker.invoke(expired.token, actor="SportsAgent", run_id="r", task_id="t", tool_name="sports.search", payload={"query": "nba"})


def test_filesystem_broker_rejects_traversal_and_symlink_escape(tmp_path: Path):
    root = tmp_path / "home"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    broker = FilesystemBroker({"SportsAgent": (root,)})

    assert broker.resolve("SportsAgent", root / "note.md") == (root / "note.md").resolve()
    with pytest.raises(BrokerPermissionError, match="path unavailable"):
        broker.resolve("SportsAgent", root / ".." / "secret.txt")
    link = root / "escape"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(BrokerPermissionError, match="path unavailable"):
        broker.resolve("SportsAgent", link)


def test_network_terminal_and_credentials_are_scoped(tmp_path: Path):
    network = NetworkBroker({"SportsAgent": {"api.example.test"}})
    assert network.authorize("SportsAgent", "https://api.example.test/scores") == "https://api.example.test/scores"
    with pytest.raises(BrokerPermissionError, match="network unavailable"):
        network.authorize("SportsAgent", "https://evil.test/")

    terminal = TerminalBroker({"SportsAgent": tmp_path / "sports"}, runner=lambda argv, cwd: (tuple(argv), cwd))
    argv, cwd = terminal.run("SportsAgent", ["python", "job.py"])
    assert argv == ("python", "job.py")
    assert cwd == (tmp_path / "sports").resolve()

    credentials = CredentialBroker({("SportsAgent", "sports.search"): lambda: "secret"})
    assert credentials.perform("SportsAgent", "sports.search", lambda secret: secret == "secret") is True
    with pytest.raises(BrokerPermissionError, match="credential unavailable"):
        credentials.perform("SportsAgent", "x.publish", lambda secret: secret)
    assert "secret" not in repr(credentials)
