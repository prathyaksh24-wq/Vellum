# Vellum desktop

The desktop host uses Electron. React/Vite and the FastAPI backend retain their
existing owners. This migration replaces the Tauri runtime, Rust build and
desktop command bridge; it does not migrate application databases or install
the agent logic to a different runtime. The packaged app includes a Python
sidecar running those same owners.

## Development

Run `scripts/start-desktop.ps1` from the repository. It reuses `start.ps1` to
start missing services and then runs Electron. Add `-SkipHoncho` only when
intentionally using the existing memory fallback. Existing running services
are reused; they are not terminated or restarted. Node.js/npm is supported,
with a fallback to Codex's bundled Node/pnpm on this Windows environment.
Node.js 22.12 or newer is required. There is no Rust or C++ desktop build prerequisite.

The main window directly opens the canonical workspace on loopback port 5173.
The Vellum menu opens the existing computer-use controls. Detached conversations
use the original canonical conversation ID and reuse one window per ID.
The computer-use overlay is nonfocusable and click-through. The backend accepts
`source: electron` to avoid creating a second overlay. Its legacy `tauri` source
remains accepted for older clients; no Tauri runtime is shipped.

## Native interface and ownership

`window.VellumDesktop.invoke` exposes only `backend_health`, `workspace_ready`,
`protected_audio_ready`,
`open_vellum_window`, `open_conversation_window`, `set_overlay`, and `skill_file`.
The skill-file command accepts a registered name plus open/reveal; it resolves
the Markdown path through the backend catalog. It accepts no renderer-supplied path.
Main-process checks reject unknown commands, unexpected arguments, unrelated
pages, and subframes. Renderers retain sandboxing, context isolation, and web
security without Node integration. Third-party pages do not get a Vellum bridge.

Windows workspace/conversation windows use a compact themed, draggable menu bar
with the existing Vellum, Edit, View, and Window menus. Caption buttons remain
native through the Windows title-bar overlay. The menu bridge accepts only
those four menu identifiers, bounded anchors, and opaque theme colors from a
registered trusted top-level workspace. The ordinary browser preview has no
native menu bridge. Restart the desktop host after updating main/preload code;
Ctrl+R alone cannot replace its native window frame or IPC handlers.
Media and notification requests require a native user decision. Microphone-only
approval for the trusted workspace is remembered in `workspace-permissions.json`
inside Electron's local user-data profile. It survives reloads, detached chat
windows and app restarts; the profile cutover retains that choice. Camera access,
combined audio/video requests, unknown media requests and embedded websites do
not inherit microphone approval. Removing this file while the app is closed
resets the saved microphone choice. Operating-system microphone restrictions
remain in effect independently.

Application data stays in the existing backend, vault, and configured model
locations. No browser profile is copied or deleted. Electron maintains a
separate workspace session, so device settings in a regular Brave/WebView2
profile are not automatically imported. The regular web UI remains supported.

Closing the main workspace quits Vellum, stops its development watcher, and
gracefully shuts down the backend it started, including music downloads.
Minimizing keeps the workspace and background tasks running.

`scripts/start-desktop.ps1` and `npm run dev` build the current desktop UI and
watch workspace source changes. Successful UI builds reload the workspace window
on port 5184. Backend edits restart an API owned by Electron, and changes to
Electron shell code or assets relaunch the app. Quit any separately started
Vellum API before starting desktop development if you want API auto-reload.

## Verification

From `desktop/`:

```powershell
npm ci
npm test
npm run smoke
npm run smoke:browser
npm run package
```

The smoke check uses muted Electron windows, a disposable local fixture, and
an isolated temporary app profile. It never opens a user's media or browser
session. It verifies the real preload, detached window reuse, overlay behavior,
and rejected untrusted-page commands. Frontend account and conversation checks
exercise the new bridge through the existing adapters and App Actions.

## Embedded browser

The desktop browser renders real Chromium pages in sandboxed Electron
`WebContentsView` instances. BrowserAgent and browser App Actions still use the
canonical `DedicatedBrowser` owner and Playwright worker. An app-owned loopback
CDP connection exposes only registered guest tabs to that owner; chat, settings,
and detached workspace pages are excluded. The guest preload exposes no Vellum
native API. A private, authenticated broker descriptor is stored in the ignored
`.desktop-runtime` directory and is removed when its host exits.

