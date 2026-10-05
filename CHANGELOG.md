# Changelog

All notable changes to Vellum will be documented in this file.

The project follows Semantic Versioning once tagged releases begin. Vellum is currently in alpha development and has no tagged release history yet.

## [Unreleased]

- Every built-in specialist has a complete hybrid profile: task-local instructions, pinned model/reasoning, own Hermes skills, scoped memory and an allowlisted reasoning/tool loop. Exact action handlers preserve confirmation and verified receipts.
- Specialists can request bounded, attributed memory packets through the existing memory owner. Both profiles' sharing permissions, approved scopes, current thread/user, relevance, expiry and local processing are checked; packets cannot authorize actions or mutate shared memory.
- Add local YouTube History reads through the existing browser, with day-level evidence, account binding, explicit freshness/failure status, and opt-in scheduled refresh.

- Clear MusicAgent song additions and removals execute without a second confirmation, with captured targets, single writes and membership read-back. Liked playlist aliases, misspelled saved-song titles, version selections and destination-preserving corrections stay in the music workflow.
- Mixed confirmations such as “NBA news and yes” separate the exact pending action from the independent specialist question and stream each result on completion. A single yes cannot authorize queued changes.
- Album requests use typed MusicAgent plans; the latest album comes from the artist’s paginated Spotify catalog and release dates, with context playback verification instead of a song search.
- Skill curator backups reserve unique, ordered folders when Windows clock timestamps tie, preserving backup retention and rollback checks.
- Knowledge Core ingestion jobs retain newest-first order when creation timestamps tie, so a later failure remains visible in connector health.

- Music requests activate Vellum's existing Spotify player before playback; an explicit stop releases it after Spotify confirms it is paused. Pause leaves the player ready to resume, and connection or audio-policy failures remain visible.
- Relative seeking, volume changes, repeat and shuffle use direct typed MusicAgent plans with bounded Spotify calls and state read-back before reporting success. Current or named songs can be checked, added or removed from Liked Songs and playlists with exact targets.
- Curated playlist creation handles Spotify's public-playlist contents restriction by previewing real catalog songs with an explicit source/ranking limitation; requested names and song counts are preserved.
- Agent Reach publication has a shared write/read-back deadline including command-lock waits. Uncertain writes are never repeated automatically; explicit X targets and confirmed-action follow-ups stay with XAgent.
- Credential registration order remains stable when creation timestamps tie, avoiding random key selection in provider pools on Windows.

- Independent specialist tasks run concurrently through the shared delegation runtime and appear in chat as each finishes. Dependent tasks stay ordered; partial failures and operation-bound confirmations retain their own results and targets.
- Personal YouTube summaries use bounded local synthesis with readable evidence-based fallback. Creator watch queries filter the full imported history, preserve channel renames, and support follow-ups without substituting public search results.
- X posting intent recognizes omitted pronouns, shorthand, and corrections; self-introduction drafts identify Vellum and stay short. Music deduplicates song suggestions, accepts a clear single-choice yes, seeks within current audio, reads live podcast/song state, and verifies playlist names and songs before reporting success.

