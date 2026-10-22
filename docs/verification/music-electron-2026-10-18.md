# Electron music and public playlist verification - 2026-10-18

Observed live backend: connected Premium account with playback scopes; no available
device at the first read. Playlist items requests for 2000s bangers, Nostalgic
Bollywood Songs and Top 100 returned HTTP 403. Kannada returned its songs. The
connector already uses the current /playlists/{id}/items endpoint. The user
subsequently confirmed playback in Brave.

An isolated hidden stock Electron 44.9.0 process, disposable profile and local
fixture probed com.widevine.alpha with temporary audio-only EME configuration.
Even with mediaKeySystem allowed it returned NotSupportedError: Unsupported
keySystem or supportedConfigurations. No Spotify account, token or audio was
used in that probe.

Reproduced failing permission tests and frontend tests before the recovery fixes.
The host now scopes DRM permission to registered workspace windows and Spotify
origins. The playback controller detects unavailable Widevine before loading or
claiming a local SDK, and its shared-device path accepts only a live ready Vellum
device. Tests also reject stale/reconnecting shared owners.

A production MusicPage fixture with the real public 2000s bangers official iframe
showed 100 track entries in the browser. No playback was started. This proves
public embed rendering for that playlist, not complete API access or full audio.
The compact and expanded controls use the existing canonical player. A responsive
390px check showed the iframe fitting the available width. The first visual pass
revealed duplicate native/embed headers; native header, sort/edit controls and
empty track headings are now suppressed for this fallback. Play in Vellum remains
explicitly distinct from Spotify's internal controls.

Native Electron audio remains unavailable in the stock runtime. No DRM runtime
fork, license/signing service, library copy, account reconnect or Git publication
was performed. Shared-device control is covered with provider-state fixtures;
physical Electron-to-Brave audio output and long-session audio remain unverified.

Final checks: 480 frontend tests across 48 files passed; 9 desktop tests passed;
26 focused Spotify UI/Music contract tests passed. The existing real Electron
host smoke passed its preload isolation, detached-window reuse, overlay and
untrusted IPC checks. Frontend build and desktop resource copy passed. Vite
reported the existing non-module script warnings; Electron fixture smoke
reported its existing fixture CSP warnings. No full backend suite was run for
this frontend/host-only change.

Final browser confirmation showed exactly one iframe at the full detail width,
no native duplicate header and no empty native table headings. Screenshot:
.scratch/spotify-electron-qa/playlist-final.jpg. This was a production-component
fixture with live public Spotify content, not the user's Electron window.

Follow-up investigation on 2026-10-18: an isolated, checksum-verified official
Castlabs ECS 44.5.1+wvcus runtime installed Widevine 4.10.3112.0 and passed the
audio-only EME probe. The regular desktop dependency remains stock 44.9.0;
the fork has not been adopted as the default or packaged for distribution.
The test loaded the real Vellum workspace and canonical playback controller.
The user reported that audio started then became silent. Scoped native request
metadata captured repeated HTTP 500 responses from
https://api.spotify.com/v1/widevine-license/v1/audio/license, followed by SDK
playback_error events. No tokens, request bodies or media were captured.

Castlabs EVS 1.3.2 verify-pkg independently rejected this runtime with
"Certificate is valid for development only". Production signing is the next
test, not a proven resolution yet. The same symptom and endpoint are documented
with a signing resolution in https://github.com/castlabs/electron-releases/issues/193;
official setup is https://github.com/castlabs/electron-releases/wiki/EVS.
The user requested the local signup path. An interactive wizard is prepared in
.scratch/spotify-electron-qa/spotify-signup.ps1; private signup and signing must
complete before the next live playback check. The task-owned failing test window
was closed to stop license retries. The temporary served SDK probe was removed.

Two separate regressions were reproduced and fixed: a stalled SDK activation
acknowledgement prevented connection, and stalled state/volume reads prevented
lease heartbeats. Sampling now has bounded waits and connection does not await
the activation acknowledgement. Host visibility also no longer waits solely for
ready-to-show when an external iframe is pending. A temporary diagnostic callback
initially crashed on the audio event's argument shape; it was corrected to query
isCurrentlyAudible() and the visible test window was verified by process title.

