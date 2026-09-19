# Hermes Voice & TTS and the Sarvam AI MCP Server

Research report — 2026-08-05
Primary sources: `https://github.com/NousResearch/hermes-agent` (main branch, commit `1be70d6` 2026-08-05; docs mirrored in the repo under `website/docs/...`), `https://github.com/sarvamai/sarvam-mcp` (main branch, commit `14305aa` 2026-07-06, v0.2.8), the official Sarvam docs at `https://docs.sarvam.ai` (pages fetched 2026-08-05, cited by URL path), and `https://www.sarvam.ai/privacy-policy`. File/line citations were extracted from the cloned repos on `main`; anything not found is reported as "not found" inline.

---

# Topic 1 — Hermes Voice & TTS

## 1. Where the Hermes repo/docs document voice

Voice is documented on four dedicated pages plus scattered references:

- `website/docs/guides/use-voice-mode-with-hermes.md` — practical setup guide (CLI mic loop, Telegram/Discord voice replies, Discord voice channels; 460 lines)
- `website/docs/user-guide/features/voice-mode.md` — the feature reference ("Voice Mode", 563 lines): CLI push-to-talk, gateway voice replies, Discord VCs, config reference, STT/TTS provider comparison tables
- `website/docs/user-guide/features/tts.md` — "Voice & TTS": all TTS/STT providers, command providers, Python plugin providers, input length caps
- `website/docs/user-guide/features/wake-word.md` — "Wake Word ('Hey Hermes')", on-device hotword detection
- Supporting mentions: `website/docs/reference/slash-commands.md` (`/voice`, `/wake`), `website/docs/reference/environment-variables.md:108-110,161-167` (voice env vars), `website/docs/user-guide/messaging/telegram.md` / `discord.md` / `whatsapp.md` / `slack.md` / `signal.md` (voice-message transcription per platform), `website/docs/user-guide/docker.md` (Linux desktop audio bridge), `website/docs/getting-started/nix-setup.md` (faster-whisper).

Implementation lives in: `tools/voice_mode.py`, `tools/tts_tool.py`, `tools/tts_streaming.py`, `tools/tts_text_normalize.py`, `tools/transcription_tools.py`, `tools/wake_word.py`, `hermes_cli/voice.py`, `agent/tts_provider.py` / `agent/transcription_provider.py` (plugin ABCs), `agent/tts_registry.py` / `agent/transcription_registry.py`.

## 2. STT engines, selection, and configuration

**Built-in provider names** — `BUILTIN_STT_PROVIDERS` at `tools/transcription_tools.py:341-350`: `local`, `local_command`, `groq`, `openai`, `mistral`, `xai`, `elevenlabs`, `deepinfra`.

**Selection** — `stt.provider` in `config.yaml`; default is `"local"` (`hermes_cli/config_defaults.py:1504-1510`). Provider fallback order when the configured one is unavailable: `local` → `groq` → `openai` (docs `website/docs/user-guide/features/voice-mode.md:497`; detailed fallback rules in `website/docs/user-guide/features/tts.md:526-533`).

**Engines and models:**
- `local` — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CPU/GPU), model sizes `tiny` ~75 MB, `base` ~150 MB (default), `small` ~500 MB, `medium` ~1.5 GB, `large-v3` ~3 GB (`website/docs/user-guide/features/tts.md:480-489`). "If `faster-whisper` is installed, voice mode works with **zero API keys** for STT" (`website/docs/user-guide/features/voice-mode.md:107`).
- `groq` — Whisper via Groq: `whisper-large-v3-turbo`, `whisper-large-v3` (`website/docs/user-guide/features/voice-mode.md:468,489-490`).
- `openai` — `whisper-1`, `gpt-4o-mini-transcribe`, `gpt-4o-transcribe`, `gpt-transcribe` (`website/docs/user-guide/features/tts.md:470`).
- `mistral` — `voxtral-mini-latest`, `voxtral-mini-2602`; diarization + word timestamps (`website/docs/user-guide/features/tts.md:471-472,494`).
- `xai` — `grok-stt` posted to `https://api.x.ai/v1/stt` (`website/docs/user-guide/features/tts.md:496`).
- `local_command` — `HERMES_LOCAL_STT_COMMAND` argv-tokenized escape hatch with `{input_path}`, `{output_dir}`, `{language}`, `{model}` placeholders, executed without a shell (`website/docs/user-guide/features/tts.md:498,517-524`).
- Custom shell command providers: `stt.providers.<name>: type: command` (e.g. `parakeet-asr`, `whisper-cli`, `sensevoice-cli`; `website/docs/user-guide/features/tts.md:535-609`), formats `txt`/`json`/`srt`/`vtt`.
- Python plugin providers via `ctx.register_transcription_provider()` — `TranscriptionProvider` ABC at `agent/transcription_provider.py:61` (docs `website/docs/user-guide/features/tts.md:611-718`).

