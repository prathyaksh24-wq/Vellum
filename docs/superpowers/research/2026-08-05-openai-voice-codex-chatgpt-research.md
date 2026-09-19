# OpenAI Voice: Realtime API Models, Voice in Codex, and Voice in ChatGPT

Research report — 2026-08-05
Primary sources: `https://developers.openai.com/api/docs/...` (model pages and guides, fetched 2026-08-05, cited by URL path), `https://openai.com/index/...` (product announcements, fetched 2026-08-05, cited by URL path), `https://github.com/openai/codex` (releases page and commit messages, cited by URL), `https://help.openai.com/en/articles/8400625-voice-mode` (voice FAQ), `https://deploymentsafety.openai.com/gpt-live` (GPT-Live system card), and `https://learn.chatgpt.com/docs/prompting.md` (ChatGPT desktop dictation). Anything not found in these is reported as "not found" inline; secondary sources are labeled as such.

---

# Topic 1 — OpenAI voice & realtime models in the API

## 1. The realtime voice model lineup (mid-2026)

- **`gpt-realtime`** — "our first realtime model", GA since 2025-08-28, snapshot `gpt-realtime-2025-08-28`. Input: text/audio/image; output: text/audio. 32K context, 4,096 max output tokens. Pricing per 1M tokens: text $4 / $0.40 cached / $16 output; audio $32 / $0.40 cached / $64 output; image $5 / $0.50 cached. Transports: WebRTC, WebSocket, SIP. "Not supported in the Chat Completions or Responses APIs." (`https://developers.openai.com/api/docs/models/gpt-realtime`)
- **`gpt-realtime-2`** — "the most capable realtime voice model" (2026-05-07). First realtime model with "GPT-5-class reasoning" (`https://openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api/`). 128K context (up from 32K), 32K max output tokens, configurable reasoning effort `minimal | low | medium | high | xhigh` with `low` as default. Pricing per 1M tokens: text $4 / $0.40 cached / $24 output; audio $32 / $0.40 cached / $64 output (`https://developers.openai.com/api/docs/models/gpt-realtime-2`). New behaviors per the announcement: **preambles** ("let me check that"), **parallel tool calls with tool transparency** ("checking your calendar"), **stronger recovery behavior** after errors, better tone control, and stronger retention of domain vocabulary. Eval claims: "GPT‑Realtime‑2 (high) scores 15.2% higher on Big Bench Audio than GPT‑Realtime‑1.5"; "(xhigh) scores 13.8% higher on Audio MultiChallenge" for instruction following (announcement URL above).
- **`gpt-realtime-2.1`** — the model the current guides recommend for new voice agents; the WebSocket example connects with `wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1` (`https://developers.openai.com/api/docs/guides/realtime`, `https://developers.openai.com/api/docs/guides/realtime-websocket`). No dedicated pricing page found for 2.1 ("not found"; see Not-found).
- **`gpt-realtime-mini`** (snapshots 2025-10-06, 2025-12-15) and **`gpt-realtime-1.5`** (snapshot 2026-02-23) — listed as supported models only on Microsoft's Foundry page (secondary: `https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio-webrtc`); no dedicated OpenAI model pages found ("not found"). `gpt-realtime-1.5` is also used as the eval baseline in the May 7 announcement.
- **`gpt-realtime-translate`** (snapshot 2026-05-06) — live translation model: "translates speech from 70+ input languages into 13 output languages while keeping pace with the speaker", priced **$0.034 per minute** (announcement URL above; dedicated guide `https://developers.openai.com/api/docs/guides/realtime-translation`).
- **`gpt-realtime-whisper`** (snapshot 2026-05-06) — streaming speech-to-text that "transcribes speech live as the speaker talks", priced **$0.017 per minute** (announcement URL above).
- **`gpt-live-transcribe`** — streaming transcription model, $0.017/min, served by `v1/realtime/transcription_sessions` and recommended in the realtime transcription guide (`https://developers.openai.com/api/docs/models/gpt-live-transcribe`, `https://developers.openai.com/api/docs/guides/realtime-transcription`).

