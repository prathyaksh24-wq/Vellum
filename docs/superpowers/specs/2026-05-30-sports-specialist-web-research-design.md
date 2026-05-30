# Sports Specialist — On-Demand Web Research + Real Citations (Design Spec)

> Date: 30/05/2026
> Status: approved-for-planning
> Supersedes: the daemon/SerpAPI portions of `docs/superpowers/plans/2026-05-27-vellum-agent-swarm-sports-daemon.md`

## Goal

Turn Vellum's sports handling into a **routed, on-demand web-research specialist**. When the user asks about sports, the main agent hands the conversation to **SportsAgent**, which searches the web, reads the top articles, and answers with **real source citations**. Sports answers are saved per-sport under `Library/Sports/<league>/`. Pre-fetched SerpAPI snapshots and the background daemon are removed; the curiosity scorer is kept for a later proactivity phase.

## Background — current state

- The live chat path is a single LangGraph `create_react_agent` (`backend/agent/graph/agent.py` `build_agent`/`build_async_agent`), wrapped by `LazyAgent`, invoked from `backend/agent/api.py` (`_run_agent`, `_stream_agent_turn` → `agent.ainvoke` / `agent.astream_events`).
- The specialist layer (`backend/agent/agents/`: `SpecialistRouter`, `SkillRouteResolver`, `SpecialistOrchestrator`, `SportsAgent`, stubs) exists but is **dead code** — never imported by `api.py` or `graph/agent.py`; exercised only by unit tests.
- `SportsAgent` today only **reads vault snapshots** (`Library/Sports/<league>/latest.md`) and is limited to 5 fixed leagues.
- Sports data is fetched via SerpAPI (`scripts/import_sports_snapshots.py`) by `fetch_sports_if_curious` (a live `@tool`) and by the **daemon** (`backend/agent/daemon/`), writing snapshots into `Library/Sports/`.
- **Sources are not real:** `ChatResponse` carries only `tools: list[str]` (tool names). The SSE stream emits `token` / `tool` (name only) / `final` / `error` / `audio`. The frontend (`frontend/ui/vellum-chat.html`) renders footnotes + a hover popover from a **static `TOOL_TO_SOURCE` map keyed by tool name** — no real URLs/titles/snippets, no sources sidebar, no activity timeline.
- Web tools available: `web_search` (DuckDuckGo, `backend/agent/tools/web.py`) returns 5 results as a formatted string of `title / body-snippet / href`; `context_mode` `fetch_and_index` (`backend/agent/tools/context_mode.py`) fetches a URL → full markdown (external/unscrubbed, 24h cache).
- Saving: every turn runs `_background_learn` (`api.py`) → `store_qa_pair` → `Agent/Responses/` + Qdrant + FTS5 + Honcho. The intake node writes every query to `Agent/Queries/`.
- `SkillStore` (`backend/agent/memory/skills.py`) defaults its root to `Path(".skills")` — **cwd-relative**, so skill routing returns nothing when the app runs from `backend/` (latent bug).

## Scope

**In scope (this feature):**
- Wire SportsAgent into the live chat behind a router with per-thread active-agent state.
- SportsAgent answers **any** sport (open-ended), including UFC/boxing, via web research (`web_search` → read top 1–3 articles → synthesize).
- Real source citations: structured `Source` records flowing backend → response → SSE → a **minimal** real Sources list in the UI.
- Intent-based hand-back: while in SportsAgent, a non-sports turn prompts the user to route back to the main agent (or another sub-agent).
- Per-sport save isolation: each sports answer saved under the correct `Library/Sports/<league>/`; routing handoff recorded in `Agent/Queries/`.
- Delete the daemon; retire the SerpAPI answer path; keep the curiosity scorer.
- Fix the `SkillStore` cwd bug.

**Deferred (later phases, not this feature):**
- The full ChatGPT-style source UI (domain chips with favicons + `+N` overflow, hover preview cards, a "Sources" sidebar with an AI-activity timeline).
- Proactivity / "learn curiosity from saved history" (will reuse the kept scorer).
- Wiring X / YouTube / Memory sub-agents (the router is designed to accommodate them, but only SportsAgent is implemented now).

**Out of scope:**
- Changing the privacy gate, model routing, or memory architecture beyond what citations/saving require.

## Architecture overview