Desktop page input and rendering do not use JPEG frames, the `/browser/frame`
endpoint, or the browser WebSocket stream. The native view follows the panel and
split divider bounds. Vellum temporarily detaches it while menus or dialogs
cover it, preparing and decoding a single still before detaching for browser
menus or divider drags. A drag survives normal parent status refreshes and the
live view is restored at the new bounds on release. New guest views have a
usable initial viewport before the workspace mounts them. The regular web UI
continues to support the owned Brave stream when no desktop host is connected.

Named profiles retain separate cookies in `data/browser-session/electron` or
`data/browser-session/profiles/<profile-id>/electron`. Existing Brave profile
files remain untouched and are not imported; sign in to sites again in the
embedded browser. Profile switching, permissions, history, downloads, and
cursor preferences retain their existing backend settings and action receipts.
The agent cursor is drawn inside the actual page as actions move the page mouse.
Human page input yields agent control. Browser shortcuts stay within the embedded
browser, and Escape exits page fullscreen without closing its tab or panel.

`npm run smoke:browser` drives a real BrowserAgent through the native surface
using a disposable fixture. It checks typing, clicks, scrolling, visible cursor,
tabs, fullscreen exit, isolated profiles, cookie clearing, and saved downloads.
It never opens the user's profile or media.

## Packaging

`npm run package` builds the frontend, stages the backend, and creates a Windows
x64 app folder under `desktop/out`. `npm run make` creates a ZIP distribution.
Electron Forge packages the host/frontend with ASAR; Python, installed Python
dependencies and backend source assets are placed outside ASAR in
`resources/backend-runtime`. The existing protected-audio signing gate still
applies. Python/Node dependency installation is a publisher preparation step,
not something the app silently runs on the user's laptop.

The backend builder uses the prepared repository `.venv`, or
`VELLUM_BUILD_PYTHON`, and validates the declared backend dependencies. It copies
the Windows Python runtime and installed site-packages, preserving distribution
metadata/licenses while excluding caches, test fixtures and editable checkout
hooks. This initial package includes installed ML libraries and can be large;
workspace model/cache directories are not copied. `.env`, vaults, databases, sign-ins,
browser profiles and user skill state are not copied into the release. Generated
resources and package outputs are ignored by Git. Check the build environment
without copying or installing anything:

```powershell
.\.venv\Scripts\python.exe desktop/scripts/build-backend.py --check
```

### Workspace and backend startup

First packaged launch asks for the existing Vellum workspace folder containing
`data`. It saves only that selection in `desktop-workspace.json` in the desktop
profile; it does not move, import or duplicate user data. `VELLUM_WORKSPACE_ROOT`
can explicitly select a folder. Backend code and bundled plugin implementations
come from the release; mutable state and `.env` stay in the selected workspace.
Existing absolute vault/model locations remain in effect.

The desktop host checks `/api/desktop/runtime` for protocol version, exact
backend build identity and workspace before reusing a server. Otherwise it starts
the bundled interpreter on loopback port 8000, waits for readiness, and opens the
workspace. The backend takes an OS-held workspace lease before importing API
stores. The development `start-api.ps1` uses the same lease-aware entry point.
An unrelated service, older unidentifiable backend or different backend build
produces an explicit startup error; it is not killed or silently adopted. An old
server needs one explicit restart onto the new entry point. Use separate data
workspaces to run different development and installed backend builds together.

### Startup performance

The packaged window opens while its backend starts, showing a local startup
surface. Its compiled workspace waits on the trusted `workspace_ready` command
before mounting account and conversation views, so a cold backend cannot be
mistaken for an empty account. The desktop API adapter uses the host's fixed
verified backend instead of a stale renderer-local URL override.

`frontend/vite-desktop.config.mjs` compiles the canonical HTML entry's Babel/JSX
scripts at build time. It uses the frontend's installed React/ReactDOM dependency
for both the shell and module-backed controls; the development preview retains
its existing runtime. The desktop no longer downloads CDN React/Babel or compiles
the shell JSX at startup. External web-font links use bundled/system fallbacks.
This is a desktop-only build adaptation, not a second UI implementation.

Protected-audio component preparation runs concurrently rather than holding the
workspace window for up to a minute. Only Spotify player preparation awaits the
trusted `protected_audio_ready` command before its Widevine probe. Other controls
remain available while the component initializes. Cold backend imports and
provider/model/network work are still real costs; no startup time or performance
improvement has been measured in an attended app run yet.

Content-free phases are written to `.api-runtime/desktop-startup.json`: Electron
ready, workspace selection, backend readiness, window request, document load and
protected-audio readiness. Document load is not a claim that every provider or
model is ready. This gives subsequent cold/warm startup work an actual baseline.

