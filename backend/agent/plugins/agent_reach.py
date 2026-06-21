from __future__ import annotations

import shutil
import subprocess

from agent.plugins.models import PluginStatus


AGENT_REACH_CAPABILITIES = [
    "x.search",
    "x.read_tweet",
    "x.timeline",
    "x.profile",
    "x.bookmarks",
    "x.post",
    "x.reply",
    "x.like",
    "x.repost",
    "x.delete",
]


def agent_reach_plugin_status(
    *,
    agent_reach_bin: str = "agent-reach",
    twitter_cli_bin: str = "twitter",
    timeout_seconds: float = 10.0,
) -> PluginStatus:
    if shutil.which(agent_reach_bin) is None:
        return _status(
            configured=False,
            status="missing_agent_reach",
            notes="Install Agent-Reach, then run its health check before using the X connector.",
        )
    if shutil.which(twitter_cli_bin) is None:
        return _status(
            configured=False,
            status="missing_twitter_cli",
            notes="Install and configure twitter-cli so Agent-Reach can access X account actions.",
        )

    agent_reach_check = _run_agent_reach_health(agent_reach_bin, timeout_seconds)
    if agent_reach_check.returncode != 0:
        return _status(
            configured=False,
            status="error",
            notes=f"Agent-Reach health check failed: {_short_error(agent_reach_check)}",
        )

    twitter_check = _run_health([twitter_cli_bin, "status", "--yaml"], timeout_seconds)
    if twitter_check.returncode != 0:
        return _status(
            configured=False,
            status="not_authenticated",
            notes="Agent-Reach is installed, but twitter-cli is not authenticated. Authenticate X in twitter-cli first.",
        )

    return _status(configured=True, status="ready", notes="Agent-Reach X connector is ready.")


def _run_health(args: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=str(exc))


def _run_agent_reach_health(agent_reach_bin: str, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    result = _run_health([agent_reach_bin, "health"], timeout_seconds)
    if result.returncode == 0:
        return result
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "invalid choice" in combined and "doctor" in combined:
        return _run_health([agent_reach_bin, "doctor"], timeout_seconds)
    return result


def _status(*, configured: bool, status: str, notes: str) -> PluginStatus:
    return PluginStatus(
        id="agent-reach",
        name="Agent-Reach",
        type="connector",
        category="Connectors",
        configured=configured,
        status=status,
        notes=notes,
        capabilities=list(AGENT_REACH_CAPABILITIES),
    )


def _short_error(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or result.stdout or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:240] or f"exit code {result.returncode}"
