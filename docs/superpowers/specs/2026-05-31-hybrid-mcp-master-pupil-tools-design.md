# Hybrid MCP Master-Pupil Tool Layer (Design Spec)

> Date: 31/05/2026
> Status: approved-direction, pending implementation plan
> Builds on: `2026-05-30-sports-specialist-web-research-design.md`

## Goal

Move Vellum's sub-agents toward the build-plan model: Vellum remains the Master agent and final user-facing responder, while Pupils use shared, permissioned tool capabilities instead of owning raw integrations directly.

The first target is a hybrid MCP approach:

- Internal MCP-shaped services for capabilities that are not yet true MCP servers.
- Existing MCP/tool integrations reused through the same registry and permission model.
- A clean path to promote stable internal services into real MCP servers later.

This should make X, YouTube, Memory, Sports, Research, Coding, and future Pupils scalable without turning Vellum into a pile of one-off tool calls.

## Current State

- `SportsAgent` now has the first real Pupil path: live dispatcher, sources, per-thread active-agent state, and on-demand answers.
- `XAgent`, `YoutubeAgent`, and `MemoryAgent` route through the dispatcher, but X/Youtube are still execution stubs and MemoryAgent is only a proposal stub.
- X has existing OAuth infrastructure:
  - `scripts/setup_xai_oauth.py` writes `data/xai-oauth.json` for xAI/SuperGrok OAuth search.
  - `scripts/xai_x_search_client.py` performs xAI-backed X Search.
  - `scripts/setup_x_api_oauth.py` writes `data/x-api-oauth.json` for official X API reads/writes.
  - `backend/agent/tools/x.py` exposes `x_action`, mixing public search, private reads, and posting behind env gates.
- Existing shared tools already include Context Mode, Context7/library docs, GitHub, Obsidian API, browser/computer use, web search, local files, and vault search.
- Memory exists in several layers: FTS5, Honcho, ProjectContext, Obsidian memory cards, Qdrant when installed, retention/distillation scripts, and background learning.

## Design Principles

1. Vellum stays the Master agent.
2. Pupils never own the final user response.
3. Pupils do not own raw integrations; they receive scoped access to shared capabilities.
4. Tokens and OAuth files are centralized, never copied into Pupil state.
5. Write actions require Master permission and, when external, explicit user approval.
6. Pupils can propose global memory; MemoryAgent reviews; Master approves accepted writes.
7. Existing MCP servers are reused, not replaced.
8. Internal services should look MCP-shaped from day one: typed inputs, typed outputs, capability names, permissions, audit events, and tests.

## Architecture

```text
User
  -> Vellum Master
      -> Master Dispatcher
      -> Pupil Registry
      -> Tool Registry
          -> Existing MCP/tool adapters
          -> Internal MCP-shaped services
          -> Future real MCP servers
      -> MemoryAgent review
      -> Final response composer

Pupils
  -> SportsAgent
  -> XAgent
  -> YoutubeAgent
  -> MemoryAgent
  -> Future Research/Coding/Books agents
```

## Hybrid MCP Model

Each capability is registered as a tool namespace:

```text
x.search_posts
x.get_post_thread
x.get_user_profile
youtube.search_videos
youtube.get_transcript
memory.get_relevant_context
memory.propose_card
context7.resolve_library
context7.fetch_docs
context_mode.fetch_and_index
obsidian.search_notes
github.read_issue
```

For now, some namespaces call local Python modules or LangChain tools. Later, any namespace can be exposed as a real MCP server without changing the Pupil contract.

## Tool Registry

Add a shared registry that records:

- capability name
- owner namespace
- callable adapter
- read/write/destructive/external-posting classification
- required env gates
- allowed Pupils
- audit label for streaming activity
- source extraction behavior

Example:

```json
{
  "name": "x.search_posts",
  "namespace": "x",
  "access": "read",
  "backend": "internal",
  "allowed_agents": ["XAgent", "ResearchAgent", "MemoryAgent", "VellumAgent"],
  "requires": ["data/xai-oauth.json or XAI_OAUTH_ACCESS_TOKEN"],
  "stream_label": "Searched X"
}
```

## X Capability Layer

### Purpose

Give XAgent and other approved agents reliable X access through xAI/SuperGrok OAuth and official X OAuth, without exposing raw OAuth handling to the Pupil.

### Backends

- Public X search: xAI/SuperGrok OAuth via `data/xai-oauth.json` or `XAI_OAUTH_ACCESS_TOKEN`.
- Account/private reads: official X API OAuth via `data/x-api-oauth.json`, gated by `X_TOOL_ALLOW_PRIVATE_READS=true`.
- Posting: official X API OAuth, gated by `X_TOOL_ALLOW_POSTS=true`, `confirm=True`, and explicit user intent.

### Tools

```text
x.search_posts(query, max_results, since, until)
x.get_user_profile(handle)
x.get_user_timeline(handle, max_results)
x.get_post_thread(url_or_id)
x.get_bookmarks(max_results)
x.publish_post(text, confirm)
```

### XAgent Behavior

XAgent should:

- classify whether the user wants public search, account lookup, thread reading, bookmarks, or posting
- call the X capability layer
- return structured evidence: posts, handles, timestamps, URLs, snippets
- propose memory only for stable preferences or repeatedly tracked accounts
- never post without Master + user approval

## YouTube Capability Layer

### Purpose

Provide a read-only content intelligence surface for videos, channels, transcripts, playlists, and creator tracking.

### Tools