**Env vars** — `GROQ_API_KEY`, `VOICE_TOOLS_OPENAI_KEY` (also falls back to `OPENAI_API_KEY`), `STT_GROQ_MODEL`, `STT_OPENAI_MODEL`, `STT_OPENAI_BASE_URL`, `GROQ_BASE_URL`, `HERMES_LOCAL_STT_COMMAND`, `HERMES_LOCAL_STT_LANGUAGE` (`website/docs/user-guide/features/voice-mode.md:462-471`; `website/docs/reference/environment-variables.md:109-110,164-167`).

**Streaming vs file upload** — STT is **file-based, not streaming**. The dispatcher entry is `transcribe_audio(file_path, model)` at `tools/transcription_tools.py:2524`, which validates the source (refuses credential/secret stores before anything else, `:2526-2533`), preprocesses/decodes, and dispatches per provider. `transcribe_audio` is **not registered as a model tool** (no `registry.register` in `tools/transcription_tools.py`; "not found") — it is called by the gateway/voice pipelines. The only model-facing audio tool is TTS (see §4). Optional passthrough: `stt.enabled: false` skips auto-transcription but "the gateway still caches the audio file and passes its path to the agent as part of the inbound message, useful for custom pipelines (diarization, alignment, archival, etc.)" (`website/docs/user-guide/features/voice-mode.md:421-426`).

## 3. TTS engines, voice selection, output formats

**Built-in provider names** — `BUILTIN_TTS_PROVIDERS` at `tools/tts_tool.py:611-623`: `edge`, `elevenlabs`, `openai`, `minimax`, `xai`, `mistral`, `gemini`, `neutts`, `kittentts`, `piper`, `deepinfra`. **No Kokoro built-in** — Kokoro is supported indirectly: `tts.openai.language` is forwarded as a `lang_code` request parameter intended "for OpenAI-compatible TTS servers that support `lang_code` — for example [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI)" (`website/docs/user-guide/features/tts.md:147`), and an `mlx-kokoro` CLI can be wired as a command provider (`website/docs/user-guide/features/tts.md:276-281`). Also documented as a custom-command example: VoxCPM, XTTS CLI (`website/docs/user-guide/features/tts.md:261`).

**Default** — `tts.provider: "edge"` with `voice: "en-US-AriaNeural"` (`hermes_cli/config_defaults.py:1428-1432`); Edge TTS = free, no key, "322 voices, 74 languages" (`website/docs/user-guide/features/tts.md:50`).

**Voice selection (config.yaml, exact keys)** — from `website/docs/user-guide/features/tts.md:44-106` and `hermes_cli/config_defaults.py:1425-1499`:
- `tts.edge.voice` (e.g. `en-US-AriaNeural`)
- `tts.elevenlabs.voice_id` (default `pNInz6obpgDQGcFmaJgB` = "Adam") + `tts.elevenlabs.model_id` (default `eleven_multilingual_v2`)
- `tts.openai.model` (`gpt-4o-mini-tts`) + `tts.openai.voice` (`alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`; newer voices `ash`, `ballad`, `cedar`, `coral`, `marin`, `sage`, `verse` per `config_defaults.py:1440-1442`) + optional `base_url` override for OpenAI-compatible endpoints
- `tts.minimax.model` (`speech-02-hd`) + `voice_id` + `region: global|cn`
- `tts.mistral.model` (`voxtral-mini-tts-2603`) + `voice_id`
- `tts.gemini.model` (`gemini-2.5-flash-preview-tts` / `gemini-3.1-flash-tts-preview`) + `voice` (e.g. `Kore`; "30 prebuilt voices: Zephyr, Puck, Kore, Enceladus, Gacrux, etc.")
- `tts.xai.voice_id` (`eve` default or a custom cloned-voice id) + `language`, `speed`, `sample_rate`, `bit_rate`, `optimize_streaming_latency`
- `tts.neutts.model` (`neuphonic/neutts-air-q4-gguf`, local GGUF) + `ref_audio`/`ref_text`/`device`
- `tts.kittentts.model` (`KittenML/kitten-tts-nano-0.8-int8`) + `voice` (Jasper, Bella, Luna, Bruno, Rosie, Hugo, Kiki, Leo)
- `tts.piper.voice` (`en_US-lessac-medium`, or absolute `.onnx` path; 44 languages, models auto-download to `~/.hermes/cache/piper-voices/`)
- `tts.deepinfra.model`/`voice`
- Global `tts.speed` multiplier with per-provider override (`website/docs/user-guide/features/tts.md:115`)

**Voice is user-configured, not model-selected** — the tool schema states "Voice and provider are user-configured (built-in providers like edge/openai or custom command providers under tts.providers.<name>), not model-selected" (`tools/tts_tool.py:3912`); the model can override the provider per call via an optional `provider` arg (`tools/tts_tool.py:3937-3945`) and pass voice-design `instructions` to OpenAI-compatible backends (`:3928-3935`).

**Output formats** — CLI saves MP3 to `~/.hermes/audio_cache/`; Telegram delivers an Opus `.ogg` voice bubble; Discord Opus/OGG voice bubble (file-attachment fallback); WhatsApp MP3 (`website/docs/user-guide/features/tts.md:33-40`). Opus-required platforms: `OPUS_VOICE_PLATFORMS = {telegram, matrix, feishu, whatsapp, signal}` (`tools/tts_tool.py:636-642`). ffmpeg converts MP3/WAV/PCM to Opus for voice bubbles (`website/docs/user-guide/features/tts.md:187-215`). Per-provider input length caps (Edge 5000, OpenAI 4096, xAI 15000, MiniMax 10000, Mistral 4000, Gemini 32000, ElevenLabs model-aware 5k–40k, NeuTTS/KittenTTS 2000, Piper 5000; `website/docs/user-guide/features/tts.md:150-176`).

