# Vellum Voice V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add push-to-talk local voice turns that transcribe speech, run the existing Vellum agent stream, speak the answer with Kokoro, and learn from spoken transcripts through the existing memory path.

**Architecture:** Voice is an adapter around the current chat API, not a second agent. The backend owns STT/TTS and emits SSE events; the frontend records mic audio and plays returned WAV chunks.

**Tech Stack:** FastAPI multipart uploads, SSE, Moonshine Voice, Kokoro ONNX, soundfile, Web Audio, MediaRecorder, pytest, Vitest.

---

## Audited Execution Notes

- Use TDD for backend behavior: add failing tests before production code.
- Keep raw audio transient.
- Treat TTS as best-effort: text response must still work if synthesis fails.
- Do not add wake word, auto-VAD turn-taking, or a full settings screen in v1.
- Do not require real Moonshine/Kokoro models in tests.

## File Map

- Create `backend/agent/voice/audio.py`: WAV decode/encode helpers.
- Create `backend/agent/voice/stt.py`: lazy STT provider and injection point.
- Create `backend/agent/voice/tts.py`: lazy TTS provider and injection point.
- Create `backend/agent/voice/__init__.py`: package marker.
- Modify `backend/agent/config.py`: voice settings.
- Modify `backend/agent/api.py`: voice endpoints, shared stream helper, source-aware learning.
- Modify `backend/requirements.txt` and `backend/pyproject.toml`: voice dependencies.
- Create `scripts/download_voice_models.py`: idempotent local model downloader.
- Create `backend/tests/test_voice_api.py`: backend contract tests.
- Modify `frontend/ui/vellum-chat.html`: mic UI, recording, voice SSE handling, audio playback, replay.

## Tasks

### Task 1: Backend Voice API Tests

**Files:**
- Create: `backend/tests/test_voice_api.py`

- [ ] Write tests for `/api/voice/transcribe`, empty speech, `/api/voice/turn` event order, `source="voice"` learning, and TTS failure fallback.
- [ ] Run `python -m pytest backend/tests/test_voice_api.py -q` and confirm failures are due to missing voice API.

### Task 2: Voice Settings And Adapters

**Files:**
- Create: `backend/agent/voice/__init__.py`
- Create: `backend/agent/voice/audio.py`
- Create: `backend/agent/voice/stt.py`
- Create: `backend/agent/voice/tts.py`
- Modify: `backend/agent/config.py`

- [ ] Add voice settings with safe defaults.
- [ ] Implement WAV decode/encode helpers.
- [ ] Implement lazy Moonshine and Kokoro providers with clear runtime errors when optional dependencies or model files are missing.
- [ ] Run the voice adapter tests and confirm adapter-level imports do not require installed model packages.

### Task 3: Shared Agent Streaming And Voice Endpoints

**Files:**
- Modify: `backend/agent/api.py`

- [ ] Extract the existing `/api/chat/stream` event loop into a shared async generator.
- [ ] Add `POST /api/voice/transcribe`.
- [ ] Add `POST /api/voice/turn` with transcript, token, tool, audio, final, and error events.
- [ ] Extend `_background_learn` with a `source` argument and pass it to `store_qa_pair`.
- [ ] Run `python -m pytest backend/tests/test_voice_api.py backend/tests/test_api.py -q`.

### Task 4: Dependencies And Model Setup Script

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/pyproject.toml`
- Create: `scripts/download_voice_models.py`

- [ ] Add optional runtime packages to manifests.
- [ ] Add an idempotent downloader for `kokoro-v1.0.onnx` and `voices-v1.0.bin`.
- [ ] Add Moonshine cache warm-up through `get_model_for_language("en")`.
- [ ] Run syntax/import checks for the script without requiring downloads during tests.

### Task 5: Frontend Push-To-Talk

**Files:**
- Modify: `frontend/ui/vellum-chat.html`

- [ ] Add mic button markup and state CSS.
- [ ] Add recorder helpers using `MediaRecorder`.
- [ ] Add `sendVoice(blob)` that consumes `/api/voice/turn` SSE.
- [ ] Render transcript event as a user message.
- [ ] Play `audio` events through a queue and stop playback on cancel.
- [ ] Add replay button on assistant messages that requests TTS for stored text.

### Task 6: Verification

**Files:**
- Existing test files only unless fixing discovered issues.

- [ ] Run backend targeted tests: `python -m pytest backend/tests/test_voice_api.py backend/tests/test_api.py -q`.
- [ ] Run frontend tests: `npm test -- --runInBand` from `frontend`, or the closest supported Vitest command if `--runInBand` is unsupported.
- [ ] Run `npm run build` from `frontend`.
- [ ] Self-audit implementation against the spec and list any accepted residual risks.