```text
youtube.search_videos(query, max_results)
youtube.get_video_metadata(url_or_id)
youtube.get_transcript(url_or_id)
youtube.get_channel_uploads(channel_id_or_url, max_results)
youtube.get_playlist_videos(playlist_url_or_id)
youtube.summarize_video(url_or_id)
youtube.track_channel(channel_id_or_url)
youtube.compare_videos(video_ids)
youtube.extract_key_moments(url_or_id)
```

### Permission Model

- Read-only by default.
- No liking, commenting, subscribing, or posting in the first implementation.
- Channel tracking writes only to Vellum's local vault/memory, not YouTube.

## Memory Capability Layer

### Purpose

Make MemoryAgent the dependable memory specialist for Vellum and all Pupils.

MemoryAgent should be responsible for long-term memory quality, context packing, conflict detection, proposal review, and durable memory-card creation.

### Tools

```text
memory.get_relevant_context(query, thread_id, agent_name)
memory.search_cards(query, scope)
memory.propose_card(scope, claim, evidence, confidence)
memory.review_proposals(proposals)
memory.detect_conflicts(claims)
memory.create_card(scope, title, summary, evidence, visible_to)
memory.summarize_conversation(thread_id)
memory.build_context_pack(query, thread_id, agent_name)
```

### Memory Layers

Use existing stores instead of inventing a parallel memory brain:

- ProjectContext for active project and identity context
- FTS5 for local searchable Q/A
- Honcho for conversational memory when available
- Obsidian `Agent/Memories/` cards for durable memory
- Qdrant/vector store when installed
- retention/distillation scripts for archive-to-card compression

### Write Policy

- Vellum can write global memory through approved paths.
- Pupils can propose memories.
- MemoryAgent reviews proposals and detects conflicts.
- Master approves accepted global/user-memory writes.
- Domain-private memories can be scoped to a Pupil, such as `pupil/x` or `pupil/sports`.

## Existing MCP Servers and Tools

Existing integrations remain part of the shared registry:

- Context7/library docs: docs lookup for CodingAgent, ResearchAgent, and Vellum.
- Context Mode: fetch/index/execute for research and article reading.
- GitHub MCP: GitHub read/write, with writes gated.
- Obsidian API/MCP: local knowledge and note operations, folder-policy aware.
- Browser/computer use: visible automation, Master-approved for risky actions.
- Web search: public research fallback.
- Vault search/local files: private/local retrieval.

These should be represented in the Tool Registry even when the backend is already implemented as a LangChain tool.

## Data Flow

```text
User asks question
  -> Master dispatcher identifies direct answer vs Pupil
  -> selected Pupil requests context from MemoryAgent when useful
  -> Pupil calls permitted capability tools
  -> capability layer returns structured records + source metadata
  -> Pupil returns SpecialistResponse
  -> MemoryAgent reviews memory proposals
  -> Master composes final answer
  -> frontend sees one chat with activity/source events
```

## Streaming UX

The frontend stays a single Vellum chat. Activity events should show safe, high-level steps:

```text
Routed to XAgent
Searched X
Read post thread
Asked MemoryAgent for context
Reviewed memory proposal
Final response ready
```

Do not stream raw chain-of-thought, prompts, tokens, OAuth data, or unfiltered internal scratchpad.

## Reliability and Scalability

Reliability comes from:

- one schema per capability
- one permission model per capability
- centralized OAuth handling
- structured sources and evidence
- tests per tool adapter
- Master-owned final answer
- MemoryAgent review before durable global memory writes

Scalability comes from:

- shared tools reused by many Pupils
- no duplicate integrations per Pupil
- easy migration from internal adapter to real MCP server
- registry-based routing and permissions
- audit logs/reward signals per capability and Pupil

## Implementation Phases

### Phase 1: Registry Foundation

- Add Tool Registry models.
- Register existing tools and MCP-like adapters.
- Add permission checks and audit labels.
- Add tests for read/write gates.

### Phase 2: X MCP-Shaped Service

- Wrap xAI/SuperGrok OAuth search as `x.search_posts`.
- Add profile/thread/timeline wrappers where existing client support is available.
- Update XAgent to use X service instead of stub response.
- Keep posting gated and deferred unless explicitly requested.

### Phase 3: Memory MCP-Shaped Service

- Add Memory service around FTS5, ProjectContext, Honcho, and memory cards.
- Upgrade MemoryAgent to build context packs and review proposals.
- Add conflict detection and accepted/rejected proposal persistence.

### Phase 4: YouTube MCP-Shaped Service

- Add YouTube read-only service for search, metadata, transcript, and tracking.
- Update YoutubeAgent to use the service.

### Phase 5: Promote Stable Services to Real MCP

- For any namespace that becomes useful outside Vellum, expose it as a real MCP server.
- Keep the Pupil contract and Tool Registry interface unchanged.

## Testing Strategy

- Unit tests for every capability adapter.
- Permission tests for private reads, writes, and posting.
- Dispatcher tests for Pupil routing and fallback to main Vellum.
- Memory tests for context packing, proposal review, conflict detection, and card creation.
- Source tests for structured evidence and frontend source display.
- No live network in default tests; OAuth and API calls mocked.

## Open Decisions

- Whether the first YouTube backend uses an existing transcript package, YouTube Data API, or a local transcript scraper.
- Whether accepted MemoryAgent writes should be automatic above a confidence threshold or always Master-reviewed first.
- Whether X private reads should be enabled by default after OAuth setup or remain env-gated every time.

## Recommended Defaults

- Use the hybrid model now.
- Keep private reads and posts env-gated.
- Keep posting behind explicit user confirmation.
- Let MemoryAgent propose/review, and let Master own accepted global writes.
- Promote internal services to true MCP only after the schema and permissions prove stable.