### Fixed
- Personal liked-video requests, including “liked vidoes” and “what videos have I liked?”, read the connected YouTube account instead of searching public tutorials.
- The browser address field searches ordinary words and accepts website addresses and local development URLs without turning search text into an invalid hostname.
- Opening the UI server's base address now redirects to Vellum instead of returning 404; entry redirects retain view and conversation query parameters.
- Interrupted or overlapping browser cleanup finishes closing the owned Brave process before reopening, preventing a stranded process from locking Vellum's browser profile.
- The Browser sidebar entry reads current readiness before opening, so a first click during startup launches the dedicated session instead of leaving it closed. Launch failures use the existing toast helper to show the error without crashing the handler.
- Browser worker shutdown clears dedicated transport ownership before restart; closing the in-app session keeps its ownership until shutdown. Browser delegation prompt contracts retain the compact prompt budget and specialist-only browser capabilities.
- Automation approvals compare the reviewed record's content, so changes made within the same timestamp cannot reuse an old confirmation.
- Music follow-ups retain the requested song across current-track questions, distinguish original-version selection from a new title, and prioritize fresh Liked Songs requests over failed searches. Spotify title matching accepts featured-artist credits while preserving version qualifiers.
- Personal YouTube data questions use local Takeout evidence instead of public how-to search results; broad questions no longer accidentally filter out the imported history.
- X publication requires a valid receipt and Agent Reach read-back before reporting success. Unconfirmed writes retain a check-before-retry warning and are never automatically reposted.
- Local book and music synthesis request JSON output with bounded model-call deadlines. Book synthesis uses exact short source labels mapped back to canonical evidence, with strict claim validation and refreshed Book/YouTube cache versions.
- Backend CI contracts cover empty or populated Ollama discovery, specialist answer passthrough and stream alignment, the podcast tool catalog and Markdown renderer; book UI paths and mocked Windows scan timeouts run independently of runner platform.
- Editable backend installs include the pinned Agent Reach and X CLI dependencies, matching the launcher requirements and allowing clean CI runners to import the X provider.
- Reconciled settings, Adaptive UI and action-parity changes with local model discovery, Calendar and Spotify workflows; connection upgrades retain saved public client IDs and plugin contributions expose both connection and playback actions.
- Chat recall and playback-control matching avoid regex backtracking on long punctuation or whitespace inputs; clock follow-ups retain normalized whitespace handling. Calendar OAuth forwarding tests check the exact authorization URL.
- Broad Discover requests read imported YouTube interests. Operational X commands are excluded from durable profile facts; Honcho portraits use extant canonical chats and exclude explicit temporary demonstrations.
- X confirmations execute the original pending payload rather than republishing its preview. Read requests retain their read intent. Natural follow-ups retain real targets; newest posts are ordered by identity and private failures require Agent Reach reconnection.
- Book queries follow EPUB chapter boundaries across separate title/body files. UI annotations no longer trigger unrelated memory/inventory requests; invalid optional personal observations do not discard a validated answer.
- Spotify chat retains playback-control commands and acknowledgements in both main and specialist views. Liked playlist aliases and numbered songs use saved tracks; emoji names retain identity; saved playlist lookup paginates fully and accepts Spotify links. Missing personalized mixes request a link, public matches require selection, and podcast requests resolve shows/episodes without falling back to songs. Player callbacks handle episode artwork/show metadata safely.
- Music playback now recognizes next/skip phrases before song search, resolves named playlists such as Kannada bangers, plays Liked Songs from saved tracks, and asks for an artist when song titles are ambiguous. Artist corrections use bounded context in the existing conversation state. Playback-only chat turns retain their acknowledgements; the player refreshes upcoming tracks and removes repeated queue rows.

- Calendar reads include synced calendars such as F1; contextual deletion keeps real event/calendar IDs and accepts one confirmation or an explicit retry of the same failed action.

### Added
- BrowserAgent delegation to a separate local Brave session, with an in-app live view, tabs, navigation, downloads, pause/resume and manual takeover. Browser interactions use existing confirmation and App Action owners; the sidebar keeps secondary destinations under More.
- Local Takeout libraries for YouTube Music songs, subscriptions, Watch Later, playlists and channel metadata through the existing Knowledge Core, with idempotent replay and explicit snapshot freshness.
- Local Windows EPUB OCR with image provenance and uncertainty labels, versioned parser upgrades and compatible citation maps; canonical Book-to-Skill retains local embeddings and grounded Gemma synthesis.
- Agent Reach reply reads and bounded X follow-up context, with operation-bound confirmation and no automatic retry of uncertain writes.