Follow-up checks: all 46 playback-controller tests and six focused host/CDM tests
passed. Full frontend run passed 479 tests, with three routing tests denied
loopback access by the sandbox; those three passed when rerun with loopback
access. Continuous physical audio and working transport controls in Electron
remain unverified. No Git publication was performed.

Signed-runtime follow-up: the user completed the private EVS signup/signing
wizard. verify-pkg now reports a valid production streaming signature with
1369 days remaining. The same real Vellum workspace was reopened using that
signed runtime. Its audio-license response changed from 500 to 200, native
audibility became true, and the observed playback position advanced. The user
confirmed sound remained on during the requested one-minute test and Pause,
Resume, Next and Previous all worked. These observations establish this local
vertical slice; they do not establish days/months of playback reliability.

The signed distribution was copied into the Git-ignored
.desktop-runtime/protected-audio directory and its production signature verified
again. The normal npm desktop entry now configures Electron's existing runtime
override from this provisioned directory before invoking the official CLI.
It preserves an explicit caller override and stock startup when no distribution
is provisioned. The ordinary launcher returned v44.5.1; its selection regressions
passed. Stock 44.9.0 dependencies/lockfile and Forge release packaging were not
changed. This avoids treating a locally signed test as a signed distributable;
the older ECS engine's maintenance gap is documented in docs/desktop.md.

All 15 desktop tests passed across the initial sandbox run and the rerun of
loopback-denied tests with loopback access. The existing real Electron smoke
passed on the signed ECS runtime: isolated preload, detached chat reuse, overlay,
and untrusted IPC rejection. Its existing fixture CSP warnings remained. The
frontend/controller verification from the previous follow-up remains applicable;
no further frontend code was changed during signing/cutover. No commit, push,
branch creation or PR publication occurred.

Final local cutover: after the test window was closed, the normal desktop entry
was launched with `node scripts/start.cjs .` from desktop. The visible workspace
process was observed at .desktop-runtime/protected-audio/electron.exe, and a
fresh verify-pkg check again accepted its production streaming signature. No
startup error appeared in the new host log. The listening/control acceptance
above was performed in the same signed binary with an isolated profile; a
second physical listening test in the ordinary profile was not requested.

Subsequent ordinary-profile testing did reproduce silence and rapid track skips.
The same signed runtime returned license HTTP 403 under the Roaming profile.
Resetting SDK storage, cache or Spotify cookies, using a fresh session partition,
and creating fresh Roaming/Local AppData profiles did not resolve it. Fresh
workspace-local profiles passed; retaining the original UI Local Storage there
also passed. Profile migration now retains UI data through an atomic staging
directory, preserving the original and excluding runtime encryption/CDM/cookies.

The production playback controller/App Actions fixture on the final development
profile reached 65,718ms, paused, resumed the same track, advanced once to the
second track, and returned to the first track. Audio-license responses were 200.
The fixture deliberately disconnected at its successful end; that explains the
stop the user observed during this test. The ordinary app was then reopened with
no automatic stop, and native telemetry showed a 200 license and audible output.

The explicitly approved install-profile comparison used fresh Windows Local
AppData, native audibility and playback progress. It started audio, then received
license 403 and SDK playback_error, so it failed. The approved quiet vendor
verification followed the Castlabs VMP Lab protocol against Google's public UAT
endpoint (no Spotify credentials or audible content). Workspace returned
PLATFORM_SOFTWARE_VERIFIED; Local AppData returned PLATFORM_TAMPERED. CDM DLL and
signature hashes/permissions matched. Normalizing separators and temporarily
comparing Local State did not change the failing result. The temporary Local
State comparison was restored. A copied, offline-verified signed runtime under
Local AppData also reported TAMPERED with either profile. Fresh Documents and
user-home profiles returned SOFTWARE_VERIFIED. This establishes the runtime
verification difference, not its underlying vendor/OS cause.

The first vendor harness launch collided on a fixed port and displayed an
EADDRINUSE popup. Those owned probes were closed. Subsequent probes used an
ephemeral loopback port with an error handler and completed without that popup.
No such harness is part of production startup; the temporary diagnostics import
and served Spotify fixture were removed. Debug artifacts remain ignored.

