# Changelog

All notable changes to Vellum will be documented in this file.

The project follows Semantic Versioning once tagged releases begin. Vellum is currently in alpha development and has no tagged release history yet.

## [Unreleased]

- YouTube creator tracking chooses channels from repeated recent saved activity and explicit long-term, seasonal, current, former, and excluded relationships. Public Atom polling has response and request limits, backoff, quiet first-run baselines, persistent video deduplication, and retryable delivery through the existing Automation and Conversation owners. Creator assessments are local and account scoped; searches and recommendations do not endorse creators.

- Music-request parsing consumes repeated whitespace and polite prefixes without regex backtracking, preserving provider selection, quoted titles, history artist filters and playlist/album commands. CodeQL's reported slow-regex paths now use single-pass delimiters or non-overlapping normalized matches.

- Browser new tabs now show the five approved local wallpaper homepages, with Google, Brave, DuckDuckGo, Startpage and SearXNG selection beside the title. Search preferences, SearXNG instance and custom shortcuts persist through the existing browser App Action. Native homepage input avoids streamed-frame latency; new tabs do not wait for a remote homepage. Compact controls and workspace expansion leave more room for the page and restore the previous split without losing tabs.

- Browser engine menus fit within the homepage even during instance setup, with scrolling when space is limited. SearXNG stays centered when selected and opens configuration on request instead of moving the homepage upward.

- MusicAgent understands random saved-playlist requests, short collection follow-ups, small control typos and casual/formal music wording. Skip receipts retain scoped navigation so `go back` requests the previous track. Artist-only song requests verify Spotify credits; `69` means 6ix9ine while explicit numeric playlists retain their names. YT Music aliases preserve the selected provider. Automatic Vellum playback activation covers polite and casual requests; absolute volume percentages remain absolute when followed by `please`.

- Album shorthand such as `latest album from J Cole` delegates directly to MusicAgent. Typed `can u play` requests activate Vellum audio before sending chat, including albums. Artist punctuation matching preserves non-Latin names and ambiguous identities; playlist-count wording with `is have` reads the saved library instead of reaching a model-generated count.

- MusicAgent reads playlist counts/retrieval directly for saved-playlist wording and selects random playback only from the saved collection, including common playlist typos. Song/album artist corrections survive trailing player controls and attached chat context; expired targets clarify without model timeouts. Credited `(with Artist)` suffixes no longer hide the original song. Title-before-`album` requests retain album identity, offer catalog artist choices and acknowledge actual credits instead of playing a track. Recent legacy album targets recover without a data migration; incorrect collaborator searches get one title-only retry before offering verified album credits.

- Song requests without an artist prefer an earlier studio recording over labelled covers/remixes and later recordings. Explicit artists and version titles remain authoritative; tied or incomplete catalog evidence asks for clarification. MusicAgent retains preflighted unfinished compound actions in its existing thread context, so an artist reply finishes the volume/shuffle steps without repeating completed actions. Cancellation, replacement, expiry, errors and pending approvals preserve their boundaries; normal and streaming chat route active clarifications despite attached old chat context.

- MusicAgent executes up to eight combined typed music actions in order, returning a receipt for each. Current-song edits bind to measured playback before an `and` request changes songs; `then` resolves the new song only after playback read-back. Displayed charts survive intervening library/player controls, including named-country follow-ups and the `sogns` typo. Invalid arguments are checked before writes; failures or confirmation previews stop remaining actions without replaying uncertain writes, and new explicit compound library edits clear older pending targets.

- MusicAgent understands possessive country names and global/regional chart playback wording. Chart and album discovery stay in its existing conversation context for “play it” and album-name follow-ups, even when another specialist is selected. Live artist/album questions use measured playback metadata; duplicate Spotify artist names are corroborated with Kworb identity. Chart playback requires read-back before acknowledging success, retains its exact track list for an explicit retry and never retries uncertain writes automatically.

- MusicAgent reads Kworb directly for monthly listeners, artist rankings, song streams and daily/weekly country charts, retaining source links and snapshot dates. Reads use a bounded six-hour public-page cache without a search-provider request. Album discovery verifies Spotify release dates; explicit chart playback uses the listed track IDs through the existing Spotify integration. Unavailable monthly-listener evidence retains the main agent's public-web fallback.