```
user turn ──> intake + privacy gate (unchanged)
          └─> DISPATCHER (new)
                 ├─ reads per-thread active_agent + pending_reroute
                 ├─ intent check (keyword fast-path + fast-model fallback)
                 ├─ decides: stay | enter SportsAgent | ask-to-hand-back | switch
                 └─> streams the chosen compiled agent:
                        ├─ MAIN agent  (existing create_react_agent)
                        └─ SPORTS agent (new create_react_agent: web_search + fetch_and_index)
                                 └─ SOURCE COLLECTOR captures real sources from tool results
                                 └─ SPORT/LEAGUE RESOLVER picks the save folder
                                 └─ saves answer+sources to Library/Sports/<league>/
final response: answer + structured sources  ──> SSE (token / tool / source / final)
                                              ──> minimal real Sources list in UI
```

## Components

### C1. Active-agent thread state
- **Responsibility:** remember, per thread, which agent owns the conversation and any pending re-route.
- **Interface:** extend the existing per-thread state store (where `active_project` lives, `backend/agent/memory/project_context.py` / `sessions.py`) with:
  - `active_agent: "VellumAgent" | "SportsAgent"` (default `VellumAgent`)
  - `active_sports_league: str | None` (last resolved league, for context; save routing re-resolves per answer)
  - `pending_reroute: {target_agent: str, original_query: str} | None`
- **Depends on:** existing thread-state persistence.

### C2. Dispatcher (routing layer)
- **Responsibility:** decide, per turn, which agent handles the turn, and manage entering/leaving SportsAgent.
- **Logic:**
  - If `pending_reroute` is set: interpret this turn as the confirmation. Affirmative → set `active_agent = target`, clear pending, answer `original_query` (and the current turn if distinct). Negative/unclear → clear pending, stay in current agent, answer normally.
  - Else if `active_agent == VellumAgent`: run intent check. Sports intent → set `active_agent = SportsAgent`, record handoff to `Agent/Queries`, answer via SportsAgent. Otherwise → main agent.
  - Else (`active_agent == SportsAgent`): run intent check. Sports → SportsAgent answers. Non-sports → set `pending_reroute` (target resolved from intent: main, or a future sub-agent) and return a **hand-back question** instead of answering.
- **Interface:** `dispatch(thread_id, query) -> Decision` where `Decision ∈ {stay_main, enter_sports, stay_sports, ask_handback(target), confirmed_switch(target, original_query)}`.
- **Integration:** called inside `api.py` turn handlers (`_run_agent`, `_stream_agent_turn`) before streaming; selects which compiled agent to stream. Both agents emit the same SSE event shapes, so the streaming pipeline stays uniform.
- **Depends on:** C1, C3 (intent), the existing `SpecialistRouter`/`SkillRouteResolver` (reused + extended), the SkillStore fix.

### C3. Intent detection (broad sports + hand-back)
- **Responsibility:** classify a turn as sports vs not, robust across **any** sport.
- **Design:** hybrid —
  1. **Keyword fast-path:** a broad sports lexicon (leagues, sports nouns, common team/competition terms). Extends today's narrow `SportsAgent.can_handle` keyword set.
  2. **Fast-model fallback (Gemma 12B):** for ambiguous turns, a cheap classification call returns `sports | not_sports | unclear` (+ for non-sports, a hint of the better target).
- **Note:** combat sports (UFC/boxing/MMA) are now **in scope** — remove the disabled-keyword block in `SportsAgent`.
- **Depends on:** existing fast-model routing (`agent/llm`), `SkillRouteResolver`.

### C4. SportsAgent web-research executor
- **Responsibility:** answer a sports turn by researching the live web and citing real sources.
- **Design:** a dedicated `create_react_agent` (its own `LazyAgent`) with:
  - **Tools:** `web_search`, `context_mode` (used for `fetch_and_index`). No vault-snapshot reader, no SerpAPI tools.
  - **Prompt:** a sports-specialist system prompt: search first, read the top 1–3 results' full text, synthesize a structured answer (current status → key facts/stats → short analysis → freshness caveat), and **cite sources inline by number** matching the collected source list. Answers any sport including UFC/boxing.
- **Flow per turn:** `web_search(query)` → select top 1–3 results → `fetch_and_index(url)` for each → synthesize.
- **Depends on:** `web_search`, `context_mode`, the source collector (C6).