- Spotify playback inside Vellum through the Web Playback SDK, with device ownership, expiring-token refresh, reconnection, and an explicit audio activation control. Native webview audio support still requires live validation.
- Typed Spotify play/pause/skip actions shared by chat and player buttons, overlapping-click protection, song-title resolution, and bounded playback health diagnostics. Continuous audio remains a live browser validation gate.
- MusicAgent in the existing specialist catalog, with an exclusive Spotify skill/tool boundary, provider-neutral music plans and adapters, local intent parsing, song-title playback, and named playlist shuffle. Actual playback results pass through to chat without a second model rewrite or cached side effects.
- MusicAgent previews new playlists with resolved song names and artists, then creates private playlists only through the shared pending-action confirmation path. Spotify creation uses the current-user playlist endpoint; uncertain writes are never automatically replayed.

- Google Calendar plugin connection status, disable controls, event search, and collision-aware scheduling with confirmed alternative times.

- Windows AMSI Book scanning with the installed antivirus provider and explicit OCR-required import status.
- Native Ollama streaming with a configurable 16K context window and local attachment conversion.
- Configurable local inference batch size, matching the local Honcho transport to avoid repeated model reloads.
- Local synthesis of fetched Discord messages for summary requests, retaining message provenance.
- Typed, privacy-aware specialist delegation from natural-language intent, with compact profile discovery and profile-scoped skills.
- Ollama capability and context discovery so local models expose their native tool-call support accurately.
- Local Ollama inference through the existing routed chat runtime, with Qwen 3.5 9B as the default primary model.
- Live Ollama model discovery for the model picker, including automatic replacement when the selected local model is removed.
- Action Parity inventory and served-JSX contract gate for visual controls, with explicit non-state exemptions, deferrals, and disposable browser validation.
- Adaptive UI rules for reversible presentation preferences, with three-signal learning, context scoping, explanations, Undo suppression, and local rule controls.
- Capability-discovery contract for the frontend/backend boundary through `/api/capabilities`.
- Stable API adapter pattern for the Vellum web UI.
- Memory Orchestrator surfaces for summaries, saved memories, archived memories, settings, dreaming runs, and conversation imports.
- Maintained Obsidian Knowledge Wiki under `Vault/Knowledge` with explicit trust, provenance, history, linting, and source-aware ingestion.
- Idempotent Obsidian conversation export and retention workflows.
- Profile-based specialist delegation runtime with isolated task packets.
- Profile-scoped specialist response cache with freshness classes and stale fallback behavior.
- Profile-only LLM specialist support with declarative YAML profiles.
- Delegation audit records without raw prompts or private context.
- OpenRouter routing resilience with credential pools, provider policy, fallback chains, health state, cooldowns, and settings UI support.
- Direct provider handling for configured OpenAI routes.
- Hermes-compatible `SKILL.md` package system for procedural memory.
- Approval-gated skill mutation coordinator with package validation, locking, snapshots, catalog updates, and audit records.
- Privacy-safe `/learn` and `skill_learn` workflows.
- Background skill signal detection and proposal flow.
- Canonical skill catalog with duplicate detection and usage intelligence.
- Recoverable skill curator maintenance.
- Secure multi-source Skills Hub and marketplace adapters, including bundle quarantine and security scans.
- Skills Hub UI surface and tests.
- Spotify plugin status, OAuth, playback, player action, and recovery support.
- Agent/tool capability services for memory, MCP, X, YouTube, and shared tool registry surfaces.
- Live X topic synthesis over Agent-Reach results using the active Vellum model, plus direct account-post retrieval through `x.user_posts`.
- Voice STT/TTS modules and API coverage.
- Computer-use routing, guarded sessions, native Windows driver components, and overlay/runtime tests.
- Coding session service and Codex/Claude adapter coverage.
- Telemetry and usage ledger support for provider/tool usage.

### Changed