A source-host launch of the prepared UI on 2026-10-31 recorded its window
document loaded at 637 ms and backend ready at 6,636 ms. The window title and
both local HTTP endpoints were checked; private page content was not inspected.
This is one instrumented source launch, not a clean-install benchmark or proof
that every feature is ready at those times. Its first attempt exposed Windows'
venv interpreter redirection: the actual API PID differs from the spawned
launcher PID. New launches therefore echo a per-launch correlation ID through
the typed identity handshake instead of comparing those PIDs.

The installed frontend uses port 5184, leaving the development UI's 5173 alone.
Account/provider return checks and playback-origin checks accept this exact
additional loopback port. UI-only preferences stored under the old 5173 browser
origin are not automatically migrated to 5184; canonical backend data is reused.
A per-workspace native-host lock prevents two updated Electron hosts from
overwriting the same browser broker. Startup errors offer the log folder;
backend logs are in the workspace's `.api-runtime/desktop-backend*.log`.

The desktop controls its own backend through a private parent/child pipe, not a
public shutdown endpoint. Quit waits for normal API shutdown; if work is still
finishing, it reports that rather than forcibly killing it. A desktop-process
crash closes the pipe and requests child shutdown. External backends are never
stopped by this path.

### Installation, updates and remaining release checks

To review the prepared compiled UI without installation, set
`VELLUM_DESKTOP_BUNDLED_UI=1` when launching the existing desktop source host.
It serves `desktop/resources/ui` on 5184, starts the workspace backend through
the same manager, and does not need a Vite development server. It still uses
the development backend environment; this is not installed-release acceptance.

Installation is deferred. No installer, startup entry, file association or
installed application has been changed by this work. The current distribution
is a Windows app folder/ZIP; a signed installer and unattended updater/feed
remain separate release work. Updates must replace the application while it is
closed; data stays outside the app. There is no hot replacement of an active
backend or forced restart of a conversation.

Ollama/models, Honcho/PostgreSQL and provider services retain their existing
owners and configuration. The package starts the FastAPI backend; it does not
silently install Docker, models, browser extensions or external provider CLIs.
The existing YouTube collector/catch-up policy remains in the automation owner;
offline notification delivery still depends on provider authorization and the
hosted collector. Power-off/resume delivery is a separate live acceptance check.

This change has syntax checks, a production UI build and a staged backend build,
not an attended installed-app
acceptance run. New focused lifecycle/lease tests are supplied but were not run
under the existing no-tests instruction. Packaging, clean-machine startup,
upgrade/data retention, crash recovery, YouTube catch-up and Spotify playback
still need verification before claiming an installed release is ready.

The embedded engine is Electron's Chromium, not the installed Brave executable.
Chrome extension installation, Widevine/protected media, native browser profile
import, and host system-cursor control are separate capabilities and are not
established by native embedding. Agent model planning and backend request time
are still independent of page rendering performance.

## Spotify protected audio

Stock Electron 44.9.0 does not provide usable Widevine audio in the local probe.
Self-contained Spotify playback was verified on Windows using the official
Castlabs ECS 44.5.1+wvcus runtime with a production streaming VMP signature.
The unsigned development runtime connected but Spotify's audio-license endpoint
returned HTTP 500 and audio stopped. After EVS signing, the same endpoint returned
200; the user confirmed continuous audio for the requested one-minute test and
working Pause, Resume, Next and Previous. A subsequent automated production-
controller check reached 65 seconds and verified those transport actions again.
Days/months of playback remain unverified.

`npm run dev`, `npm start` and `scripts/start-desktop.ps1` prefer a locally
provisioned distribution at `.desktop-runtime/protected-audio` (repository root).
An explicit `ELECTRON_OVERRIDE_DIST_PATH` takes precedence. Without either, they
use the installed stock Electron package and the UI explains unavailable DRM.
This uses Electron's existing CLI and runtime override, not a second player or
backend. The local distribution is ignored by Git and survives `npm ci`.

To provision another Windows development machine:

