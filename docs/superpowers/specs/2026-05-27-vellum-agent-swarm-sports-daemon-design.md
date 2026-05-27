---
type: design-spec
created: 2026-05-27
agent_version: vellum-1.0
private: true
status: pending-user-review
---

# Vellum Agent Swarm and Sports Daemon Design

## Purpose

Vellum should remain the user's main general-purpose agent while gaining specialist subagents that can learn, run focused workflows, and return structured results. The immediate use case is fixing `Vault/Library/Sports/` so Vellum can track Formula One, NBA, Premier League, and Champions League updates continuously, while leaving UFC and boxing disabled.

The end-user experience should be simple: the user asks Vellum for a sports update, a match summary, an injury check, or broader analysis. Vellum routes internally to a specialist if useful, then responds in one coherent voice with current status, sources, and analysis.

## Current Context

The repo already has a sports foundation:

- `scripts/import_sports_snapshots.py` fetches SerpAPI snapshots into `Library/Sports/<League>/snapshots/YYYY/`.
- `backend/agent/tools/sports_curiosity.py` exposes `should_fetch_sports` and `fetch_sports_if_curious`.
- `backend/agent/scheduler/sports_calibration.py` adjusts sports curiosity thresholds from usage signals.
- `Vault/Library/Sports/.state/curiosity.json` stores per-league curiosity settings.
- Vellum's system prompt already lists sports curiosity tools.

Gaps:

- Sports fetching is opportunistic only, not daemon-driven.
- `latest.md` files are placeholders because no real snapshots have been fetched.
- UFC and boxing are still present in config and tool descriptions, even though the user wants to leave them out.
- Existing tests for `test_sports_importer.py` appear to expect an older `Vault/Sports/...` layout and older direct-source files, while the current importer writes `Vault/Library/Sports/...` SerpAPI snapshots.
- There is no first-class subagent routing contract yet.
- The memory model does not yet clearly distinguish main-agent memory, specialist memory, shared memory, and proposed learnings.

Verified current sports attention map as of 2026-05-27:

- NBA Finals 2026 tip off on June 3, 2026.
- Champions League final 2026 is scheduled for May 30, 2026 at Puskas Arena.
- Formula One's next race after Canada is Monaco, June 5-7, 2026.
- Arsenal are confirmed as 2025/26 Premier League champions.

## Product Shape

Vellum remains the main agent. It can still:

- search the vault
- search the web
- call MCP tools
- use browser/computer tools
- write approved notes
- reason generally
- answer directly when specialist help is unnecessary
- delegate when a specialist domain or long-running workflow is useful
- synthesize specialist results into the final response

Specialist agents advise; Vellum decides. Specialists should not directly speak to the user unless the user explicitly opens a specialist mode later.

## Architecture

### Main Agent

`VellumAgent` is the user-facing orchestrator.

Responsibilities:

- classify query intent
- retrieve main memory and relevant vault context
- decide whether to answer directly or route
- call specialist agents through a structured interface
- enforce privacy and folder policy
- merge outputs
- provide final answer in Vellum's voice
- write user-facing response and durable summaries through existing memory paths

### Specialist Agents

Initial specialist set:

- `SportsAgent`: live sports snapshots, scores, injuries, fixtures, post-match summaries, tactical/contextual analysis.
- `XAgent`: X ingestion, account/topic tracking, quote extraction, recurring theme detection.
- `YoutubeAgent`: channel watching, transcript imports, video summaries, creator/topic memory.
- `MemoryAgent`: cross-agent distillation, skill proposals, durable user traits, memory conflict checks.
- `MCPAgent`: optional tool-broker for complex MCP-heavy workflows. Simple MCP calls stay with Vellum.

Each specialist has:

- a domain prompt
- allowed tools
- private specialist memory
- a structured response schema
- escalation rules
- source and confidence reporting

### Daemon

Add a local background process named `vellum-daemon`.

Responsibilities:

- run background curiosity loops
- evaluate attention scores
- fetch or skip based on thresholds, budgets, and season state
- write fetch decisions as memories
- update `latest.md` files
- produce post-event summaries when games or matches finish
- queue reindex requests or trigger existing watcher flows where available
- avoid duplicate fetches through state locks

The daemon should run locally only. It should be startable with a script and later installable as a Windows scheduled/background service.

Initial loops:

- `sports_loop`
- `x_loop`
- `youtube_loop`
- `memory_loop`

The sports loop is implemented first.

## Routing Flow

```text
User asks Vellum
  -> Vellum checks direct answer capability
  -> Vellum retrieves shared/user memory
  -> Vellum routes if specialist context is useful
  -> specialist returns structured result
  -> Vellum checks sources, confidence, freshness, and safety
  -> Vellum answers the user
```

Routing should be explicit and inspectable in logs, but invisible in normal chat unless the user asks how an answer was produced.

## Specialist Response Contract