## 2. Audio in Chat Completions: `gpt-audio-1.5`

- `gpt-audio-1.5` is the current audio-in/audio-out model for the Chat Completions API ("best voice model for voice in/out with Chat Completions"); 128K context, 16,384 max output tokens; pricing per 1M tokens: text $2.5 / $10, audio $32 / $64 (`https://developers.openai.com/api/docs/models/gpt-audio-1.5`). This is the non-realtime path: TTS/STT-style turns without a persistent session.

## 3. Pricing summary (as published, per the pages cited above)

| Model | Context | Text in/out per 1M | Audio in/out per 1M | Per-minute |
|---|---|---|---|---|
| gpt-realtime | 32K | $4 / $16 | $32 / $64 | — |
| gpt-realtime-2 | 128K | $4 / $24 | $32 / $64 | — |
| gpt-realtime-translate | — | — | — | $0.034 |
| gpt-realtime-whisper / gpt-live-transcribe | — | — | — | $0.017 |
| gpt-audio-1.5 (Chat Completions) | 128K | $2.5 / $10 | $32 / $64 | — |

## 4. Realtime API architecture

- **Guide index / overview** — compares voice-agent, translation, and transcription session types; WebRTC vs WebSocket vs SIP (`https://developers.openai.com/api/docs/guides/realtime`).
- **Voice agents guide** — two canonical patterns: *speech-to-speech* (Realtime session) and *chained voice pipeline* (STT → LLM → TTS); official TypeScript SDK objects `RealtimeAgent` / `RealtimeSession` and Python `VoicePipeline` (`https://developers.openai.com/api/docs/guides/voice-agents`).
- **WebSocket** — server-to-server transport with a standard API key (`Authorization: Bearer`), the `OpenAI-Safety-Identifier: srv_...` header required for safety/abuse attribution, raw PCM 24 kHz audio, and manual management of the input audio buffer (`session.input_audio_buffer` events); Node `ws` example included (`https://developers.openai.com/api/docs/guides/realtime-websocket`).
- **WebRTC** — recommended for browser/mobile; client creates an ephemeral token via `POST /v1/realtime/sessions` and connects media directly; no manual audio buffering (`https://developers.openai.com/api/docs/guides/realtime-webrtc`).
- **VAD / turn detection** — `server_vad` (default) or `semantic_vad`; configured via `session.audio.input.turn_detection`; server emits `input_audio_buffer.speech_started` / `input_audio_buffer.speech_stopped`; transcription-session VAD behavior depends on the model, and `gpt-realtime-whisper` requires `turn_detection: null` (`https://developers.openai.com/api/docs/guides/realtime-vad`).
- **Realtime transcription sessions** — session type `"transcription"`, audio input format `audio/pcm` at 24000 Hz 16-bit little-endian fed via `input_audio_buffer.append`; transcript deltas stream back (`https://developers.openai.com/api/docs/guides/realtime-transcription`).
- **Conversations** — session objects are mutated with `session.update`; WebSocket clients drive the input buffer manually; text and audio events interleave in a defined order (`https://developers.openai.com/api/docs/guides/realtime-conversations`).
- **GA announcement (2025-08-28)** — WebRTC/WebSocket/SIP transports, function calling, image input, and MCP server support (`https://openai.com/index/introducing-gpt-realtime/`).
- OpenAPI reference for the realtime resources exists at `https://developers.openai.com/api/reference/resources/realtime` (not fetched in detail).

## 5. Voice-to-action: tools, MCP, and the tool loop