## 4. How voice is wired into the agent loop

- **TTS is a model tool; STT is not.** The single model-facing voice tool is `text_to_speech` — schema at `tools/tts_tool.py:3910-3950` (`name: "text_to_speech"`, params `text` (required), `output_path`, `speed`, `instructions`, `provider`; returns a `MEDIA:` path the platform delivers as native audio), registered at `tools/tts_tool.py:3952-3959` under toolset `"tts"` (`toolsets.py:224-228`). It is in `_HERMES_CORE_TOOLS` (`toolsets.py:57`), i.e. shipped on every platform's base toolset by default. There is no `transcribe`/STT model tool ("not found").
- **Inbound audio → text.** Voice messages on Telegram/Discord/WhatsApp/Slack/Signal are transcribed by the platform pipeline and injected as text; the agent "sees the transcript as normal text" (`website/docs/user-guide/features/tts.md:443-445`). A `[[audio_as_voice]]` delivery directive on TTS output makes the platform render the attached audio as a voice bubble (`gateway/run.py:1529`; extracted at `gateway/platforms/base.py:4459-4487`).
- **CLI/TUI voice mode.** `/voice on` → push-to-talk on `Ctrl+B` (`voice.record_key`), 880 Hz start beep, silence VAD (RMS threshold 200, 3.0 s silence, two-stage detection), auto-restart loop, "stop" phrase ends the chat (`website/docs/user-guide/features/voice-mode.md:116-166`; constants `SILENCE_RMS_THRESHOLD = 200` / `SILENCE_DURATION_SECONDS = 3.0` at `tools/voice_mode.py:432-433`). Recording/transcription is a Python pipeline (`tools/voice_mode.py`); the TUI/desktop backend uses JSON-RPC handlers `voice.record`, `voice.toggle`, `voice.tts` (`hermes_cli/voice.py:1-16`). Streaming TTS: replies are spoken sentence-by-sentence via `tools/tts_streaming.py` (`StreamingTTSProvider` ABC at `:131`, `SentenceChunker` at `:89`, provider resolution `resolve_streaming_provider` at `:182`; docs `voice-mode.md:168-176`). Barge-in with quiet-room noise-floor calibration, `voice.barge_in_threshold_multiplier` (3.0), `voice.barge_in_grace_seconds` (0.5) (`voice-mode.md:178-189`). Whisper hallucination filter (26 phrases + regex) (`voice-mode.md:191-193`).
- **Messaging gateway.** `/voice on|off|tts|join|leave|status` handled at `gateway/slash_commands.py:2914-2954`; modes `off` / `voice_only` / `all`, persisted per chat in `~/.hermes/gateway_voice_mode.json` (`_VOICE_MODE_PATH` at `gateway/run.py:6231`). Dispatch from `gateway/run.py:15272-15273`. Telegram/Discord voice bubbles via ffmpeg conversion (`voice-mode.md:256-262`).
- **Discord voice channels (full-duplex).** `/voice join` → `_handle_voice_channel_join` (`gateway/run.py:18725`); per-user audio streams → VAD (0.5 s speech / 1.5 s silence) → Whisper STT → full agent pipeline → TTS reply back into the VC (`gateway/run.py:18856`; docs `voice-mode.md:372-392`). Echo prevention pauses the listener during playback (`voice-mode.md:392`); access control via `DISCORD_ALLOWED_USERS` (`voice-mode.md:394-400`); transcriptions posted to the text channel (`voice-mode.md:384-388`).
- **Desktop/web audio API (FastAPI).** In `hermes_cli/web_server.py`: `POST /api/audio/transcribe` (`:4273`, accepts base64 data-URL audio, returns `{ok, transcript, provider}`), `GET /api/audio/elevenlabs/voices` (`:4396`, for the `voice_id` dropdown), `POST /api/audio/speak` (`:4480`, text → base64 audio data URL via the configured `tts.*` chain), and `WS /api/audio/speak-stream` (`:4584`) — a per-reply speech WebSocket: client sends `{"text": "..."}` deltas, `{"done": true}`, `{"stop": true}` (barge-in); server sends `{"type": "start", "sample_rate", "channels": 1}`, raw int16 PCM frames, `{"type": "end"}`, or `{"type": "fallback"}` when the provider has no chunked API (protocol docstring `:4595-4602`). "Speech overlaps generation... exactly like the token→sentence→TTS pipelining the realtime-voice literature converges on" (`:4591-4593`).
- **Wake word.** `tools/wake_word.py` — three on-device engines: `openwakeword` (default, bundled "hey hermes" model), `sherpa` (open-vocabulary phrase spotting), `porcupine` (Picovoice, `PORCUPINE_ACCESS_KEY`) (`tools/wake_word.py:9-21`); deps pinned in `tools/lazy_deps.py:165-184` (`openwakeword==0.6.0`, `sherpa-onnx==1.13.4`, `pvporcupine==4.0.3`). 16 kHz mono int16 capture (`SAMPLE_RATE = 16000`, `tools/wake_word.py:44-45`). Wired into the CLI at `cli.py:12841-13022` (`_maybe_start_wake_word`, `_on_wake_word`); surfaces CLI/TUI/desktop only, not the messaging gateway (`website/docs/user-guide/features/wake-word.md:297-299`). On wake it hands "a plain string to the caller, exactly like a voice transcript" (`tools/wake_word.py:28-29`).
- **The gateway HTTP API does NOT expose voice.** The api_server platform advertises `"audio_api": False, "realtime_voice": False` in its `/api/server/info` features (`gateway/platforms/api_server.py:3063-3064`). Voice is reachable only through the CLI/TUI/desktop surfaces and platform adapters, not through Hermes' OpenAI-compatible REST surface.

