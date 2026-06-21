import subprocess

from agent.plugins.agent_reach import agent_reach_plugin_status


def test_agent_reach_plugin_status_ready_when_bins_exist_and_twitter_authenticated(monkeypatch):
    monkeypatch.setattr("agent.plugins.agent_reach.shutil.which", lambda name: f"C:/bin/{name}.exe")
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr("agent.plugins.agent_reach.subprocess.run", fake_run)

    status = agent_reach_plugin_status(agent_reach_bin="agent-reach", twitter_cli_bin="twitter")

    assert status.id == "agent-reach"
    assert status.status == "ready"
    assert status.configured is True
    assert "x.search" in status.capabilities
    assert calls[0] == ["agent-reach", "health"]


def test_agent_reach_plugin_status_falls_back_to_doctor_for_current_cli(monkeypatch):
    monkeypatch.setattr("agent.plugins.agent_reach.shutil.which", lambda name: f"C:/bin/{name}.exe")
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        if args == ["agent-reach", "health"]:
            return subprocess.CompletedProcess(args, 2, stdout="", stderr="invalid choice: 'health' (choose from 'doctor')")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr("agent.plugins.agent_reach.subprocess.run", fake_run)

    status = agent_reach_plugin_status(agent_reach_bin="agent-reach", twitter_cli_bin="twitter")

    assert status.status == "ready"
    assert ["agent-reach", "doctor"] in calls


def test_agent_reach_plugin_status_reports_missing_agent_reach(monkeypatch):
    monkeypatch.setattr("agent.plugins.agent_reach.shutil.which", lambda name: None)

    status = agent_reach_plugin_status(agent_reach_bin="agent-reach", twitter_cli_bin="twitter")

    assert status.status == "missing_agent_reach"
    assert status.configured is False
    assert "Install Agent-Reach" in status.notes


def test_agent_reach_plugin_status_reports_missing_twitter_cli(monkeypatch):
    monkeypatch.setattr(
        "agent.plugins.agent_reach.shutil.which",
        lambda name: "C:/bin/agent-reach.exe" if name == "agent-reach" else None,
    )

    status = agent_reach_plugin_status(agent_reach_bin="agent-reach", twitter_cli_bin="twitter")

    assert status.status == "missing_twitter_cli"
    assert status.configured is False
    assert "twitter-cli" in status.notes


def test_agent_reach_plugin_status_reports_not_authenticated(monkeypatch):
    monkeypatch.setattr("agent.plugins.agent_reach.shutil.which", lambda name: f"C:/bin/{name}.exe")

    def fake_run(args, **_kwargs):
        if args[0] == "twitter":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="Please login first")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr("agent.plugins.agent_reach.subprocess.run", fake_run)

    status = agent_reach_plugin_status(agent_reach_bin="agent-reach", twitter_cli_bin="twitter")

    assert status.status == "not_authenticated"
    assert status.configured is False
    assert "authenticate" in status.notes.lower()
