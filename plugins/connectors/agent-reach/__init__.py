"""Hermes-style portable wrapper for Vellum's Agent-Reach connector."""

from __future__ import annotations

from agent.plugins.agent_reach import agent_reach_plugin_status
from agent.tools.capabilities.agent_reach_x_provider import AgentReachXProvider


def register(ctx) -> None:
    ctx.register_connector(
        id="agent-reach",
        name="Agent-Reach",
        category="Connectors",
        status_factory=agent_reach_plugin_status,
        provider_factory=AgentReachXProvider,
        capabilities=[
            "x.search",
            "x.read_tweet",
            "x.timeline",
            "x.profile",
            "x.bookmarks",
            "x.likes",
            "x.post",
            "x.reply",
            "x.like",
            "x.repost",
            "x.delete",
        ],
    )
