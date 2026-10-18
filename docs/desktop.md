# Vellum desktop

The desktop host uses Electron. React/Vite and the FastAPI backend retain their
existing owners. This migration replaces the Tauri runtime, Rust build and
desktop command bridge; it does not migrate application databases or install
another copy of the agent runtime.

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

`window.VellumDesktop.invoke` exposes only `backend_health`,
`open_vellum_window`, `open_conversation_window`, and `set_overlay`.
Main-process checks reject unknown commands, unexpected arguments, unrelated
pages, and subframes. Renderers retain sandboxing, context isolation, and web
security without Node integration. Third-party pages do not get a Vellum bridge.
Media and notification requests require a native user decision.

Application data stays in the existing backend, vault, and configured model
locations. No browser profile is copied or deleted. Electron maintains a
separate workspace session, so device settings in a regular Brave/WebView2
profile are not automatically imported. The regular web UI remains supported.

Closing the desktop host does not stop the Python backend or automation
scheduler. Model, voice, music, memory, specialist, and permission owners remain
unchanged by this host migration.

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

`npm run package` builds the existing frontend and creates a Windows app folder
under `desktop/out`. `npm run make` creates a ZIP distribution. Electron Forge
packages the host and frontend with ASAR. Generated frontend copies and package
outputs are ignored by Git. The packaged frontend is served from the app on
loopback port 5173; it fails visibly if another service already owns that port.
The existing backend must be running separately. Bundled Python distribution,
code signing, an installer/updater, and automatic backend provisioning are not
implemented by this migration.

The embedded engine is Electron's Chromium, not the installed Brave executable.
Chrome extension installation, Widevine/protected media, native browser profile
import, and host system-cursor control are separate capabilities and are not
established by native embedding. Agent model planning and backend request time
are still independent of page rendering performance.