Packaged Windows now defaults to the verified user-home profile; development
keeps the verified workspace-local profile and explicit overrides remain intact.
Forge's packaging metadata hook selects ECS 44.5.1+wvcus without changing the
stock development dependency. A real Windows x64 package was built through
Forge's API using the checksum-verified ECS archive, then production-signed and
verified with 1369 days remaining. The CLI packaging attempt encountered the
machine's absent global npm and temporary pnpm-runner configuration; using the
normal script API avoided those environment issues. This is package/signature
evidence, not installed-app audio acceptance. AppData executable placement,
other machines, OSes and multi-day sessions remain unverified/failing release
gates as described in docs/desktop.md. No Git publication occurred.

Final desktop regression run: 21/21 passed, including the real Forge version
resolver, noninteractive package signing failure paths, UI-preserving profile
migration and packaged Windows home-profile selection. Frontend verification
remains the preceding 482 passing tests; no frontend changes followed that run.
The normal Vellum window was reopened through its standard launcher with the
working development profile. It has no diagnostic auto-stop. The source tree no
longer contains the temporary diagnostic hook or served Spotify test fixture.

Vendor reproduction matrix, all on the same Windows host and signed ECS build:

| Runtime location | Profile location | UAT VMP status |
| --- | --- | --- |
| Checkout `.desktop-runtime/protected-audio` | Workspace profile | SOFTWARE_VERIFIED |
| Same | Fresh Local AppData | TAMPERED |
| Same | Fresh user-home `.vellum/desktop-profile` | SOFTWARE_VERIFIED |
| Same | Fresh Documents directory | SOFTWARE_VERIFIED |
| Local AppData copy | Workspace profile | TAMPERED |
| Local AppData copy | Local AppData profile | TAMPERED |

Both runtime copies pass offline production signature verification. Executable
SHA-256: f0147b356a8ad6d199d8862605fd4b5d76658e987f7293040a155c80599507ab.
Both CDM DLLs: 7b44e84403fbb3faee15ca2d56eb8432fdf4eb68812c4460abdd20972528e825.
Both CDM signature files: f9f160cb5ca37ef81a3aa80eeb7fef8b302e18c82d92c34f42503e0ab085ada5.
No sandbox-disabling setting was adopted. Disabling only CdmServiceSandbox in
a vendor-only diagnostic did not change the failing AppData result.

The matrix can be independently repeated by opening the documented
[Castlabs VMP Lab](https://castlabs.github.io/wv-vmp-lab/) in the signed runtime
with each userData location. UAT test content needs no Spotify account. The
[vendor status reference](https://github.com/castlabs/electron-releases/wiki/VMP)
distinguishes static signature checks from server-observed platform verification.
No issue/support message was sent externally.

The final profile-selection change was repackaged and its production signature
verified successfully. Inspection of that final ASAR confirmed the home-profile
implementation was included, the temporary main diagnostics import and Spotify
fixture page were absent, and no downloaded Widevine CDM was bundled. The normal
Vellum window remained visible after package verification.

Follow-up user report on 2026-10-20: music remained audible and all playback
controls worked in the previous day's normal Electron session. No exact session
duration was recorded. This is user-reported everyday-use evidence, not a
controlled fresh-install or multi-day acceptance test.

PR preparation on 2026-10-21 isolated these Spotify changes on current main,
excluding the development checkout's unrelated microphone, custom window-chrome,
account, voice, and browser changes. No tests or builds were run in this pass,
as explicitly requested. Earlier results above were not rerun on this PR branch.

CI follow-up on 2026-10-21: run 39602431546 passed frontend build/tests, Python
dependency audit, dependency review and secret scanning. Frontend dependency audit
failed on Vite 7.3.6 (GHSA-698v-4r3x-3vcv, GHSA-r825-w8mm-5pxw and
GHSA-587h-7wmj-h5pm); the manifest and lockfile now select patched 7.3.7.
Backend reported 3239 passed, 28 skipped and one failure: missing EPUB scan
approval returned 409 instead of 422. FastAPI 0.156.8 explicitly infers False
for omitted boolean form fields. The API now checks field presence at its HTTP
boundary, preserving missing-field validation while still rejecting explicit
False before ingestion. Regression coverage also distinguishes malformed input.
No local tests or builds were run for this follow-up; GitHub checks are the
validation source for the pushed CI fix.
