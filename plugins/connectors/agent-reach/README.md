# Agent-Reach Connector

Hermes-style portable wrapper for Vellum's Agent-Reach X connector.

This wrapper does not duplicate runtime code. It registers the existing Vellum backend implementation:

- `agent.plugins.agent_reach.agent_reach_plugin_status`
- `agent.tools.capabilities.agent_reach_x_provider.AgentReachXProvider`

## Capabilities

- Search X
- Read tweets
- Fetch timeline, profile, bookmarks, and likes
- Prepare and execute confirmed write actions: post, reply, like, repost, delete

Write actions still require Vellum's existing confirmation flow.

## Setup

Agent-Reach and `twitter-cli` must be installed and authenticated in the local environment.
