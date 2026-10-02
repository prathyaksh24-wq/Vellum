from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping

from agent.plugins.models import PluginStatus


AGENT_REACH_CAPABILITIES = [
    "x.search",
    "x.read_tweet",
    "x.timeline",
    "x.profile",
    "x.user_posts",
    "x.bookmarks",
    "x.post",
    "x.reply",
    "x.like",
    "x.unlike",
    "x.repost",
    "x.unrepost",
    "x.bookmark",
    "x.unbookmark",
    "x.quote",
    "x.follow",
    "x.unfollow",
    "x.delete",
]


def agent_reach_plugin_status(
    *,
    agent_reach_bin: str = "agent-reach",
    twitter_cli_bin: str = "twitter",
    timeout_seconds: float = 10.0,
    twitter_env: Mapping[str, str] | None = None,
    trust_configured_credentials: bool = False,
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

    agent_reach_check = _run_health([agent_reach_bin, "--version"], timeout_seconds)
    if agent_reach_check.returncode != 0:
        return _status(
            configured=False,
            status="error",
            notes=f"Agent-Reach health check failed: {_short_error(agent_reach_check)}",
        )

    if trust_configured_credentials and twitter_env:
        auth_token = str(twitter_env.get("TWITTER_AUTH_TOKEN") or "").strip()
        ct0 = str(twitter_env.get("TWITTER_CT0") or "").strip()
        if auth_token and ct0:
            return _status(
                configured=True,
                status="ready",
                notes="Agent-Reach X credentials are configured; live commands verify the session.",
            )

    twitter_check = _run_health(
        [twitter_cli_bin, "status", "--yaml"],
        timeout_seconds,
        env=twitter_env,
    )
    if twitter_check.returncode != 0:
        return _status(
            configured=False,
            status="not_authenticated",
            notes="Agent-Reach is installed, but twitter-cli is not authenticated. Authenticate X in twitter-cli first.",
        )

    return _status(configured=True, status="ready", notes="Agent-Reach X connector is ready.")


def _run_health(
    args: list[str],
    timeout_seconds: float,
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            env=dict(env) if env is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=str(exc))


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