## 5. Does Hermes use an MCP server for voice? Sarvam references?

- **No voice MCP server in the Hermes MCP catalog.** The `optional-mcps/` directory ships only `blender`, `comfy-cloud`, `figma`, `linear`, `n8n`, `unreal-engine` ("not found" for any voice/STT/TTS MCP server). Voice is implemented as core tool + platform adapters instead; notably, the repo's contribution rubric would prefer an MCP server for non-core capability ("MCP server (in the catalog)... over growing the core toolset", `AGENTS.md`), yet TTS was placed in `_HERMES_CORE_TOOLS` (`toolsets.py:57`).
- **Sarvam AI: "not found" anywhere in the Hermes repo.** A case-insensitive search for `sarvam` across the entire `hermes-agent` tree (docs, tools, gateway, plugins, optional-mcps, mcp catalog) returns zero matches.

## 6. Privacy / scrubbing stance on audio

- **Wake word is explicitly local:** "Detection runs **entirely on-device**. The always-on listener only watches for the wake phrase; no audio leaves your machine until you actually speak a command to the agent" (`website/docs/user-guide/features/wake-word.md:16-18`); "Hotword detection is local" (`:302`).
- **Local STT is positioned as the privacy default:** "`local` → best default for privacy and zero-cost use" (`website/docs/guides/use-voice-mode-with-hermes.md:142`); "Local transcription works out of the box when `faster-whisper` is installed" (`website/docs/user-guide/features/tts.md:453-455`).
- **Subprocess scrubbing:** command-type TTS/STT providers "run with Hermes secrets scrubbed from the child environment — gateway bot tokens, LLM provider API keys, and internal relay credentials are removed" (`website/docs/user-guide/features/tts.md:290`).
- **Filesystem guards:** `transcribe_audio` refuses to feed credential/secret stores to an STT provider (`tools/transcription_tools.py:2526-2533`).
- No audio-retention policy, audio redaction, or recorded-audio deletion statement was found in the voice docs or in `agent/redact.py` (no audio references; "not found").

## 7. Concrete config keys, endpoints, model names (as found)

- Config: `voice.record_key`, `voice.max_recording_seconds`, `voice.auto_tts`, `voice.beep_enabled`, `voice.silence_threshold`, `voice.silence_duration`, `voice.stop_phrases`, `voice.barge_in`, `voice.barge_in_threshold_multiplier`, `voice.barge_in_grace_seconds`; `stt.provider|enabled|language|local.model|groq|openai|mistral|xai`; `tts.provider|speed|edge|elevenlabs|openai|minimax|mistral|gemini|xai|neutts|kittentts|piper|deepinfra|providers.<name>`; `wake_word.enabled|surface|input_device|provider|phrase|sensitivity|confirmation_frames|start_new_session|openwakeword|porcupine` (references in §2-§4).
- Env: `GROQ_API_KEY`, `VOICE_TOOLS_OPENAI_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `MINIMAX_API_KEY`/`MINIMAX_CN_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `DEEPINFRA_API_KEY`, `PORCUPINE_ACCESS_KEY`, `STT_GROQ_MODEL`, `STT_OPENAI_MODEL`, `STT_OPENAI_BASE_URL`, `GROQ_BASE_URL`, `HERMES_LOCAL_STT_COMMAND`, `HERMES_LOCAL_STT_LANGUAGE`, `HERMES_VOICE_DEBUG`, `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`, `DISCORD_REQUIRE_MENTION`, `DISCORD_FREE_RESPONSE_CHANNELS` (`website/docs/user-guide/features/voice-mode.md:461-480,187`).
- HTTP endpoints: `POST /api/audio/transcribe`, `GET /api/audio/elevenlabs/voices`, `POST /api/audio/speak`, `WS /api/audio/speak-stream` (`hermes_cli/web_server.py:4273,4396,4480,4584`).
- Model names: STT `whisper-1`, `gpt-4o-transcribe`, `gpt-transcribe`, `whisper-large-v3-turbo`, `grok-stt`, `voxtral-mini-latest`, `saaras:*` (not applicable); TTS `gpt-4o-mini-tts`, `eleven_multilingual_v2`, `speech-02-hd`, `voxtral-mini-tts-2603`, `gemini-2.5-flash-preview-tts`, `neuphonic/neutts-air-q4-gguf`, `KittenML/kitten-tts-nano-0.8-int8`, `en_US-lessac-medium`.