- Keep specialist model selection request scoped and persist specialist exchanges in the existing chat checkpoint for follow-up questions.
- Coalesce background user-model refreshes after an idle interval and bound local Honcho inference budgets; keep terse clarifications tied to the current substantive request.
- Batch local Honcho derivation before inference so short conversations do not trigger a GPU job after every exchange.
- Preserve active chat navigation during delayed New Chat receipts and startup hydration.
- Render answer Markdown safely, bound skill summaries, use authenticated X authorship for own-post requests, and show the next sports event with IST first when its source date and timezone are available.
- Expanded the provider-neutral runtime instructions with evidence-based personal intelligence, user-correction precedence, task-dependent context balance, and bounded self-improvement through existing memory, skill, and profile policies.
- Migrated remaining settings, memory, Spotify connection, and LLM-routing mutations to typed App Actions with catalog-aware UI dispatch and compatibility adapters.
- Unified explicit memory creation with the canonical FTS-backed memory writer and made credential-pool reset receipts report actual state changes.
- Consolidated chat history ownership around `data/ui/conversations.json` and `/api/conversations`, with Obsidian conversation notes as projections.
- Clarified that Knowledge Wiki pages are maintained synthesis and raw Library material requires explicit approved ingestion.
- Shifted procedural memory from legacy JSON skill records toward Hermes-compatible `SKILL.md` packages.
- Moved frontend integration toward capability-driven feature discovery instead of hardcoded endpoint assumptions.
- Updated memory/retrieval flows to keep current conversation context above older memory when conflicts exist.
- Updated Docker services so Honcho and PostgreSQL are the local service dependencies while vector storage is configured through embedded ChromaDB.
- Refined routing behavior so visible streamed output is not replayed through an automatic model switch.

### Fixed

- Keep the API responsive during slow Spotify playback/device actions, refresh expiring credentials before requests, coalesce concurrent expired-token recovery, and distinguish empty command acknowledgements from inactive playback.
- Isolate invalid plugin connectors during valid tool lookup while preserving plugin path validation.
- Preserve official Formula 1 calendar excerpts and attribute unverified X news claims to their authors.
- Natural follow-up recall now answers exact current-chat and previous-chat questions from canonical conversation history.
- Relative time follow-ups now scan prior event answers and convert US game times to the configured user timezone (Asia/Kolkata by default).
- In-progress turns survive conversation refreshes and persist the submitted user message before streaming starts.
- Visible answers now omit raw Markdown heading markers and inline reference dumps while retaining structured source chips.
- Natural X requests now distinguish publishing, bookmark ordinals and summaries, latest liked posts, latest account posts, and broad topic summaries; singular requests return one result and links remain in structured Sources.
- X retrieval no longer falls back to generic web search; Agent-Reach remains primary and the separately configured xAI/SuperGrok path remains optional.
- Agent-Reach commands no longer depend on a network status preflight that could time out even when authenticated X reads were working.
- Creative posting requests such as “tweet something funny” now draft the post with the active Vellum model and present it for confirmation; “tweet this” can reuse the preceding assistant message.
- Terse retry and explanation follow-ups such as `??` and “why?” now stay attached to the failed X request instead of recalling an unrelated previous chat.
- Completed X specialist results take precedence over stale main-model text from an earlier topic in the same chat.
- Agent-Reach accepts the published `twitter-cli` 0.8.5 release instead of requiring a nonexistent 0.8.6 package.
- Completed specialist results survive local-model greetings, deferred answers, duplicate delegation loops, and graph recursion limits.
- Restored the served Vellum interface by importing React's `useMemo` hook used during startup.
- Knowledge health checks now use the App Actions boundary, source imports require maintained synthesis, and local YouTube intelligence rebuilds remain available without OAuth.
- Spotify playback recovery on inactive devices.
- Provider routing and 404 handling.
- Routing settings control polish.
- Frontend/backend contract regressions covered by tests.
- Knowledge Wiki and conversation projection edge cases covered by regression tests.

### Security

- Added confirmation-bound, redacted credential and destructive-setting changes with rollback-safe provider-key persistence.
- Enforced zero-data-retention OpenRouter routing controls.
- Added privacy scrubbing for skill authoring and learning flows.
- Added security checks for remote skill packages and marketplace sources.
- Kept skill deletion recoverable and approval-gated.

## Release History

No version has been tagged yet. The first release should move the verified entries above into a dated version section and create a fresh `[Unreleased]` section.
