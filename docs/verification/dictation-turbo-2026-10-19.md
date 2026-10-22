# Whisper Turbo upgrade and spoken music routing — 2026-10-19

The user reported a repeating microphone prompt after refreshing Vellum, two
dictated music requests that reached YouTube, and occasional recognition/spelling
errors with Whisper Small. They confirmed they refreshed rather than fully
closed and reopened Electron. The running main process predated the permission
fix, and its desktop profile had no saved microphone approval.

## Changes and observations

- Installed `dropbox-dash/faster-whisper-large-v3-turbo` at immutable revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`. The model file is 1,617,884,929
  bytes. Its SHA-256 matches the publisher's pinned metadata:
  `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`.
  Hugging Face's transfer stalled; a resumable direct HTTPS download of the same
  pinned artifact completed and passed this integrity check. Configuration,
  tokenizer, vocabulary and preprocessor files came from the pinned snapshot.
- The default model directory and setup now select Turbo. Existing Small weights
  remain intact, and `-Model small` plus an explicit model-directory override
  supports rollback. The runtime dependencies did not change. Source metadata
  identifies the model in worker startup, status and transcript contracts.
- Worker warm-up now uses the installed feature extractor's mel dimension:
  128 for large-v3/Turbo and 80 for Small. Inference remains local, offline,
  multilingual transcription with automatic language identification.
- The latest local conversation contained “Okay play a song from my liked song
  playlist” and a longer testing/disfluency preamble. Both failed MusicAgent's
  original `can_handle` check in the regression loop. “play a song” succeeded in
  the saved conversation. The channel was ordinary text chat in each case.
- MusicAgent now recognizes conversational openings before commands. A spoken
  preamble can reach its existing typed planner without treating that preamble
  as the first compound action or executing an extracted fragment. Song titles
  containing Okay/Yeah/So/Well are preserved. The actual upgraded model heard
  “liked song playlist” as “like song playlist” in one synthetic clip; that narrow
  unquoted collection wording now maps to Liked Songs in the parser. The draft
  transcript is not rewritten.
- Under the user's explicit instruction to remember their already-given access,
  saved microphone approval in the active `.desktop-runtime/workspace-profile`
  using the existing permission-file schema and exact workspace scope. This
  supersedes the earlier expectation that this user must approve again after
  restart. No microphone recording or permission dialog was driven in their UI.

## Verification

- Final affected backend suites: **334 passed**. These cover MusicAgent,
  conversational language, compound commands, collection selection, playback,
  parser resources, reported failures, voice sessions, dictation and voice APIs.
  The separate frontend-capability contract test also passed: **1 passed**.
- Tests first reproduced both failed music matches and the synthetic “like song
  playlist” misclassification, then passed after their fixes. Routing tests use
  the real catalog/dispatcher and provider fixtures after a YouTube active turn.
  Full spoken wording reaches the typed interpreter. No real Spotify action was
  triggered by these tests.
- Isolated actual CUDA transcription: 6.878-second synthetic English clip
  transcribed exactly. First process cold 8.260 s / warm 0.416 s. A repeat process
  cold 4.842 s / warm 0.556 s (concurrent tests, warm OS file cache). Synthetic
  3.944-second music command transcribed in 0.392 s and parsed as `play_liked`.
  These are fixture timings, not broad speed or accuracy benchmarks.
- Restarted only the verified local backend process. A real multipart upload to
  `/api/voice/dictation/transcribe` returned Turbo/CUDA metadata and the music
  transcript. `/api/voice/dictation/status` reports enabled, available, ready,
  `model=openai/whisper-large-v3-turbo`, `device=cuda`.
- Scoped whitespace checks passed. Generated weights, model environment and
  fixtures/results remain ignored under `data/models/` and `.test-data/`.

Evidence: `.test-data/dictation-live/turbo-check.py`, `turbo-results.json`,
`music-command.wav`, and the saved model `source.json`. Research and source links
are in `docs/research/whisper-upgrade-2026-10-19.md`.

## Limits and remaining user action

The larger model still produced the one documented recognition error; an
improvement in this user's Hindi, English, names or mixed-language speech has
not yet been measured. The user previously confirmed Small worked with Hindi
and English, but no new real microphone sample was recorded for Turbo. No fresh
live Spotify playback was attempted; routing/provider integration was checked
with fixtures and the user had already demonstrated typed playback.

The user stopped Computer Use and requested no further Computer Use. It was
stopped. Before that, the screenshot provider returned an unrelated foreground
page despite a verified Vellum handle; an attempted follow-up capture was
automatically rejected, and no unrelated page was edited. Process/window
identity was subsequently verified with read-only metadata. The actual Electron
window remains open and must be fully closed/reopened by the user to load the
main-process permission fix; Ctrl+R is insufficient. The saved grant is already
present for the next launch. No Git publication occurred.
