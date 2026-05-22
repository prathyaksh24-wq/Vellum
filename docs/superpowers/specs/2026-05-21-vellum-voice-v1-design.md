# Vellum Voice V1 Design

## Brainstorm Summary

Vellum should accept spoken turns without creating a second memory or agent pipeline. The browser records a push-to-talk clip, the backend transcribes it locally, the transcript enters the same agent stream as typed text, and the final transcript/answer pair is learned through the existing `_background_learn` path. Raw audio is transient and is never written to the vault, FTS5, Honcho, or audit logs.

The chosen v1 design is backend-local voice:

- STT: Moonshine Voice, lazy-loaded, default English model.
- TTS: Kokoro ONNX, lazy-loaded, default `af_heart`.
- UI: one mic control beside the current text input, plus replay controls on assistant messages.
- API: multipart voice endpoints and SSE events compatible with the current `/api/chat/stream` flow.

## Brainstorm Audit

1. Assumption-check: The original plan assumed direct `tiny`/`small` model selectors in Moonshine. Current Moonshine Python docs expose `get_model_for_language("en")` and `Transcriber.transcribe_without_streaming(audio_data, sample_rate)`, so v1 stores `VOICE_STT_MODEL` as configuration metadata but resolves through the documented language helper. Accepted risk: finer model selection may require package-specific options later.
2. Architecture stress: Empty audio, missing dependencies, unavailable model files, browser permission denial, stream abort, and TTS failure must fail independently. Transcript failure stops the turn; TTS failure still returns text.
3. Alternative dismissal: Browser-local STT/TTS was rejected for v1 because the existing backend already owns privacy, model config, and stream orchestration. Always-on VAD was rejected because push-to-talk is safer and easier to validate.
4. Requirement gap: "Learns from speaking" means transcript text, not raw audio. The source is marked `voice` in `Agent/Responses` while preserving the same memory path.
5. Composability claim: Voice composes by sharing the chat streaming helper. The voice endpoint emits an extra `transcript` event before normal token/tool/final events and extra `audio` events as sentence chunks become available.
6. Scope honesty: Real-time duplex audio is not v1. The backend streams synthesized sentence chunks after sentence boundaries; it does not synthesize every token.
7. API surface drift: `/api/voice/turn` uses stable event names and accepts form fields, leaving room for future engine selection without changing the chat contract.
8. Failure mode map: STT dependency missing returns a clear 503-style API error; no speech returns 400; TTS dependency/model failure emits text normally and suppresses audio; stream abort cancels queued frontend playback.
9. YAGNI sweep: No wake word, no faster-whisper UI selector, no raw audio archive, no full settings panel, no voice activity auto-turn-taking.

## Design

Backend voice lives in `backend/agent/voice/`:

- `audio.py` decodes uploaded WAV bytes into mono float32 samples and sample rate, validates duration, and encodes float samples back to WAV bytes.
- `stt.py` defines a small STT interface plus `MoonshineTranscriber`. It lazily imports `moonshine_voice`, downloads/loads its English model through the documented helper, and returns a stripped transcript.
- `tts.py` defines a TTS interface plus `KokoroSpeaker`. It lazily imports `kokoro_onnx` and `soundfile`, loads `kokoro-v1.0.onnx` and `voices-v1.0.bin` from `VOICE_MODEL_DIR`, and returns WAV bytes.

`backend/agent/api.py` gets shared stream helpers so both `/api/chat/stream` and `/api/voice/turn` run through the same agent event loop. Voice adds:

- `POST /api/voice/transcribe` for debugging and tests.
- `POST /api/voice/turn` for push-to-talk conversations.
- `_background_learn(..., source="agent")`, with voice passing `source="voice"`.

Frontend changes are constrained to `frontend/ui/vellum-chat.html`:

- Add a mic button beside the input.
- Use `MediaRecorder` to record audio, then send multipart form data.
- Render the `transcript` event as the user message.
- Render text tokens as today.
- Decode `audio` SSE chunks into Web Audio playback.
- Stop cancels recording, the active fetch, and any queued audio.
- Add a small replay button to assistant messages that calls TTS for stored text through a lightweight endpoint if audio is not already available.

## Test Strategy

Backend tests use fake STT/TTS objects injected into the API module, not real model dependencies. This keeps CI fast and proves the Vellum contract:

- Transcription endpoint returns transcript metadata.
- Empty/no-speech transcript returns a clean 400.
- Voice turn emits `transcript`, `token`, `audio`, and `final`.
- Voice learning records `source="voice"`.
- TTS failure does not break text streaming.

Frontend tests focus on pure helpers and DOM behavior where practical: state transitions, transcript insertion, audio queue cancellation, and replay request shape.

## Sources

- Moonshine docs: `Transcriber`, `get_model_for_language`, and `transcribe_without_streaming`.
- Kokoro ONNX README/example: `Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin").create(...)`.
