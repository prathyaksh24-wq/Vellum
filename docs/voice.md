# Local voice and dictation

## Dictation into the composer

The microphone button or the configured shortcut (Ctrl+Shift+D by default) records speech for an editable text prompt.
The level bars reflect actual microphone audio. Pause/Resume retains the recording;
Done runs local multilingual Whisper Large v3 Turbo and appends recognized text to the current
draft. Cancel discards the recording or cancels transcription. No message is sent
until the normal Send action. Typing during transcription is preserved. Whisper
does not invoke tools, select the chat model, or write conversations or memory.
The normal text field, placeholder and attachment button remain available while
dictating. The waveform occupies the existing bottom toolbar between small cancel,
pause/resume and square Stop controls, without an extra divider or recorder row.
Stop ends capture and shows a centered “Transcribing…” status in that toolbar,
then inserts the transcript into the current draft. Recording time remains
available on waveform hover and to assistive technology. Existing and newly typed
text, image attachments, file drop and paste remain usable during capture.
The currently served development HTML does not hot-reload: after a source update,
finish/cancel active recording and reload the Electron window with Ctrl+R.

Run `scripts/setup-dictation.ps1` once to install the isolated runtime and download
the pinned public `dropbox-dash/faster-whisper-large-v3-turbo` checkpoint into
`data/models/whisper-large-v3-turbo` (about 1.62 GB of weights/configuration).
`source.json` records the downloaded repository revision. Turbo supports
multilingual transcription with automatic language detection. Startup uses the
model's actual audio feature dimensions, including large-v3's 128 mel features.
For a smaller installation, use `scripts/setup-dictation.ps1 -Model small` and
set `DICTATION_MODEL_DIR=data/models/whisper-small`. Existing Small weights are
retained during an upgrade. Model identity in status and transcripts follows
the installed checkpoint rather than always reporting Small.
Runtime inference sets Hugging Face offline mode and loads only local model files.
Completed audio and transcript text are retained locally when history saving is enabled.
Cancelled recordings are discarded. The transcript becomes ordinary draft text; after Send, the selected
chat model and normal disclosure settings apply.

The existing `agent.voice.session` lifecycle also owns the Whisper worker, with
serialized requests, startup/turn timeouts, cancellation cleanup, process-tree
termination and parent-exit handling. `/api/voice/dictation/status`, `/prepare` and
`/transcribe` are declared as additive endpoints in the existing voice capability.
Status distinguishes installation from a warmed worker and reports the actual
chosen device. WAV uploads are limited to 15 MiB and five minutes. Silence yields
an empty transcript and the composer offers another recording. Active capture is
limited to five minutes, with a fifteen-minute wall-clock limit including pauses.

Configuration: `DICTATION_ENABLED` (true), `DICTATION_MODEL_DIR`
(`data/models/whisper-large-v3-turbo`) and `DICTATION_DEVICE` (`auto`, `cpu`, `cuda`).
`VOICE_ENABLED` disables all voice transport, including dictation. Automatic device
selection attempts GPU FP16 with an encoder smoke test, then CPU INT8. On Windows,
the worker can reuse compatible CUDA DLLs from the existing LFM model environment
when installed; this is optional, and CPU inference needs no CUDA installation.
An explicit `cuda` selection fails visibly if unavailable rather than falling back.
Diagnostics are bounded in `data/logs/dictation-worker.log`, without transcript or
audio logging. English/Hindi and mixed-language accuracy require real-user testing.

Electron remembers an explicitly approved microphone in its desktop profile.
Main-process permission changes require closing and reopening Vellum; Ctrl+R
only refreshes the renderer. Dictated drafts use the same Send and music owner
as typed messages. Conversational openings such as “Okay play a song…” are
recognized, and longer spoken preambles reach the full typed music interpreter
without extracting and executing a guessed sentence fragment.

## Voice settings and local dictation history

Settings → Voice separates **Conversation** from **Dictation**. Conversation
defaults to the single local speaker. Users can explicitly choose optional
OpenAI reply speech (`gpt-4o-mini-tts`), one of its 13 built-in voices, and speaking
speed, or return to local speech. Speech preferences belong to the existing
device settings snapshot and `settings.device.update` receipts. The current
selection is captured when a voice session starts; restart an active voice
session after changing it.

This option changes reply synthesis, while the LFM conversation engine and
microphone processing stay local. Only generated reply text is sent to OpenAI,
using the backend's existing OpenAI key; no microphone recording, transcript,
history or key enters that request body. Dictation stays local independently.
`POST /api/voice/preview` synthesizes a fixed sample after an explicit preview
click. Cloud failures are shown without silently switching provider. The UI
states the external processing and provider charges. Cloud speech buffers the
local reply text before synthesis, so it adds latency compared with local audio.

Settings → Voice → Dictation contains configurable hold/double-tap and single-tap
shortcuts, recording history, and the dictation dictionary. Shortcuts operate
while Vellum is focused and use the same composer recorder; they never submit a
chat. Hold begins capture and release finishes it. Two quick taps leave capture
running hands-free until the next press or the square Stop button. Default hold
is Off; default single-tap is Ctrl+Shift+D. Backspace clears a shortcut in its
key editor. Editing, navigation, and live-voice shortcut conflicts are rejected.

Advanced contains the saved spoken-language preference and history switch.
There is no language dropdown in the prompt box. Auto detects each recording;
selecting Kannada sends `kn` to the same Whisper worker, including when the
recording contains a few English words. This avoids the automatic Kannada/Tamil
choice; it does not guarantee perfect mixed-language transcription. The settings
and history language dropdowns reuse the shared Personalization `VSelect`.

The canonical `DictationStore` owns `data/voice/dictation.db`: preferences,
completed transcript metadata, and original uploaded WAV bytes in one local
SQLite transaction. Every completed nonempty dictation is retained until the
user deletes it; there is no latest-20 retention cap. A recording row shows its
local date/time, detected language, requested mode and duration. Read expands
full text, Copy copies exact text, and the options menu downloads the original
WAV or requests confirmed deletion of both audio and transcript. Sent chat
messages are unaffected. Old transcript-only rows remain readable but cannot
recover audio that was never saved. Switching saving off stops future storage
without erasing existing history. A storage failure preserves the editable draft
and reports the failure. History never automatically enters agent memory.

Dictionary phrases (up to 100, each 100 characters) are normalized and sent as
Whisper `hotwords` on every request. They guide recognition rather than replacing
recognized text or guaranteeing exact spelling. Settings writes use
`dictation.settings.update`; `dictation.history.delete` uses the existing
operation-bound confirmation and receipt machinery. The voice capability
publishes preferences, paginated/searchable history and a validated per-entry
recording-download endpoint. Binary audio transport stays in the voice adapter.

## Publication scope

This PR adds dictation to the current main branch without replacing its existing
live-voice HTTP/UI implementation. The isolated worker lifecycle and its local
parent-process helper are included as dictation dependencies. Later reply-speech,
streaming, embedding and desktop-profile migration work is excluded. The PR also
retains the previously published title-bar and account-presentation changes.
No tests, builds or live checks were rerun while preparing the isolated draft,
as requested. Earlier verification reports describe the development checkout,
not a fresh validation of this PR projection.

Whisper Small was explicitly uninstalled from the development machine after
Turbo was verified active. Local model binaries, runtimes and recordings are
ignored and are not part of this source PR. The setup script retains an explicit
Small option for other installations; Turbo remains the default.
