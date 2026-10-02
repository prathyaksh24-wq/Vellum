import subprocess
import tomllib
from pathlib import Path

from agent.plugins.agent_reach import agent_reach_plugin_status


def test_agent_reach_dependencies_are_in_both_install_manifests():
    backend = Path(__file__).resolve().parents[1]
    dependencies = tomllib.loads((backend / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    requirements = (backend / "requirements.txt").read_text(encoding="utf-8").splitlines()
    for prefix in ("agent-reach==", "twitter-cli @"):
        matching = [entry for entry in requirements if entry.startswith(prefix)]
        assert len(matching) == 1
        assert matching[0] in dependencies


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
    assert calls[0] == ["agent-reach", "--version"]


def test_agent_reach_plugin_status_passes_saved_credentials_only_to_twitter(monkeypatch):
    monkeypatch.setattr("agent.plugins.agent_reach.shutil.which", lambda name: f"C:/bin/{name}.exe")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs.get("env")))
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr("agent.plugins.agent_reach.subprocess.run", fake_run)
    child_env = {"TWITTER_AUTH_TOKEN": "saved-auth", "TWITTER_CT0": "saved-ct0"}

    status = agent_reach_plugin_status(
        agent_reach_bin="agent-reach",
        twitter_cli_bin="twitter",
        twitter_env=child_env,
    )

    assert status.status == "ready"
    assert calls[0] == (["agent-reach", "--version"], None)
    assert calls[1] == (["twitter", "status", "--yaml"], child_env)


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