1. Obtain an official supported [Castlabs ECS release](https://github.com/castlabs/electron-releases/releases)
   and verify its published SHA-256 before extracting its distribution into
   `.desktop-runtime/protected-audio`. Do not copy Widevine from another browser;
   ECS downloads the component on first launch. The tested Windows x64 archive
   was `electron-v44.5.1+wvcus-win32-x64.zip`, SHA-256
   `c7d51e4bf80de9ef18b3306b0d140059bb203510d3dfc88f3404049a12c90f89`.
2. Follow [Castlabs EVS setup](https://github.com/castlabs/electron-releases/wiki/EVS).
   Sign the extracted directory with `python -m castlabs_evs.vmp sign-pkg .desktop-runtime/protected-audio`,
   then verify it with `python -m castlabs_evs.vmp --no-ask verify-pkg .desktop-runtime/protected-audio`.
   A development-only certificate is insufficient for this Spotify test.
   Credentials remain in the official client's local configuration, outside Git.
3. Close older Vellum desktop instances and launch normally. The host waits for
   Widevine installation before preparing its Spotify player, while the workspace
   opens independently. Re-sign after replacing
   the ECS distribution, and retest Spotify playback after runtime/CDM updates.

The tested ECS version is older than stock 44.9.0, which includes later upstream
fixes. Keep that maintenance gap explicit and update the provisioned distribution
when a supported ECS build containing those fixes becomes available. Stock
development dependencies remain unchanged. Forge's `readPackageJson` hook selects
ECS for packaging, because Forge derives the version from package metadata and
overrides `packagerConfig.electronVersion`. Its download mirror targets official
Castlabs releases. `VELLUM_ELECTRON_ZIP_DIR` optionally selects an already verified
archive directory. The `postPackage` hook requires the publisher's EVS client to
sign and verify the final output; signing/verification failure fails packaging.
Set `VELLUM_EVS_PYTHON` to that client's Python executable. Credentials stay in the
official client's local configuration, never in the app or source tree. A local
Windows x64 package was built, signed and verified successfully. End users receive
the signed app and do not need an EVS account.

The normal development launcher selects `.desktop-runtime/workspace-profile`.
Packaged Windows startup selects `%USERPROFILE%/.vellum/desktop-profile`, before
initializing sessions. `VELLUM_DESKTOP_PROFILE` explicitly overrides either.
First migration copies existing UI storage/preferences through a staging directory
and preserves the original profile. It does not transplant cookies, encryption
keys, CDM state or caches; website sessions may need a new login. An existing
destination is never overwritten. Backend Spotify authorization is independent.

This profile choice has a specific local basis: the signed runtime returned
Spotify license HTTP 403 with both fresh and existing AppData profiles. Castlabs'
documented Widevine verification reported `PLATFORM_TAMPERED` there, versus
`PLATFORM_SOFTWARE_VERIFIED` with fresh workspace, Documents and user-home
profiles. Identical DLL/signature hashes, permissions, path separator changes and
a Local State comparison did not explain the difference. A byte-identical runtime
copied into Local AppData also failed runtime verification, even with the known
good workspace profile. The underlying location-dependent verification cause is
unresolved; the profile selection is a tested local mitigation, not evidence that
every installation path works. A Windows installer/updater and clean-install
audio acceptance on representative machines remain release gates. Do not ship
an AppData installation on the assumption that offline signature verification
alone establishes runtime VMP verification.

macOS signing order needs a separate release integration: VMP must precede macOS
code signing; the current hook rejects a configured `osxSign` pipeline rather than
silently signing in the wrong order. Windows VMP follows executable code signing.
Linux audio and macOS packages have not been validated by these Windows tests.
Spotify developer-mode access is also separate from app signing; wider account
access requires Spotify's approval. See [Spotify quota guidance](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).

A successful Spotify OAuth connection is separate from protected audio support.
The workspace probes the Widevine EME key system before creating a local SDK
player; unsupported hosts show an explicit browser recovery link instead of
claiming a connecting playback device.

Open the same Vellum workspace in a protected-content-capable browser such as
Brave, enable its Vellum player, and keep that tab open. Desktop Play can then
reuse that verified Vellum device through the existing backend and App Actions.
It checks both the live device list and canonical ready state on each request;
it neither takes over the other window's lease nor claims a local audio device.
This is browser-backed playback controlled from Electron, not embedded Electron
audio. This remains a fallback for machines without a provisioned signed runtime.

The host permits `mediaKeySystem` only for the workspace origin and the exact
HTTPS Spotify SDK/embed origins inside a registered workspace window. Spotify
frames receive no microphone/camera or native bridge authority. This permission
policy alone does not install Widevine or provide a DRM license.

For playlists whose songs Spotify's Web API denies, Music shows Spotify's official
playlist iframe. Its own artwork/title appears once, replacing the native header
and empty native table. Play in Vellum still sends the exact playlist context to
the canonical player. Spotify owns the embedded list and its internal controls;
Vellum cannot sort/edit it or treat it as a complete native API result. No scraped
copy, user token transfer, or parallel playlist store is created. Embed playback
is independent of the Vellum SDK and is not a workaround for missing DRM.