Specialists return JSON-like structured data:

```json
{
  "agent": "SportsAgent",
  "status": "answered | needs_fetch | stale | blocked | error",
  "summary": "short plain-language finding",
  "analysis": "domain-specific reasoning",
  "sources": [
    {
      "kind": "vault | web | api | memory",
      "title": "source title",
      "path_or_url": "source path or URL",
      "captured_at": "ISO timestamp",
      "freshness": "live | recent | stale | historical"
    }
  ],
  "confidence": 0.0,
  "memory_proposals": [
    {
      "scope": "sports | x | youtube | shared",
      "claim": "candidate learning",
      "evidence": "why this seems true",
      "confidence": 0.0
    }
  ]
}
```

Vellum can reject, summarize, or store `memory_proposals`. Specialists do not directly rewrite shared identity memory.

## Memory Model

Memory has two dimensions: type and scope.

Types:

- Episodic: conversations, fetches, decisions, match events, tool attempts.
- Semantic: stable facts and preferences, such as "user follows Arsenal" or "user prefers tactical sports analysis over hype."
- Procedural: reusable skills, routing habits, answer formats, tool workflows.

Scopes:

- Main Vellum memory: tone, principles, goals, conversation style, long-term preferences, project context.
- Specialist private memory: domain-specific learning owned by one specialist.
- Shared memory: distilled facts useful to Vellum and multiple specialists.
- Proposed memory: unapproved or low-confidence learning waiting for MemoryAgent/Vellum review.

Learning flow:

```text
Specialist observes signal
  -> writes episodic memory or proposes semantic/procedural memory
  -> MemoryAgent reviews and distills
  -> Vellum accepts shared memory when evidence is strong
```

This keeps self-learning real without allowing uncontrolled identity drift.

### Retention and Memory Cards

The agent swarm must reuse Vellum's existing retention model instead of creating an unbounded parallel memory store.

Existing retention behavior:

- Public source folders such as `Library/X/`, `Library/Youtube/`, and `Library/Sports/` can move raw notes to `Archive/` after 30 days.
- Archived raw source notes can be deleted after 90 days.
- Before archived raw source notes are deleted, Vellum writes durable memory cards into `Agent/Memories/`.
- Conversation logs follow a related path: `Agent/Queries/` can be distilled and deleted after 30 days, while `Agent/Responses/` can be distilled and deleted after 90 days.
- `Agent/Saved/`, `Agent/Memories/`, `Agent/Digests/`, `Agent/Reflections/`, and notes marked `pinned: true` or `retention: keep` are protected.

Subagents should treat raw fetched material as perishable and memory cards as durable. A specialist can write or propose high-signal memory cards, but routine source snapshots should remain subject to archive/delete retention. This keeps the system scalable: the vault stays queryable while old raw material is compressed into stable lessons, preferences, and domain summaries.

For sports, this means dated snapshots and event notes can age out through the existing retention path, while `SportsAgent` preserves durable cards such as:

- the user's followed leagues, teams, players, and drivers
- recurring analysis preferences
- season-level summaries
- major completed events
- lessons about which fetches were useful or wasteful

## SportsAgent Design

Tracked sports:

- NBA
- Formula One
- Premier League
- Champions League

Disabled for now:

- UFC
- Boxing

Ambient sports remain possible only when strongly triggered by user conversation or major events, but the first implementation can keep Ambient low-priority.

### Sports Data Flow

```text
sports_loop wakes
  -> loads curiosity state
  -> evaluates each enabled league
  -> checks live calendar and recency hunger
  -> checks user-signal memory and recent queries
  -> checks cross-feed signals from X/Youtube
  -> fetches if threshold and budget allow
  -> writes dated snapshot
  -> regenerates latest.md
  -> writes decision memory
  -> if event ended, writes post-event summary
```

### Sports Outputs

Each enabled league should have:

- `latest.md`: current top-level feed with snapshot links and human-readable status.
- `snapshots/YYYY/*.md`: dated raw-ish SerpAPI snapshots with extracted blocks.
- `events/YYYY/<event>.md`: post-event summary notes for completed games/races/matches.
- `topics/`: durable notes for players, teams, storylines, injuries, and title races where useful.
- `agent-guide.md`: domain-specific retrieval rules.

Sports snapshots should include:

- score/status
- fixture/race/match timing
- key players or drivers
- injuries/team news where available
- result summary once finished
- source freshness
- raw JSON block when useful for agent inspection

### Sports Curiosity

Curiosity is not random polling. It is attention formed from signals:

- user conversation
- recent actions taken by Vellum
- recency hunger
- season state
- known major events
- cross-feed mentions in X/Youtube
- whether prior fetches were used
- small stochastic component for serendipity

The daemon should evaluate curiosity on a schedule, but curiosity still decides what gets fetched.

Suggested first intervals:

- During live windows: every 3-5 minutes for active event queries.
- Normal in-season: every 30-60 minutes.
- Offseason or low-priority leagues: every 6-12 hours.
- Ambient: only when triggered by a strong user or cross-feed signal.

Budget controls remain mandatory.

## API and Implementation Boundaries

Add modules under `backend/agent/`:

- `agents/base.py`: specialist protocol and response schema.
- `agents/router.py`: route classification and delegation.
- `agents/sports.py`: SportsAgent.
- `agents/x_agent.py`: XAgent stub or thin wrapper.
- `agents/youtube.py`: YoutubeAgent stub or thin wrapper.
- `agents/memory_agent.py`: MemoryAgent stub or thin wrapper.
- `daemon/main.py`: daemon entrypoint.
- `daemon/loops/sports.py`: sports loop.

Existing scripts should be reused:

- Keep `scripts/import_sports_snapshots.py` as the low-level fetcher initially.
- Update it only where needed to disable UFC/boxing, improve latest files, and support post-event summaries.
- Keep `sports_curiosity.py`, but split pure scoring from LangChain tool wrappers if tests become awkward.

## Error Handling

- If a specialist fails, Vellum falls back to direct vault/web/tool use.
- If live fetch fails, use latest stored snapshot and clearly mark it stale.
- If SerpAPI budget is exhausted, write a skipped decision memory and answer from existing snapshots.
- If sources conflict, Vellum says so and reports the more authoritative or fresher source.
- If no sports data exists yet, Vellum can fetch once on demand if budget allows.

## Privacy and Safety

- Sports, X, Youtube, and public web data are public-source domains unless mixed with private user context.
- User preferences and personal conversation signals remain private memory.
- Specialists receive only the minimum context needed.
- Specialists can propose shared memory, but cannot directly mutate main identity memory.
- External calls should not include private vault content.
- Existing OpenRouter data-collection-deny rules still apply to any LLM call.

## Testing Plan

Unit tests:

- router chooses direct answer vs specialist route
- specialist response schema validates
- SportsAgent handles live, stale, empty, and error states
- sports daemon loop fetches enabled leagues only
- UFC and boxing are disabled
- latest files regenerate from snapshots
- post-event summaries are produced for completed events
- memory proposals are generated but not directly committed to shared memory
- budget exhaustion suppresses fetches

Integration tests:

- daemon dry-run does not hit network or write snapshots
- fake sports client writes expected `Library/Sports/...` files
- Vellum routes a sports query to SportsAgent and returns a sourced answer
- existing curiosity calibration still works with new memory notes

Regression cleanup:

- Update `test_sports_importer.py` to match the current `Library/Sports` layout or split old direct-source expectations into a removed/legacy test.

## Implementation Stages

Stage 1: Sports folder repair and disabled leagues.

- Update sports config to track NBA, Formula One, Premier League, Champions League.
- Disable UFC and boxing in routing, seed state, and importer defaults.
- Repair tests to match current paths.
- Run dry-run and targeted tests.

Stage 2: SportsAgent and routing contract.

- Add base specialist schema.
- Add SportsAgent wrapper around existing sports curiosity/fetch/retrieval tools.
- Add router logic for sports questions.
- Keep Vellum as final responder.

Stage 3: Daemon sports loop.

- Add `vellum-daemon` entrypoint.
- Add sports loop with interval config, lock file, budget guard, and dry-run mode.
- Add start/stop scripts.
- Write decision memories and update latest feeds.

Stage 4: Memory proposals.

- Add specialist memory proposal schema.
- Add MemoryAgent review stub.
- Store proposed learnings separately from accepted shared memory.

Stage 5: X/Youtube specialists.

- Wrap existing X and Youtube ingestion behavior behind specialist contracts.
- Add daemon loops only where current scripts already support safe polling.

## Open Decisions

- Whether the daemon should start automatically from `scripts/start.ps1` or require a separate `scripts/start-daemon.ps1`.
- Whether MCPAgent should be implemented in Stage 2 or deferred until MCP workflows show enough complexity.
- Whether post-event summaries should be LLM-generated immediately, or first stored as deterministic structured summaries and synthesized on demand.

Recommended defaults:

- Add a separate `scripts/start-daemon.ps1` first.
- Defer MCPAgent until after SportsAgent is working.
- Start with deterministic summaries plus source snapshots, then add LLM summaries after the data path is stable.

## Success Criteria

- Sports folder is no longer empty after a daemon or on-demand fetch.
- Vellum can answer "what is happening in sports?" with current updates and sources.
- Vellum can answer post-game questions with score, key players, and analysis.
- UFC and boxing are not fetched unless explicitly re-enabled later.
- Vellum can route to SportsAgent while preserving one final user-facing voice.
- Specialist learning produces memory proposals without uncontrolled identity drift.
- Tests cover disabled leagues, routing, daemon dry-run, and sports folder writes.