---

# Topic 2 — Sarvam AI MCP server

## 1. Canonical source and first-party status

- Canonical repo: `https://github.com/sarvamai/sarvam-mcp` — self-described "Official Sarvam MCP server" (`README.md:3`); authors = Sarvam AI, MIT license, `requires-python >=3.11`, version `0.2.8` (Development Status 4 - Beta) (`pyproject.toml:6-13,15-26`). Repo URL, docs URL `https://docs.sarvam.ai`, and homepage `https://mcp.sarvam.ai` are the project's own declared links (`pyproject.toml:48-53`). PyPI package `sarvam-mcp`.
- Docs site: `https://docs.sarvam.ai` (Sarvam API docs; the index even exposes an MCP server for AI clients at `https://docs.sarvam.ai/_mcp/server`, per `https://docs.sarvam.ai/llms.txt`).
- Official/first-party: confirmed — PyPI metadata and `pyproject.toml:13` (authors = "Sarvam AI", email support@sarvam.ai); README quickstart points to `dashboard.sarvam.ai/key-management` (`README.md:11`).

## 2. Tools exposed

Full tool table (default model in parentheses) from `README.md:82-97`, with implementations in `src/sarvam_mcp/tools/`:

| Tool | Function | Default model |
|---|---|---|
| `sarvam_tools_stt_transcribe` | Audio → transcript, 5 modes | `saaras:v3` |
| `sarvam_tools_stt_translate` | Legacy speech→English translate (DEPRECATED) | `saaras:v2.5` |
| `sarvam_tools_stt_batch_submit` | Long-file batch transcription (create→upload→start→poll) | `saaras:v3` |
| `sarvam_tools_stt_batch_status` | Poll a batch job | — |
| `sarvam_tools_tts_speak` | Text → audio file (WAV) | `bulbul:v3` |
| `sarvam_tools_tts_stream` | Text → streamed audio via WebSocket | `bulbul:v3` |
| `sarvam_tools_translate` | Cross-language text translation | `mayura:v1` |
| `sarvam_tools_transliterate` | Script conversion | — |
| `sarvam_tools_identify_language` | Language + script detection (`/text-lid`) | — |
| `sarvam_tools_text_analytics` | Typed Q&A over text (`/text-analytics`) | — |
| `sarvam_tools_llm_complete` | Chat completions | `sarvam-30b` |
| `sarvam_tools_vision_extract` / `_job_status` | Document Intelligence | Sarvam Vision |
| `sarvam_tools_pronunciation_{list,get,create,delete}` | Pronunciation dictionaries | — |
| `sarvam_tools_set_api_key` | Auth/rotation, saves to `~/.sarvam/credentials` | — |

**STT tool I/O** (`src/sarvam_mcp/tools/stt.py:36-128`): inputs `audio_path` | `audio_base64` | `audio_url` (exactly one), `filename`, `language_code` (default `"unknown"` = auto-detect; `hi-IN`, `ta-IN`, ...), `mode` (`transcribe` default | `translate` → English | `verbatim` | `translit` → Roman | `codemix`), `with_timestamps`, `model` (`saaras:v3`), `input_audio_codec` (PCM only: `pcm_s16le`, `pcm_l16`, `pcm_raw`). Returns `transcript`, `language_code`, `language_probability`, `diarized_transcript`, `timestamps` + an `observability` block (latency, quota, request-id). Endpoint `POST /speech-to-text` (`stt.py:16`).

**TTS tool I/O** (`src/sarvam_mcp/tools/tts.py:38-100`): inputs `text` (~500 chars/call), `target_language_code`, `speaker` (default `priya`), `speech_sample_rate` (default 24000; 8000–48000), `pitch` (−1..1), `pace` (0.3–3.0), `loudness`, `enable_preprocessing`, `model` (`bulbul:v3`). Returns `file_path` (under `SARVAM_MCP_BASE_PATH`, default `~/Desktop`), `resource_uri`, `base64_data`, `mime_type`, `size_bytes`. Endpoint `POST /text-to-speech` returning `{"audios": ["<base64-wav>"], "request_id"}` (`tts.py:80`).

**Composite workflow tools** (AGENTS.md; `src/sarvam_mcp/workflows/`): `sarvam_tools_voice` (audio → STT → LLM reply → TTS audio out; `workflows/voice.py:30-120`), `sarvam_tools_dub` (STT → Translate → TTS dubbing), `sarvam_tools_localize` (i18n string-table translation), `sarvam_tools_recall` (audio → STT → LLM summary). A second namespace `sarvam_code_*` provides build-time docs/snippets and "do NOT call the Sarvam API at runtime" (AGENTS.md).

**Language coverage** — STT/Translate: 23 Indic languages + English (`_common.py:97-123`, `en-IN`, `hi-IN`, `bn-IN`, `ta-IN`, `te-IN`, `gu-IN`, `kn-IN`, `ml-IN`, `mr-IN`, `pa-IN`, `od-IN`, `as-IN`, `ur-IN`, `ne-IN`, `kok-IN`, `ks-IN`, `sd-IN`, `sa-IN`, `sat-IN`, `mni-IN`, `brx-IN`, `mai-IN`, `doi-IN`); TTS subset: 11 (`_common.py:126-138`). Official docs: "22 Indian languages (Saaras v3)" for STT (`https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/overview`).