### C5. Sport/League resolver (save routing)
- **Responsibility:** map each answered sports turn to exactly one canonical `Library/Sports/<league>/` folder — never misfile.
- **Design:**
  - **Alias table** → canonical Title-Case-Hyphenated slug (`NBA`, `NFL`, `Cricket`, `Formula-One`, `Premier-League`, `Champions-League`, `Tennis`, `UFC`, `Boxing`, …).
  - **Fast-model fallback** for sports not in the table → canonical slug.
  - **Disambiguation guardrail:** "football" (soccer) vs `NFL` (American football) resolved from context/teams; if genuinely ambiguous, SportsAgent **asks** rather than guessing.
- **Interface:** `resolve_league(query, answer) -> slug`. Sets `active_sports_league` for the turn (can differ turn-to-turn).
- **Depends on:** fast model; the saver (C7).

### C6. Real-source pipeline
- **Responsibility:** turn the agent's actual web activity into structured citations visible end-to-end.
- **Backend:**
  - `Source` model: `{ url, title, snippet, domain, fetched_at }`.
  - **Source collector:** during the sports agent's `astream_events`, capture tool results — parse `web_search`'s formatted output into `(title, url, snippet)` blocks, and record each `fetch_and_index` URL/title. Order by first use; dedupe by URL. (No change to `web_search`'s string contract; a structured `web_search` variant is a possible later refactor.)
  - `ChatResponse` gains `sources: list[Source] = []`.
  - New SSE event `source` with a `Source` payload, emitted as sources are discovered; `final` includes the full `sources` list.
- **Frontend (minimal):** render a **real Sources list** (titled links → URLs, with domain) beneath sports answers, fed by `sources` from the stream/`final` — replacing the static `TOOL_TO_SOURCE` descriptions for SportsAgent answers. Reuse the existing footnotes area styling. The chip/hover-card/sidebar/activity-timeline polish stays deferred (the `source` event + `sources` field are the forward-compatible substrate for it).
- **Depends on:** C4, `api.py` SSE builder (`_sse`), `vellum-chat.html` (`handleSseBlock`, `renderMessage`).

### C7. Saving & handoff records
- **Responsibility:** persist sports conversations per-sport and record routing handoffs.
- **Design:**
  - Sports answer → `Library/Sports/<resolved-league>/` markdown note: frontmatter `type: sports-response`, `created: DD/MM/YYYY`, `league`, `sport`, `agent_version`, `private: false`, plus a `sources:` list; body `## Question` / `## Answer` / `## Sources` (links). Still indexed to FTS5/Honcho for cross-session memory.
  - Main→SportsAgent handoff → recorded in `Agent/Queries/` (the initiating query + `routed_to: SportsAgent` + resolved league + reason).
- **Depends on:** Obsidian write layer (`agent/tools/obsidian_write.py`, `ObsidianVault`), folder policy (C8), C5.

### C8. Folder policy & privacy
- **Folder policy:** permit agent **writes** under `Library/Sports/<league>/` (today `Library/` is agent-read-only except ingestion automation). Update `backend/agent/obsidian/folder_policy.py` (and `ProjectContext` if it gates this). This is a deliberate deviation made per user instruction; CLAUDE.md already contemplates ingestion/retention automation managing `Library/` source folders.
- **Privacy:** sports web queries are typically GREEN/public and pass the gate normally. `fetch_and_index` output is external/unscrubbed (per CLAUDE.md §3) → **summarize before saving/displaying**, never mix with private-folder content. Saved sports notes live in a public folder (sent-to-LLM), consistent with the existing `Sports/` policy.

### C9. Retirement / deletion
- **Delete:** `backend/agent/daemon/` (package), `scripts/start-daemon.ps1`, `scripts/stop-daemon.ps1`, the `vellum-daemon` entry in `backend/pyproject.toml`, the daemon settings + interval validator in `backend/agent/config.py`, `backend/tests/test_sports_daemon.py`, and the `.daemon-runtime/` line in `.gitignore`.
- **Retire from the answer path:** remove `should_fetch_sports` / `fetch_sports_if_curious` from the live agent tool list (`graph/agent.py`); stop using `Library/Sports/<league>/latest.md` snapshots for answering; the SerpAPI importer is no longer part of the answer path.
- **Keep intact:** the curiosity **scorer** in `backend/agent/tools/sports_curiosity.py` (scoring functions) for the later proactivity phase. (It may become temporarily unreferenced by the live path; that is acceptable and intentional.)

## Data flow (end-to-end, a sports turn)

1. User sends "who won the last F1 race + stats". Intake + privacy gate run as today; query logged to `Agent/Queries/`.
2. Dispatcher: `active_agent == VellumAgent`, intent = sports → enter SportsAgent; annotate the `Agent/Queries` record with `routed_to: SportsAgent`.
3. SportsAgent: `web_search("last F1 race result …")` → picks top 2–3 results → `fetch_and_index` each → synthesizes a stat-rich answer citing `[1][2]` inline.
4. Source collector builds `sources=[{url,title,snippet,domain,fetched_at}, …]`; `source` SSE events stream; `token` events stream the answer.
5. Sport/League resolver → `Formula-One`. Saver writes the note to `Library/Sports/Formula-One/` and indexes to FTS5/Honcho.
6. `final` SSE carries `answer + sources`. UI renders the answer + a real Sources list.
7. Next turn "and the NBA finals?" → still sports → SportsAgent answers, resolver → `NBA`, saved under `Library/Sports/NBA/`.
8. Next turn "draft an email to my landlord" → non-sports → dispatcher sets `pending_reroute={target: VellumAgent, original_query}` and Vellum asks "That's outside sports — hand back to the main agent?" On "yes", main agent answers the email request.

## Data shapes

- `Source` (pydantic): `url: str`, `title: str`, `snippet: str = ""`, `domain: str = ""`, `fetched_at: str = ""`.
- `ChatResponse`: existing fields + `sources: list[Source] = []`.
- SSE `source` event: one `Source` as JSON.
- Saved sports note frontmatter: `type: sports-response`, `created: DD/MM/YYYY`, `league: <slug>`, `sport: <slug>`, `agent_version: vellum-1.0`, `private: false`, `sources: [<url>, …]`.

## Testing strategy

- **Intent/dispatcher:** enter-sports from main; stay-sports across multiple sports (NBA→F1→cricket→UFC); non-sports → ask-handback; confirmation → switch + answers original query; "no" → stays.
- **SportsAgent flow:** with `web_search` + `fetch_and_index` mocked, produces an answer + ordered, deduped structured sources; UFC/boxing now answered (not blocked).
- **Sport/League resolver:** NBA/F1/Premier-League/NFL/Cricket/UFC/Boxing → correct slugs; "football" vs NFL disambiguation; ambiguous → asks.
- **Source pipeline:** `ChatResponse.sources` populated; `source` SSE events emitted; `final` includes sources.
- **Saving:** sports answer written under the correct `Library/Sports/<league>/`; never cross-filed; handoff recorded in `Agent/Queries/`; folder-policy permits the write.
- **Retirement:** daemon modules/scripts/config/tests removed; `should_fetch_sports`/`fetch_sports_if_curious` no longer in the live tool list; curiosity scorer importable and unit-tested still.
- **SkillStore fix:** resolves `.skills` from repo root regardless of cwd; a real sports query routes via the skill from `backend/` cwd.
- **Integration smoke (mocked web):** sports query → routes → researches → cites real sources → saves to the right league folder; full prior test suite stays green.

## Phasing (likely two implementation plans)

- **Plan 1 — Routing & lifecycle:** SkillStore cwd fix; active-agent thread state; dispatcher + broad intent + hand-back; delete the daemon; remove the SerpAPI tools + vault-snapshot reader from the live path; keep the scorer; wire SportsAgent into `api.py` **with `web_search`** so it already produces real (snippet-level) answers and records the `routed_to` handoff in `Agent/Queries`. Net: sports queries route to SportsAgent and back, answered from the live web, with tests.
- **Plan 2 — Research depth, citations & saving:** read-top-articles depth (`fetch_and_index`); source collector + `Source` / `ChatResponse.sources` + `source` SSE event + minimal real Sources list in the UI; sport/league resolver; saving answers to `Library/Sports/<league>/` and enriching the `Agent/Queries` handoff with the resolved league; folder-policy write permission.

Each plan is TDD, task-by-task, committed and pushed per task.

## Assumptions

- Combat sports (UFC/boxing/MMA) are allowed.
- League/sport switches stay inside SportsAgent (seamless, just changing the save folder); only non-sports turns trigger the hand-back prompt.
- Minimal real Sources list is acceptable "for now"; the ChatGPT-style chips/hover/sidebar/activity UI is a later phase built on the same `source` event + `sources` field.
- The curiosity scorer is kept (not deleted) even if temporarily unreferenced.
- Saving sports answers to `Library/Sports/<league>/` is an intended, user-directed deviation from the "agent writes only under `Agent/`" rule.