- **Function tools** — declared at session level via `session.tools` in `session.update` (or as item-level tool items); the *client* executes them and returns the result with `function_call_output`, which resumes the model turn (`https://developers.openai.com/api/docs/guides/realtime-mcp`).
- **MCP tools** — either a remote MCP server via `server_url` (executed by the Realtime API itself) or an OpenAI-managed `connector_id` (e.g. Google Calendar) (`https://developers.openai.com/api/docs/guides/realtime-mcp`).
- **The Codex loop as the reference implementation** — in Codex, the voice model emits a function call, the app-server's sideband WebSocket picks it up, routes it through the approval workflow, and feeds the result back into the conversation (secondary walkthrough: `https://codex.danielvaughan.com/2026/04/10/webrtc-realtime-voice-codex-cli/`, citing PRs #17057/#17188/#17176; primary changelog facts in Topic 2 §1 confirm the shape).
- **GPT-Realtime-2 tool transparency** — the model announces actions audibly ("checking your calendar") and can call multiple tools in parallel (announcement URL above).
- **GPT-Live delegation** — in ChatGPT, Live "can use web search and memory" by handing off to a frontier model (Topic 3 §1).

## 6. Official SDK examples

- TypeScript: `RealtimeAgent` + `RealtimeSession` speech-to-speech (`https://developers.openai.com/api/docs/guides/voice-agents`).
- Python: chained `VoicePipeline` (STT → LLM → TTS) in the same guide.
- Node.js: WebSocket session example with the `ws` library (`https://developers.openai.com/api/docs/guides/realtime-websocket`).
- Safety guardrails: "Developers can also easily add their own additional safety guardrails using the Agents SDK" (announcement URL above).
- The openai-agents-js / openai-agents-python voice guide URLs were not fetched ("not found").

---

# Topic 2 — Voice in Codex

## 1. CLI realtime voice timeline (changelog, primary)

Source: `https://github.com/openai/codex/releases` (changelog lives in GitHub releases, not CHANGELOG.md) and `https://developers.openai.com/codex/changelog/`.