## 3. Authentication / setup / free tier

- **API key:** set `SARVAM_API_KEY` in the MCP client config `env`, or store in `~/.sarvam/credentials` as `api_key = sk_...`; env var wins (`src/sarvam_mcp/config.py:26-49`; README.md:58-66). Key obtained at `https://dashboard.sarvam.ai/key-management` (README.md:11). The server sends it as the **`api-subscription-key`** header on all outbound calls (`src/sarvam_mcp/auth/api_key.py:9,17-18`).
- **Install:** `uvx sarvam-mcp` (no install) or `pip install sarvam-mcp`; console script `sarvam-mcp` (`pyproject.toml:45-46`; README.md:68-76). Client config JSON shapes for Cursor / Claude Desktop / Claude Code / Windsurf / Zed in README.md:48-56; `sarvam-mcp --print [--api-key=...]` emits the JSON (`server.py:176-214`).
- **Other env vars:** `SARVAM_API_BASE_URL` (default `https://api.sarvam.ai`), `SARVAM_MCP_BASE_PATH` (default `~/Desktop`), `SARVAM_AUDIO_OUTPUT_MODE` (`files` | `resources` | `both`) (`config.py:12-14,31-34`; README.md:99-106).
- **Free tier:** "Sarvam offers **₹100 worth of free credits** for every user on signup... Credits are universal and never expire" (`https://docs.sarvam.ai/api/getting-started/ratelimits`). Rate limits are per-account (shared across keys), token-bucket replenishment, per-API granularity. Examples: STT REST Starter 60 req/min, Pro 100, Business 4,000; STT WebSocket streaming Starter 20 concurrent; TTS REST Starter 60 req/min (30 for `bulbul:v3`); TTS WebSocket Starter 60 concurrent (30 for `bulbul:v3`). 429 body `{"error": {"message": "Rate limit exceeded", "code": "rate_limit_exceeded_error"}}`; WebSocket reject close code `1003`; plans Starter (pay-as-you-go) / Pro ₹10,000 / Business ₹50,000 (same page). The repo retries only `{500, 502, 503, 504}`; 429 has its own dedicated handling (`src/sarvam_mcp/http/retry.py:14-15`), and responses carry `quota_remaining` (`src/sarvam_mcp/observability.py:22,55-56`).

## 4. Model IDs, voice IDs, streaming

- **STT models:** `saaras:v3` (recommended; 5 output modes), `saaras:v3-realtime` (WebSocket realtime with partial transcripts), legacy `saaras:v2.5` (`tools/stt.py:25,32`; docs: `https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/overview`). Limits: REST ≤ 30 s/request; Batch ≤ 2 h/file, ≤ 20 files/job, ≤ 20 speakers diarization; streaming WebSocket = WAV + raw PCM only (`wav`, `pcm_s16le`, `pcm_l16`, `pcm_raw`), 16 kHz default / 8 kHz (docs, same page).
- **TTS model/voices:** `bulbul:v3` (also `bulbul:v2` per the streaming docs). Speaker roster of 38 names in `_common.py:146-152` (`aditya`, `ritu`, `ashutosh`, `priya`, `neha`, `rahul`, `pooja`, `rohan`, `simran`, `kavya`, `amit`, `dev`, `ishita`, `shreya`, `ratan`, `varun`, `manan`, `sumit`, `roopa`, `kabir`, `aayan`, `shubh`, `advait`, `anand`, `tanya`, `tarun`, `sunny`, `mani`, `gokul`, `vijay`, `shruti`, `suhani`, `mohit`, `kavitha`, `rehan`, `soham`, `rupali`, `niharika`); official docs describe "Bulbul V3... 30+ voices" (`https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/overview`).
- **Streaming:** yes, both directions. TTS streaming via WebSocket `POST /text-to-speech/stream` (HTTP stream, ≤ 3500 chars, binary audio out) or WebSocket `/text-to-speech/ws` (≤ 2500 chars/message, base64 chunks, connection reuse) (`https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api`); the MCP `sarvam_tools_tts_stream` opens the WebSocket and falls back to REST if streaming is unavailable (`tools/tts.py:102-179`, WS path `TTS_STREAM_PATH = "/text-to-speech/stream"` at `tts.py:17`). Live transcription: the Realtime STT API (`saaras:v3-realtime`) provides "true partial transcripts and mid-call reconfiguration" (docs, STT overview); the MCP server itself only exposes REST + batch STT (no realtime tool; "not found").
- **Output codecs (TTS):** `mp3`, `wav`, `aac`, `opus`, `flac`, `linear16`, `mulaw`, `alaw`; sample rates 8000/16000/22050/24000 (REST also 32000/44100/48000); REST char cap 2500, HTTP stream 3500, WS 2500 (recommended <500 for lowest latency) (`https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/overview`).

## 5. Transport / framework compatibility

