# Combined dictation, title bar and accounts PR — 2026-10-22

Draft PR #226 now includes local Whisper dictation alongside its original Windows
title-bar and account-presentation changes. Dictation uses Large v3 Turbo by
default, inserts editable text without sending, and keeps completed recordings
and transcripts locally until deletion. Voice settings own language preference,
dictionary phrases, shortcuts and searchable recording history. Download, copy
and confirmed deletion use the existing adapter and action contracts.

The original hosted CI run, 39603010872 at commit 4e12156, passed the frontend
build and tests. The frontend dependency audit failed on Vite 7.3.6 advisories;
the manifest and lockfile now use patched 7.3.7. The backend run reported
3239 passed, 28 skipped and one failure: an omitted EPUB malware-scan approval
returned 409 instead of the missing-field contract's 422. The endpoint now
checks form-field presence separately from explicit false approval, which
continues to return 409 before any book record is created. Regression source
also covers false, zero and off form values.

No local tests, builds, native smoke runs or UI automation were executed while
preparing or publishing this update, as requested. Static diff and scope review
and lockfile generation are not runtime validation. Earlier dictation reports
and screenshots describe the development checkout and synthetic fixtures, not
fresh validation of this isolated PR. Updated hosted CI results are recorded
in the PR description after publication.

Model binaries, isolated runtimes, local recordings, credentials and unrelated
shared-checkout work are excluded. Existing live-voice HTTP/UI paths remain in
place. Main/preload changes require a full Electron restart. Attended microphone
capture, native title-bar behavior, shortcut/focus handling and the user's mixed
Kannada/English speech remain manual validation gates; dictionary hints and a
saved language preference do not guarantee exact recognition.