- **0.105.0** (2026-02-25) — push-to-talk voice dictation in the TUI: "You can now dictate prompts by holding the spacebar to record and transcribe voice input directly in the TUI... to enable it set `features.voice_transcription = true` in your config."
- **0.107.0** (2026-03-02) — realtime voice sessions gain microphone/speaker **device pickers**; align ASR with 4o (#13030).
- **0.115.0** (2026-03-16) — **realtime transcription mode** for WebSocket sessions; v2 **handoff** via the `codex` tool; unified `[realtime]` session config.
- **0.118.0** (2026-03-31) — TUI voice transcription (push-to-talk) **removed** (#16114).
- **0.119.0** (2026-04-10) — realtime voice sessions **default to the v2 WebRTC path** with configurable transport; **voice selection**; native TUI media support.
- **0.122.0** (2026-04-20) — realtime V2 VAD silence delay. **0.123.0** (2026-04-23) — realtime handoffs with **transcript deltas**; realtime silence tool.
- **0.129.0** (2026-05-07) — realtime **sideband startup**.
- **0.140.0** (2026-06-15) — experimental `/realtime` TUI voice controls **removed** (#27801); per-session realtime model overrides (#24999); AVAS architecture override (#27720); roles in realtime append text (#27936).
- **0.141.0** (2026-06-18) — realtime clients can explicitly **append speech**, control how Codex responses enter the conversation, and omit startup context (#27917, #28405).
- **0.142.0** (2026-06-22) — "Always use **AVAS** for realtime WebRTC calls" (#28856); control automatic realtime handoff delivery (#27986); assistant realtime append text (#28836).
- **0.143.0** (2026-07-08) — flush trailing realtime transcript tail (#29918).
- **0.145.0** (2026-07-21) — **audio inputs and tool outputs** including common local audio formats; **streaming realtime V3 conversations** (#33261, #33856 stream realtime V3 Codex handoff output, #34080, #34385).
- **0.146.0** (2026-07-29) — session headers on realtime conversation starts (#34681); configurable realtime BEM channel prefixes (#34816).
- **0.147.0** (2026-08-07) — route **WebRTC sideband joins to the Realtime API** (#35830); realtime **delegation acknowledgement** control (#36413); extract audio-preparation utility crate (#36807); custom Codex instructions for realtime transitions (#36408).

## 2. Codex app (desktop): voice dictation

- Official features page: "**Voice dictation** — Use your voice to prompt Codex. Hold `Ctrl`+`M` while the composer is visible and start talking. Your voice will be transcribed. Edit the transcribed prompt or hit send to have Codex start work." (`https://developers.openai.com/codex/app/features`)
- Keyboard-shortcut reference lists **Dictation = `Ctrl`+`M`** under Thread actions (`https://developers.openai.com/codex/app/commands`).
- The identical pattern is documented for the ChatGPT desktop app: "In the ChatGPT desktop app, hold Ctrl+M while the composer is visible, then start talking. ChatGPT transcribes your speech into the composer so you can review and edit it before sending" (`https://learn.chatgpt.com/docs/prompting.md`).
- Known issues (primary, GitHub): Windows 11 `Ctrl+M` conflicts with OEM/global hotkeys, and the shortcut is not user-remappable (`https://github.com/openai/codex/issues/14549`, closed); dictation starts in both main and side-chat composers when a side chat is open (`https://github.com/openai/codex/issues/23398`, closed). A community thread documents the microphone icon intermittently missing and voice input being server-side gated (`https://community.openai.com/t/the-voice-transcription-button-has-disappeared-in-the-macos-codex-app/1379653` — secondary/community).
- Note the distinction: app dictation is **STT-into-composer** (transcribe → review → send), while the CLI's realtime voice sessions (Topic 2 §1/§3) are **speech-to-agent loops** with audio in and out.

## 3. Realtime architecture inside Codex

- **AVAS** — Codex's internal WebRTC audio stack. From the primary commit for #28856: "WebRTC realtime now means AVAS. If a caller explicitly asks to start WebRTC with realtime v2, Codex rejects that request because the AVAS WebRTC path only supports realtime v1." (`https://github.com/openai/codex/commit/...` via release notes; also `#34067` commit 312caf1: "WebRTC uses AVAS and supports legacy Bidi `"v1"` or Frameless Bidi `"v3"`; Realtime Voice `"v2"` is rejected for WebRTC.") The acronym is never expanded in these sources ("not found").
- **Media/control-plane separation** — audio flows directly between the client and OpenAI over WebRTC; the app-server only does signalling and sideband control (session monitoring, instruction updates, tool calls). The sideband attaches to `wss://api.openai.com/v1/realtime?call_id=...` (secondary walkthrough: `https://codex.danielvaughan.com/2026/04/10/webrtc-realtime-voice-codex-cli/`; primary changelog items 0.129.0/0.142.0/0.147.0 corroborate).
- **`thread/realtime/*` JSON-RPC surface** (primary, commit 312caf1): `thread/realtime/start` accepts `transport: {type: "websocket"}` or `{type: "webrtc", sdp}` (answer SDP returned as `thread/realtime/sdp`); `thread/realtime/appendAudio` (experimental); `thread/realtime/appendText` with required `role` of `user | developer | assistant`; `thread/realtime/appendSpeech` (text for the model to speak); `includeStartupContext: false` to skip Codex's startup context.
- **Realtime V3 (0.145.0)** — audio turns persist in conversation history (#34385), V3 sessions can be seeded with existing text items (#34067), tools and code mode can emit audio outputs (#34080), and realtime V3 Codex handoff output streams (#33856). PR #34385 also ensures audio persists across tool outputs (secondary: `https://codex.danielvaughan.com/2026/07/23/codex-cli-realtime-v3-audio-inputs-streaming-voice-architecture/`).
- **Voice/device selection** — the `/audio` command persists voice + mic + speaker to the top-level config; changing voice mid-session restarts only local audio (secondary walkthrough; primary: 0.107.0/0.119.0).

## 4. Handoff and delegation

- Realtime handoffs carry **transcript deltas** into the Codex conversation (0.123.0); delivery of automatic handoffs is controllable (0.142.0 #27986); clients can omit startup context (0.141.0); the realtime transition can carry custom Codex instructions (0.147.0 #36408) and the agent must **acknowledge delegation** (0.147.0 #36413). Voice thus enters the agent loop as a session that hands off to the full Codex agent — the "speech-to-code" pattern this report was asked about.

---

# Topic 3 — Voice in ChatGPT

## 1. GPT-Live (2026-07-08) and the Live vs Advanced split

- **`gpt-live`** is OpenAI's new-generation voice model, announced 2026-07-08: a "full-duplex architecture" that listens and speaks simultaneously, produces backchannels ("mhmm", "yeah"), and delegates to a frontier model for web search and advanced reasoning (`https://openai.com/index/introducing-gpt-live/`). Deployment safety system card published 2026-07-08, with a deployment update on 2026-07-31 extending audio watermarking (SynthID) (`https://deploymentsafety.openai.com/gpt-live`).
- **Voice FAQ** (`https://help.openai.com/en/articles/8400625-voice-mode`): the **Live** experience is "powered by GPT-Live-1 on paid plans and GPT-Live-1 mini on Free"; Live "can use web search and memory, show visual results through supported widgets, and work with text and images in the same chat"; it does **not** initially support video, screen sharing, connected apps, or plugins. **Advanced** is "the previous real-time Voice experience." Voice works within a chat (text continues alongside). **Dictation** (single recording → text, article `https://help.openai.com/en/articles/12168547`, not fetched) is a separate feature.

## 2. Dictation, desktop, and Codex-in-ChatGPT

- ChatGPT desktop app offers the same hold-`Ctrl`+`M` dictation into the composer (`https://learn.chatgpt.com/docs/prompting.md`).
- Codex itself is embedded in ChatGPT: "Codex in ChatGPT" (`https://openai.com/codex/`) and the mobile rollout — "Work with Codex from anywhere" (2026-05-14) previews Codex in the ChatGPT iOS/Android apps with remote SSH, hooks, and HIPAA-compliant local environments (`https://openai.com/index/work-with-codex-from-anywhere/`).
- GPT Voice mode coming to the ChatGPT desktop app (Work/Codex tasks) is covered only by secondary outlets dated 2026-07-23/24 (aggregation: `https://ground.news/...`); the official community announcement thread `https://community.openai.com/t/chatgpt-voice-is-now-in-the-desktop-app/1388031` was identified but not fetched ("not found" for a primary announcement).

---

# Topic 4 — Privacy, data handling, and safety

## 1. API data policy (Realtime API included)

`https://developers.openai.com/api/docs/guides/your-data`: API data is **not used for training** (as of Mar 1, 2023) unless the organization opts in; abuse monitoring retains prompts/responses for **up to 30 days**; eligible customers can get Zero Data Retention or Modified Abuse Monitoring with prior approval; controls are at API org/project level.

## 2. ChatGPT / ChatGPT Voice data handling

From the voice FAQ (`https://help.openai.com/en/articles/8400625-voice-mode`, data section): audio clips are stored for about **30 days** and deleted when the chat is deleted; Standard Mode transcribes the clip and deletes the audio; training is opt-in via "Include your audio recordings," and transcripts are used for training only if "Improve model for everyone" is enabled.

## 3. Realtime safety measures

- "We employ active classifiers over Realtime API sessions, meaning certain conversations can be halted if they are detected as violating our harmful content guidelines"; the Agents SDK adds developer-side guardrails; the Realtime API supports **EU Data Residency** and "enterprise privacy commitments" (announcement URL, May 7 2026).
- GPT-Live audio is watermarked with SynthID and the system card documents model-data and safety-evaluation sections (`https://deploymentsafety.openai.com/gpt-live`).

---

# Implications for Vellum

Concrete, citable hooks from the research above (no code; Vellum's local Moonshine STT + Kokoro TTS stack at `backend/agent/voice/`, reachable today only via the FastAPI endpoints in `backend/agent/api.py`):

1. **Cloud drop-in backends, named and priced** — `gpt-live-transcribe` / `gpt-realtime-whisper` at **$0.017/min** streaming STT and `gpt-audio-1.5` / `gpt-4o-mini-tts` for audio in/out are the exact alternatives to Moonshine/Kokoro when Vellum eventually offers a cloud tier; the model pages give Vellum precise "local vs cloud" numbers to quote.
2. **The "speak a command → agent acts" loop has a canonical shape now** — Realtime function tools (`function_call_output` returned by the client, `https://developers.openai.com/api/docs/guides/realtime-mcp`) plus Codex's sideband/approval pattern (Topic 2 §3) are the reference design for Vellum routing voice commands into its own tool loop; the `thread/realtime/appendText`-with-`role` JSON-RPC surface is a compact spec to mirror.
3. **The interruption contract is the VAD event set** — `input_audio_buffer.speech_started/stopped` with `server_vad` vs `semantic_vad` (`https://developers.openai.com/api/docs/guides/realtime-vad`) is OpenAI's documented barge-in model; GPT-Live's full-duplex is the direction of travel, and Vellum's barge-in UX should map to these events.
4. **Privacy positioning gets concrete numbers** — OpenAI: API data not used for training, abuse logs ≤ 30 days, ChatGPT Voice clips ≤ 30 days and deleted with chat, training opt-in (Topic 4). Vellum's in-process Moonshine/Kokoro is strictly stronger ("no audio leaves the machine"); these exact figures are the comparison table Vellum can publish.
5. **Dictation-into-composer is the cheapest voice feature** — Codex app and ChatGPT desktop both ship hold-`Ctrl`+`M` STT-into-composer with review-before-send (`https://developers.openai.com/codex/app/features`); Vellum already has a transcription endpoint, so this is a UI pattern, not an engine problem — and the known Windows `Ctrl+M` conflicts (#14549) argue for a remappable shortcut.
6. **Persistent audio turns are the direction of travel** — Codex Realtime V3 keeps audio in conversation history and seeds voice sessions with text context (#34067/#34385); a design note for Vellum: store audio artifacts alongside transcripts rather than discarding them.
7. **Transport guidance from OpenAI's own docs** — WebRTC with ephemeral tokens for browser/mobile, WebSocket for server pipelines (`https://developers.openai.com/api/docs/guides/realtime-websocket`), media plane separate from control plane (AVAS pattern, Topic 2 §3) — consistent with Vellum's current server-side SSE voice events and the natural path if a browser voice UI arrives.

---

## Not-found / unresolved items

- **AVAS expansion**: the acronym appears in Codex releases/commits (0.140.0 #27720, 0.142.0 #28856, #34067) but is never spelled out in any fetched primary source.
- **`gpt-realtime-mini` and `gpt-realtime-1.5` dedicated OpenAI pages**: not found on developers.openai.com; both only appear on Microsoft's Foundry page (secondary, labeled).
- **Official Realtime API latency figures**: not captured from any fetched page (the GA announcement fetch truncated before its performance claims; no official numbers found).
- **`gpt-realtime-2.1` pricing/limits page**: not found; guides reference the model but no dedicated pricing page was located.
- **ChatGPT desktop GPT Voice (Work/Codex) primary announcement**: not found; secondary coverage only (2026-07-23/24), and the official community thread (`.../chatgpt-voice-is-now-in-the-desktop-app/1388031`) was not fetched.
- **Codex mobile-app voice dictation**: not found in any primary source; the mobile "Codex from anywhere" post has no voice specifics.
- **openai-agents-js / openai-agents-python voice docs**: identified as likely guides but not fetched/verified.
- **help.openai.com dictation article (`/en/articles/12168547`)**: referenced by the FAQ but not fetched.
- **Codex app features page redirect**: a direct fetch of `https://developers.openai.com/codex/app/features` redirected to the learn.chatgpt.com docs portal; the voice-dictation content above was captured via the search index snapshot on 2026-08-05 — content may drift.
- **Eval claims (Big Bench Audio +15.2%, Audio MultiChallenge +13.8%)** are OpenAI's own published numbers from the May 7 announcement; no independent verification.
- **GPT-Live data-retention specifics** beyond the voice FAQ: not found (the system card's data sections were not fully fetched).