- **stdio MCP server** via FastMCP: `FastMCP("sarvam-mcp", ...)` then `server.run()` (default stdio transport) at `server.py:103,213-214`; launched by MCP clients as `uvx sarvam-mcp` / `sarvam-mcp` / `python -m sarvam_mcp` (README.md:17-46; `server.py:152-171`). It is a local process-server, not HTTP/SSE.
- **Remote MCP URL also exists:** Sarvam's docs index tells AI clients to "connect to the MCP server at `https://docs.sarvam.ai/_mcp/server`" (`https://docs.sarvam.ai/llms.txt`) — a first-party hosted variant.
- **LangChain/LangGraph:** "not found" — the sarvam-mcp repo contains no LangChain/LangGraph/llamaindex references. Compatibility is generic MCP: "any MCP-aware client (Claude Desktop, Claude Code, Cursor, Windsurf, Zed)" (README.md:3). Dependencies: `fastmcp>=0.4.0`, `httpx>=0.27.0`, `websockets>=12.0`, `pydantic>=2.6`, `anyio>=4.3`, `packaging>=23.0` (`pyproject.toml:27-34`). (LangGraph is used by third-party demo projects against Sarvam, e.g. Apurv428/setu-agent via `langchain-mcp-adapters` — secondary, not cited as canonical.)

## 6. Sarvam vs local Moonshine/Kokoro — what official sources say about cloud & data

Sarvam is a **cloud API** (base URL `https://api.sarvam.ai`, `config.py:12`); all audio/text is uploaded for processing. Official privacy stance (`https://www.sarvam.ai/privacy-policy`, updated 2026-07-29):

- **Model training default:** "We use Your content (including inputs, uploads, prompts, or generated outputs) to train, fine-tune, and/or improve our AI models **unless you explicitly opt-out** through your account settings" (privacy-policy, "AI Model Training & Your Data: Default Policy: Opt-In").
- **Content retention:** "Your Content (Inputs/Outputs): User-configurable (default: **30 days after last access**)" (privacy-policy, "Data Retention & Deletion"); "Voice Samples & Models: Until consent withdrawal + 30 days".
- **Compliance:** ISO 27001:2022, SOC 2 Type II, "Significant Data Fiduciary" under India's DPDP Act 2023; data not sold (privacy-policy, "Data Fiduciary Information", "Collection & Processing").
- **Cross-border transfers:** personal data "may be transferred to and processed in countries outside India, including: United States: Cloud infrastructure (AWS, GCP, Azure)... European Union: Certain model providers" with SCCs; voice biometric data stored in India (privacy-policy, "Cross-Border Data Transfers").
- **Hermes contrast (local stack):** Hermes' own docs position local STT as "best default for privacy" (`website/docs/guides/use-voice-mode-with-hermes.md:142`) and local hotword detection as "no audio leaves your machine" (`website/docs/user-guide/features/wake-word.md:16-18`) — i.e., Sarvam MCP is a privacy-equivalence trade (cloud audio, training-opt-out, 30-day retention) versus Vellum's in-process Moonshine/Kokoro. Note Hermes does not currently expose any cloud STT with Sarvam-style default-training terms in its provider list, so this comparison has no in-repo precedent.

## 7. Official examples worth citing

- **Repo quickstart:** MCP config JSON for 5 clients (README.md:17-56); `uvx`/pip install (README.md:68-76); tool table (README.md:82-97); env-var table (README.md:99-106).
- **Official docs code samples** (Python/JS/curl using the `sarvamai` SDK): streaming TTS to file or `ffplay` via `POST /text-to-speech/stream` (`https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api`); STT REST/Batch/Realtime guides (`https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/overview`); rate-limit handling incl. exponential backoff for 429/503 (`https://docs.sarvam.ai/api/getting-started/ratelimits`, `.../errors-troubleshooting`).
- **In-repo embedded snippets:** `src/sarvam_mcp/code/_snippets.py` / `_data.py` (hard-coded endpoint shapes, speaker/model tables, `_data.py:74-86,311` per-minute billing notes) — the `sarvam_code_*` tools serve these to agents at runtime.
- **Composite pattern:** `sarvam_tools_voice` in `workflows/voice.py:30-120` is a canonical "audio in → STT → LLM → TTS out" loop in ~90 lines that any agent (incl. Vellum) could mirror locally.

---

# Implications for Vellum

