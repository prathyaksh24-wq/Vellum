# Agent-Reach Connector

Hermes-style portable wrapper for Vellum's Agent-Reach X connector.

This wrapper does not duplicate runtime code. It registers the existing Vellum backend implementation:

- `agent.plugins.agent_reach.agent_reach_plugin_status`
- `agent.tools.capabilities.agent_reach_x_provider.AgentReachXProvider`

## Capabilities

- Search and read X posts
- Fetch timeline, profiles, account posts, bookmarks, and likes
- Prepare confirmed post, reply, like, unlike, repost, unrepost, bookmark,
  unbookmark, quote, follow, unfollow, and delete actions

Post editing is not supported by the current connector. Vellum must report that
boundary instead of simulating an edit with delete and repost.

## Setup

Agent-Reach and `twitter-cli` must be installed and authenticated in the local
environment. Vellum requires `twitter-cli` 0.8.6 or newer. The tested build is
pinned to the upstream search fix:

```powershell
uv tool install --force "git+https://github.com/public-clis/twitter-cli.git@57b91c03d85ef7b76328807af2a40cc9741f039e"
```

Authenticate through `twitter-cli`'s browser-cookie flow, then verify without
performing a mutation:

```powershell
twitter --version
twitter status --yaml
twitter search "Vellum" --max 1 --json
agent-reach doctor --json
```

The health endpoint marks older or unparseable `twitter-cli` versions as
degraded. Search is only marked ready after a live read-only probe.

## Runtime Safety

- Vellum serializes `twitter-cli` processes because concurrent sessions can
  interfere with the connector's transaction bootstrap state.
- Read operations retry once only for transient timeout, rate-limit, server, or
  known bootstrap failures.
- Write operations have zero automatic retries.
- Once a write reaches Agent-Reach, an error is returned to the user. Vellum
  does not switch to another write provider because the first result may be
  ambiguous and a fallback could duplicate the action.
- Every external write requires Vellum's stored pending-action confirmation.
