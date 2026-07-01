## Current Status

Vellum is currently in active development.

# Vellum

**Vellum is a self-learning AI orchestrator and desktop superapp built around the user as the source of truth.**

Vellum is a private, local-first AI workspace where a main agent coordinates multiple sub-agents, uses tools, operates the browser, terminal, filesystem, and coding environments, and continuously learns from the user’s workflows, decisions, mistakes, and knowledge base.

At its core, Vellum uses **local models as the primary brain**, giving users privacy, ownership, and control over their data. Users can also connect open-source or cloud models through their own API keys when they need more power. Even when cloud models are used, Vellum is designed to protect sensitive context before anything leaves the machine.

> Your data stays yours.

## What Vellum Does

- Chat with the main Vellum agent
- Switch into coding mode using Codex and Claude Code SDKs inside the app
- Use embedded browser, terminal, and filesystem panels
- Delegate tasks to specialized sub-agents
- Connect MCP servers through a shared tool registry
- Run local, open-source, or cloud models
- Store learning, mistakes, decisions, and knowledge in Obsidian
- Ingest knowledge bases into searchable memory
- Watch agent work through live activity streaming

## How Vellum Works

The main Vellum agent acts as an orchestrator. It decides when to answer directly, when to delegate to a sub-agent, which tools to use, and how to combine results into useful action.

Vellum’s sub-agents can specialize in areas like coding, browser automation, research, memory, books, YouTube, files, and computer use. Their outputs, mistakes, decisions, and useful learnings can be saved into Obsidian, making the knowledge base both human-readable and machine-usable.

Over time, Vellum builds a deeper understanding of the user because the user is the source of truth. It learns from conversations, workflows, files, project history, and the user’s own notes, while keeping privacy and control at the center.

## LLM Routing and Resilience

The model selected in Vellum's model picker is the primary model for every new invocation. The backend then applies three resilience layers in order:

1. Select a healthy credential from the API provider's pool.
2. Apply the global plus per-model OpenRouter inference-provider policy.
3. Move through the configured model/provider fallback chain only after the primary route is exhausted.

OpenRouter routing supports price, latency, and throughput sorting; provider allow, deny, and priority lists; required-parameter enforcement; and OpenRouter upstream fallback. Vellum always enforces zero-data-retention routing and denies provider training, regardless of saved policy.

Manual OpenRouter and OpenAI credentials are stored through the operating-system credential store. Environment and `.env` credentials are borrowed into memory and persisted only as references and one-way fingerprints. Health, cooldown, routing policy, fallback order, and content-free attempt telemetry are stored in `data/llm-routing/routing.db`.

Credential recovery behavior:

- A generic 429 retries the same key once, then applies a one-hour cooldown and rotates.
- Authentication failures invalidate that credential immediately.
- Billing or definite plan exhaustion applies a 24-hour cooldown and rotates.
- Network and server failures receive bounded exponential retries.
- Every new invocation starts from the model selected in the frontend again.
- Once streamed text or a tool call becomes visible, Vellum will not switch models automatically because replay could duplicate output or actions.

Management endpoints are available under `/api/llm-routing`, and the Configuration settings tab exposes a minimal interface for policy, fallback, credential health, and recent route status.

Optional environment settings:

```env
LLM_ROUTING_DB_PATH=data/llm-routing/routing.db
LLM_ROUTING_KEYRING_SERVICE=vellum.llm
LLM_ROUTING_MAX_TARGETS=4
LLM_ROUTING_MAX_TRANSIENT_RETRIES=2
```

## Vision

Vellum is not just a chatbot. It is an AI operating layer for your computer.

It brings together:

- Chat
- Browser
- Terminal
- Filesystem
- Coding agents
- Sub-agents
- Memory
- Local models
- Cloud models
- Obsidian knowledge base

All inside one unified desktop workspace.

```txt
Private by default.
Local-first.
Model-flexible.
Deeply personal.
Transparent in action.
Built around the user.
