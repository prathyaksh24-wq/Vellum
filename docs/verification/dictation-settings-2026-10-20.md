# Dictation settings and local recordings — 2026-10-20

Settings → Voice → Dictation follows the supplied reference: shortcut preferences,
compact recording rows with transcript/date/time/language/duration, exact text
copy, original WAV download, confirmed deletion and dictionary words. All completed
nonempty dictations are kept locally until deleted; there is no latest-20 cap.
Advanced holds the spoken language and save-history switch. The composer has no
language selector and reads the saved backend preference for each upload. Both
settings language controls use the shared Personalization VSelect component.

The existing settings App Action owner writes preferences and confirms destructive
history operations. DictationStore owns a local SQLite database with transcript
metadata and WAV blobs committed together. Cascading deletion removes both. Older
text-only rows remain supported; unsaved past audio cannot be reconstructed.
Dictionary phrases reach Whisper hotwords, without rewriting transcripts. Configured
shortcuts operate only while Vellum is focused, through its existing recorder.

## Verification performed

- 107 affected backend and capability checks passed (94 unrelated tests deselected).
  Coverage includes retained recordings beyond 20, restart persistence, exact audio
  download, preference validation, dictionary forwarding, shortcut normalization
  and collisions, failed history saves, and operation-bound deletion/replay.
- 70 focused frontend checks passed, including the mounted production component,
  shared dropdown interaction, dictionary failure/retry, copy/download/expand,
  confirmed delete/cancel, configured toggle/hold/double-tap, editable composition,
  and early shortcut release while microphone permission is pending.
- Full frontend run: 503 passed, 2 failed. Failures are unrelated working-tree
  drift in the Accounts component's reviewed handler fingerprint and an old
  conversation-search source assertion expecting direct scrollIntoView rather
  than the newer compacted-message reveal helper. These files/behaviors were
  preserved. Dictation/main-page fingerprints were reviewed and updated only for
  task controls; the unrelated Accounts fingerprint was not refreshed.
- Production Vite build passed. Existing classic/Babel script bundling warnings
  remain. Scoped whitespace checks passed.
- Hidden sandboxed Electron fixture rendered the production Dictation component,
  VSelect and CSS with real adapters against an isolated loopback fixture server.
  It verified Kannada preference saving, two recorded languages, confirmed
  deletion, open dropdown/menu geometry and no horizontal overflow at 1280×820
  and 540×860. Fixture history and receipts are synthetic. No Computer Use or
  control of the user's open application was used.
- Actual installed Whisper Large v3 Turbo ran on CUDA through the real API with
  an isolated temporary DictationStore and public Google FLEURS Kannada validation
  row 81, pinned/licensed as documented in the language research note. A 4.5-second
  recording returned language kn and Kannada script when the saved preference
  was kn. Original WAV download matched all 144044 uploaded bytes, including
  after opening a new store instance. End-to-end request including cold startup
  took 6.593 seconds. This is one ordered fixture, not an accuracy benchmark or
  the user's mixed Kannada/English recording. Kannada spelling errors remain.
- Windows TestClient shutdown printed ignored asyncio pipe-finalizer warnings
  after the successful real-model check; clean long-session shutdown was not
  established by that fixture.
- The verified idle port-8000 backend was restarted. Health, preferences and the
  recording-download capability are available. The user's selected language
  was preserved. The Electron renderer was not refreshed automatically; Ctrl+R
  loads the updated settings after active recording is finished or cancelled.

Ignored evidence: `.test-data/dictation-language/` contains the public audio,
`live-api-result.json`, `settings-electron-result.json`, desktop/narrow PNGs,
`frontend-suite.log` and `build-final.log`. Public fixture data never entered the
user's history database. No Git publication occurred.
