# Remembered Electron microphone approval — 2026-10-19

The canonical Electron host now saves an explicit microphone-only approval in
`workspace-permissions.json` inside the active desktop profile. Requests from
registered, trusted workspace windows reuse that approval across captures,
reloads, detached conversations and process restarts. The existing profile
cutover preserves the permission file. Denials are not saved as approvals.

The approval is scoped to the configured workspace origin and entry path.
Camera, combined/unspecified media, embedded frames, unrelated local pages and
unregistered web contents do not inherit it. Pending microphone prompts are
coalesced, and the requesting page is checked again after the dialog resolves.
Malformed, oversized or mismatched stored permissions require fresh approval.
Protected Spotify audio continues using its separate existing permission rule.

Verification performed:

- Complete desktop suite: **28 passed**, including seven new permission tests
  and the profile migration assertion. Tests used writable repository-local
  temporary storage. Two loopback networking tests initially failed under the
  sandbox with `EACCES`; the suite passed with loopback networking enabled.
- Actual Electron, production sandboxed host/preload, isolated disposable
  profile and synthetic microphone: first process requested permission once
  across three captures, including a page reload. A separate second process
  made three captures, including another reload, with **zero dialogs**.
- Scoped whitespace and JavaScript syntax checks passed.

The Electron fixture supplies the Allow response programmatically and uses a
synthetic microphone. It verifies real Electron permission callbacks and disk
persistence; it does not exercise a fresh human click or Windows OS microphone
consent. Results and fixture are retained under ignored
`.test-data/dictation-live/microphone-restart-{first,second}.json` and
`microphone-restart-check.cjs`.

The user's open Electron process was left running. A full Vellum restart is
required to load this main-process change; refreshing the page is insufficient.
The old version did not persist its approval, so choosing Allow once after the
restart establishes the saved grant. To reset it, close Vellum and remove the
permission file. OS microphone restrictions remain independent. No Git
publication was performed.