Concrete, citable hooks from the research above (no code; Vellum's local Moonshine/Kokoro stack at `backend/agent/voice/`, currently only reachable via `backend/agent/api.py` STT/TTS endpoints and SSE audio events — `backend/agent/api.py:3768-3774,4078-4094`):

1. **Copy Hermes' provider-abstraction config shape** — `stt.provider` / `tts.provider` with `BUILTIN_*_PROVIDERS` frozensets and an auto-detect fallback chain (`tools/transcription_tools.py:341-350`, `tools/tts_tool.py:611-623`; fallback order `voice-mode.md:497`). Vellum can keep Moonshine/Kokoro as `local` defaults and add `openai`/`groq`/Sarvam-style cloud providers as drop-in later, exactly like Hermes' `local > groq > openai` ladder.
2. **TTS as the only model-facing voice tool, STT at the transport layer** — Hermes ships `text_to_speech` in `_HERMES_CORE_TOOLS` returning a `MEDIA:` path (`toolsets.py:57`, `tools/tts_tool.py:3910-3950`) and deliberately keeps STT out of the model schema, transcribing at the inbound boundary and injecting the transcript as text (`website/docs/user-guide/features/tts.md:443-445`). Vellum's FastAPI voice layer already matches this split (`backend/agent/api.py:107-108,4078-4094`) — keep it.
3. **Adopt the desktop WebSocket protocol for streaming TTS** — `WS /api/audio/speak-stream`: client `{"text"}` deltas + `{"done"}` + `{"stop"}` (barge-in), server `{"type":"start", sample_rate, channels}` + raw int16 PCM + `{"type":"end"}` / `{"type":"fallback"}` (`hermes_cli/web_server.py:4584-4602`). Sentence-chunked streaming via `SentenceChunker` with min-20-char sentences, markdown/emoji/`<think>` stripping (`tools/tts_streaming.py:89`, `voice-mode.md:168-176`). Vellum already streams `wav_b64` SSE events (`api.py:3768-3774`) — this is the natural upgrade path.
4. **Barge-in, VAD, and stop-phrase UX** — quiet-room noise-floor calibration with `barge_in_threshold_multiplier`/`grace_seconds`, two-stage silence VAD (`silence_threshold` 200 / `silence_duration` 3.0), and a strict whole-utterance `stop_phrases` list (`voice-mode.md:151-166,178-189`; `tools/voice_mode.py:432-433`). The agent is even told its reply was cut off (`voice-mode.md:189`).
5. **On-device wake word with explicit privacy framing** — openWakeWord default + open-vocabulary sherpa, engine pinned deps, 16 kHz mono capture, pause-while-capturing, and the doc contract "no audio leaves your machine until you actually speak a command" (`tools/wake_word.py:9-21,44-45`; `website/docs/user-guide/features/wake-word.md:16-18,297-303`). This is the cheapest high-visibility voice feature for Vellum and fits the local-first stance.
6. **Sarvam MCP as an optional cloud voice backend, not a default** — the server is first-party (`sarvamai/sarvam-mcp`, `pyproject.toml:13`), stdio-launchable (`uvx sarvam-mcp`, `server.py:213-214`), exposes `sarvam_tools_stt_transcribe`/`sarvam_tools_tts_speak`/`sarvam_tools_tts_stream` plus a one-call `sarvam_tools_voice` loop (`workflows/voice.py:30-120`), and is a clean Indic-languages complement to Moonshine/Kokoro. But official policy defaults to training on inputs with a 30-day retention window and US/EU cloud transfers (privacy-policy) — so it belongs behind an explicit opt-in, mirroring Hermes' own default-local privacy stance (`use-voice-mode-with-hermes.md:142`).
7. **STT passthrough for custom pipelines** — `stt.enabled: false` keeps the raw audio path and hands it to the agent for diarization/archival pipelines (`voice-mode.md:421-426`); and refuse to feed secret stores to any STT engine (`transcription_tools.py:2526-2533`).
8. **Hallucination filter** — 26 known Whisper-style phantom phrases + regex, applied before the transcript enters the conversation (`voice-mode.md:191-193`) — directly reusable against Moonshine output today.
9. **Voice mode persistence + per-chat modes** — gateway-persisted per-chat `off | voice_only | all` states in a JSON file (`gateway/run.py:6231`, `gateway/slash_commands.py:2914-2954`) — a simple, copyable pattern for Vellum's voice-on/off UX.

---

## Not-found / unresolved items

- **Sarvam in Hermes:** zero references to "sarvam" anywhere in `NousResearch/hermes-agent` (verified by full-tree case-insensitive search) — Topic 1 Q5's Sarvam question is conclusively "not found".
- **Voice MCP servers in Hermes' catalog:** none (`optional-mcps/` = blender, comfy-cloud, figma, linear, n8n, unreal-engine).
- **Hermes STT streaming:** Hermes has no streaming/partial-transcript STT path; STT is file-based only (`transcribe_audio`, `tools/transcription_tools.py:2524`).
- **Kokoro in Hermes:** no native Kokoro provider; supported only via OpenAI-compatible `base_url` + `lang_code` (e.g. Kokoro-FastAPI) or a `type: command` provider (`website/docs/user-guide/features/tts.md:147,276-281`).
- **Audio privacy/retention in Hermes docs:** no explicit audio-recording retention or redaction policy found in the voice docs or `agent/redact.py`; only the wake-word "no audio leaves your machine" and local-STT-as-privacy-default statements exist.
- **Sarvam realtime STT in MCP:** the MCP server exposes REST + batch STT only; the `saaras:v3-realtime` streaming STT exists in the official API docs but has no MCP tool yet.
- **LangChain/LangGraph in sarvam-mcp:** no first-party compatibility notes in the repo (generic MCP clients only).
- **Commit drift risk:** Hermes main moves fast (HEAD `1be70d6`, 2026-08-05); line numbers may shift. Sarvam MCP HEAD `14305aa` (2026-07-06, v0.2.8).