- Windows browser sessions use Brave's normal renderer behind the in-app preview, restoring YouTube captions and playback beyond the reproduced 42-second cutoff. Only the owned browser's windows are hidden; exact child-announced CDP endpoints, retained last tabs and bounded cleanup preserve session ownership and reopening.

- MusicAgent directly handles mute/unmute, restarting the current song and current-artist questions. Unmute restores the measured pre-mute volume on the same device; repeat undo restores the verified preceding mode in the same chat. Unverified or unavailable controls do not claim success. Artist monthly-listener questions use the main agent's canonical public-web search and official-profile reader, preserving source links and lookup dates.

- Shuffle on/off commands and maximum-volume requests now use direct MusicAgent controls, including a contextual `max*` correction after a truncated volume request. Fresh local SDK volume remains available when paused playback has no track snapshot; expired readings and other devices retain their boundaries.

- MusicAgent directly handles absolute and relative volume wording, saved-playlist count/list questions and common playlist typos. It preserves the last successful seek distance for “go back the same amount,” and exact emoji playlist choices select the saved identity without public search.

- Accepted music suggestions retain a distinct continuation queue, and playlist suggestions reuse the last selected playlist or a verified saved Daily Mix. Personal playlist lookup asks about emoji-only choices, recognizes Telugu spelling variants, and never substitutes public playlists. Vellum's leased SDK reports fresh song and volume state; local volume changes require measured acknowledgement and the player preserves fresh SDK state against delayed HTTP responses.
- Continuous YouTube history refresh uses quiet temporary tabs and the existing opt-in automation. Knowledge Core retains deduplicated video/day evidence across refreshes, isolates browser accounts, and preserves saved history on failures. Fresh page counts stay separate from accumulated coverage; exact watch times and repeat plays remain unavailable.
- Refresh the frontend lockfile to patched Vitest and source-map-js versions after CI dependency-audit findings.

- Every built-in specialist has a complete hybrid profile: task-local instructions, pinned model/reasoning, own Hermes skills, scoped memory and an allowlisted reasoning/tool loop. Exact action handlers preserve confirmation and verified receipts.
- Specialists can request bounded, attributed memory packets through the existing memory owner. Both profiles' sharing permissions, approved scopes, current thread/user, relevance, expiry and local processing are checked; packets cannot authorize actions or mutate shared memory.
- MusicAgent recalls available dated Spotify history using local-day boundaries and verified artist credits instead of model guesses. User-stated music preferences persist in its existing private memory scope; bounded conversation-based suggestions preview a real song and require one-time acceptance before playback. Spotify results are excluded from background AI memory learning.
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
- YouTube Agent reads recent watch history from the account signed into Vellum’s Browser, with a Refresh history button in overview and chat. Reads run in a temporary background tab without opening the panel or changing the visible page. Account-scoped local snapshots preserve visible day labels and video links; failed or changed-account reads never substitute older imports or public searches.
- Sources and Activity explicitly select their own right-panel view instead of reopening the last-used Browser view. The dedicated browser session stays open in the background.
- Browser Escape exits a remote video's fullscreen without hiding the panel. New tabs focus the address bar immediately and load independently; background tabs and child-frame navigation no longer restart the visible page feed. First clicks combine takeover and input in one checked action. Alt+L/T/W and Alt+1–9 provide panel shortcuts while the host browser retains its reserved Ctrl shortcuts.
- Windows closes Vellum's dedicated Brave process when the backend abruptly exits, preventing an orphaned browser from locking its profile and breaking launches from both the sidebar and chat.
- Blank browser sessions and user-created tabs open Google's homepage. Recognized website names open directly instead of taking an unnecessary Google Search detour that can encounter a CAPTCHA before reaching the destination.
- Personal YouTube reads honor the requested entity, quantity, creator filter, and format through validated local-model plans. Follow-up links use the actual displayed list; missing context and read failures explain the limitation instead of returning unrelated public results.
- YouTube liked-video replies display every fetched video in a numbered list with clickable titles. Subscription-count questions return the full connected-account channel count, including common wording and typos; imported counts remain labeled as snapshots.
- The Brave panel follows its available page size without gray letterbox bands. Live frames replace one-second screenshot polling, page clicks take control automatically, and rapid typing and scrolling use ordered batches without a status refresh for every input.
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
