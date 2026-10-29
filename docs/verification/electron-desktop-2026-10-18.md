# Electron desktop host verification — 2026-10-18

This records the initial host-only migration. The subsequent native browser
implementation and checks are recorded in
[Native browser verification](native-browser-2026-10-18.md).

## Scope

Replaced the desktop Tauri runtime and build with Electron 44.9.0 and Electron
Forge 8.0.1. Kept the existing React/Vite workspace, Python runtime, backend
data ownership, BrowserAgent and owned Brave transport. No Git publication,
backend service restart, data migration, default-browser attachment, Rust/C++
installation or change to model files was performed.

The shared checkout already contained substantial work in other domains. The
migration changes the desktop files and launcher, account/window bridge calls,
one backend overlay-source condition and its existing regression test, CI,
README, architecture documentation and one changelog entry. Other pending work
was not reset, staged, committed or copied between checkouts.

## Passed checks

- Desktop Node tests: 5 passed. Validated loopback workspace selection,
  conversation window identity/encoding, trusted-page checks, native command
  validation, and packaged static-file serving/traversal restrictions.
- Real muted Electron smoke: passed with a disposable local fixture and app
  profile. Verified sandboxed/context-isolated preload, no Node in the renderer,
  no preload in a child frame, detached conversation reuse, nonfocusable
  always-on-top overlay open/close, and rejection of unrelated-page IPC.
- Complete current frontend suite: 48 files, 473 tests passed.
- Complete affected `backend/tests/test_api.py`: 97 tests passed. Included the
  `electron` and legacy `tauri` source paths without duplicate Python overlays,
  ordinary UI overlay start/stop, and capability discovery.
- Production Vite build: passed. Existing classic-script bundling warnings
  remain; static adapters/components are copied by the existing build plugin.
- Windows x64 Electron Forge package and ZIP make: passed.
- npm dependency audit: 132 packages audited, zero reported vulnerabilities.
- Desktop launcher PowerShell parse and `git diff --check`: passed.

The Windows app folder measured approximately 383.4 MiB; the ZIP measured
163.8 MiB. These include Electron and frontend assets, not Python, model files,
downloads or browser/user data. Build outputs remain Git-ignored.

The first native smoke exposed an overlay close-during-load race that could
show a blocking load error. Closed/aborted navigations are now excluded from
that error path. Smoke timeouts and missing results fail explicitly.

## Not established

No claim is made about full signed-in account flows, live voice hardware,
long-running music or video, or all backend feature suites. The native smoke
uses a fixture, not the user's current application session. The ZIP is not a
signed installer and still requires the existing backend to be running.

At this initial host-only checkpoint, native WebContentsView rendering was still
unimplemented and the browser used the Brave stream. The subsequent native
integration is covered by the linked native browser verification report above.
No extension compatibility, DRM playback, or system-cursor behavior was
established by this initial host migration.
