# Local Whisper dictation verification — 2026-10-19

Implemented in the current working tree without committing or publishing. Existing
unrelated changes were preserved. The desktop host is Electron; no Tauri integration
or new native bridge was introduced.

## Installed model and runtime

- Public multilingual `Systran/faster-whisper-small` revision
  `536b0662742c02347bc0e980a01041f333bce120`, downloaded into the ignored
  `data/models/whisper-small` directory. `model.bin` is 483,546,902 bytes.
- Isolated Python environment: `data/models/whisper-small/.venv`.
- Validated runtime pins: faster-whisper 1.2.1, CTranslate2 4.8.3,
  huggingface-hub 2.2.0, PyAV 16.1.0. The initially resolved PyAV 19.0.1 removed
  the `metadata_errors` argument expected by this faster-whisper decoder;
  actual transcription exposed the failure. Pinning PyAV 16.1.0 fixed it.
- Offline runtime startup loads only the local checkpoint. Automatic device
  selection verified CUDA FP16 on the RTX 5070 Ti Laptop GPU. Compatible CUDA
  libraries were available in the existing isolated LFM installation.
- `pip-audit` found no known vulnerabilities in the 24 installed runtime packages
  at verification time. This is a dependency-database check, not a security audit
  of the application or model.

## Verification performed

- Focused dictation and existing voice backend suites: **28 passed**.
- Backend capability discovery check: **1 passed**, 96 deselected.
- Complete frontend suite after the placeholder change: **488 passed** across
  49 files, using two workers. Earlier high-concurrency runs overlapped model
  benchmarks and caused unrelated five-second test timeouts; the bounded run
  passed. Initial sandbox-only localhost tests failed with EACCES; the complete
  run outside that sandbox passed.
- Production Vite build passed. It retains existing non-module static-script
  notices. Action Parity fingerprint and transport exemption were updated.
- Real local speech inference used a 6.878-second WAV synthesized with Windows
  System.Speech. Expected and recognized text matched exactly:
  “This is a local dictation test. Please put these words in the prompt box
  without sending the message.”
- CUDA: cold session including imports/model load **8.700 s**, warm **0.309 s**.
  CPU INT8: cold **41.437 s**, warm **20.785 s**, while other verification jobs
  were running. These are single-fixture observations, not comparable broad
  benchmarks or a latency promise for real dictation.
- An isolated Electron check used the actual sandboxed desktop host/preload,
  canonical composer, permission-request handler, and generated WAV as Chromium's
  fake microphone. Its test dialog stub granted only that synthetic input.
  Recording, pause, local transcription and existing-draft preservation passed.
  The resulting draft was “Existing typed draft. This is a local dictation test.
  Please put these words in the prompt box without sending the message.” No chat
  message was submitted. Frontend adapter tests also cover resume, cancel while
  permission is pending, abort/late-response suppression and empty recognition.
- The Electron check asserted that the placeholder element is absent during
  recording. Connecting, recording, paused and processing states all suppress the
  placeholder through the same active-state condition; a CSS guard additionally
  hides placeholder rendering whenever a non-error dictation strip exists.
- The already-open browser preview was confirmed to lack the placeholder guard
  and Vite live-reload client. After reload it contained both new guards. An
  already-open Electron window likewise needs Ctrl+R after finishing/cancelling
  active dictation, since this development HTML is served without hot reload.

## Evidence and limits

Local runtime evidence is ignored under `.test-data/dictation-live/`, including
`electron-result.json`, `electron-paused.png`, `electron-transcript.png`,
`electron-narrow.png`, `frontend-final.log`, `cpu-check.log`, and
`dependency-audit.json`. Screenshot capture in a hidden window can lag the DOM;
the transcript assertions and JSON result are the authoritative functional
evidence. Synthetic microphone tests do not establish physical microphone,
noise, user-accent, Hindi/mixed-language accuracy or long-session performance.
Those remain attended checks. No Large/Turbo model was installed or benchmarked.

The normal local API and development UI were started to make the feature usable.
Raw audio is not persisted by the production dictation transport. Only deliberate
synthetic test fixtures are retained in the ignored test directory. Model files,
package caches, logs and temporary app profiles remain ignored by Git.
