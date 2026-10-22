# Dictation composer refinement — 2026-10-19

The final layout follows the supplied Codex recording reference while retaining
Vellum's existing composer. The text field and its normal placeholder remain
available above the waveform. The Add button, image attachments, typing, paste
and drop continue using their existing owners. This supersedes the earlier
placeholder-hiding behavior described in the initial dictation verification.

The waveform occupies the existing toolbar, without an additional divider or
recorder row. Small cancel, pause/resume and square Stop controls replace the
large text buttons. Stop ends capture and displays centered “Transcribing…”
status before appending the recognized text. Recording duration remains
available through a tooltip and assistive technology. The selected chat model
and explicit Send behavior are preserved.

Verification:

- Focused dictation, voice, composer and Action Parity checks: 68 passed.
- Complete frontend suite: 488 passed for the refinement; final focused checks
  and production build also passed after the reference/placeholder adjustments.
- Action Parity handler fingerprint remains unchanged because the existing
  capture controls retain their handlers.
- Actual Electron test with the production sandboxed host/preload and synthetic
  microphone: passed. It verified visible placeholder geometry, editable input,
  image attachment during capture, pause, local transcription, existing draft
  preservation, and no automatic chat submission.
- Empty composer height during capture: 92.6 CSS px versus 94.6 px idle. The
  recorder's border is 0 px. Icon controls measure 28 by 28 px. At a 720-pixel
  Electron window width, the toolbar did not overflow.
- Production build and scoped whitespace checks passed. The mechanical design
  detector's remaining warnings concern incumbent unrelated styles.

Evidence is retained in the ignored `.test-data/dictation-live/` directory:
`electron-result.json`, `electron-check.log`, `dictation-compact-desktop.png`,
`dictation-compact-narrow.png`, `frontend-refined.log`, `build-refined.log`.
Hidden-window screenshots can lag DOM updates; functional assertions and measured
geometry are the authoritative test results.

The user's running Electron window was not refreshed automatically because it
was in use. The development HTML has no hot-reload client; Ctrl+R in the chat
loads the updated composer after finishing or cancelling any active recording.
No backend inference implementation was changed, and no Git publication occurred.
