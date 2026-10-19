# Native desktop browser verification — 2026-10-18

## Implementation

Electron WebContentsView replaces the streamed preview in desktop mode. The
canonical DedicatedBrowser owner attaches only to broker-registered guest page
targets through the app-owned CDP endpoint. Existing BrowserAgent delegation,
browser App Actions, profile/settings contracts, permissions, and download
receipts remain the control path. The web client retains the Brave fallback.

Guest tabs are sandboxed, isolated from the workspace session, and receive no
Vellum native API. The private broker rejects missing authentication and browser
Origin requests. Native profile data lives adjacent to, not inside, existing
Brave profile files. Clearing native cookies preserves the Brave directory.

Native bounds follow split resizing. During a drag the view detaches to preserve
pointer capture; global pointer-up, lost capture, and blur release resize mode.
Browser menus use a temporary still beneath the DOM menu. Settings and modal
surfaces suspend the native view. Escape explicitly exits HTML fullscreen.

## Verification

- Backend browser, native bridge, settings, and YouTube history regression scope:
  178 passed, 2 skipped. The known Starlette/AnyIO deprecation warning remains.
- Frontend suite: 474 passed in 48 files. After the resize and modal changes the
  two affected UI files passed all 47 tests again.
- Desktop Node suite: 7 passed, including private broker authentication and
  guest URL/profile restrictions. Host smoke passed in real muted Electron.
- Native integration smoke uses a deterministic BrowserAgent planner with real
  browser tools, not a model or simulated DOM. It verifies native navigation,
  typing, clicking, cursor visibility, scrolling, tabs, fullscreen exit, isolated profile cookies,
  native cookie clearing, saved downloads, and rejection of frame streaming.
- Live desktop UI check opened Wikipedia through the sidebar and address bar,
  confirmed the native page dimensions match the panel before and after a drag,
  used Ctrl+L, created and closed a tab, and opened the browser menu. No frame
  request or browser stream was opened. No streamed preview image existed.
  Browser settings opened above the native view. Closing the final tab closed
  the panel; reopening it showed one clean local homepage.
- Frontend production build and Windows Forge ZIP packaging passed. The existing
  standalone script bundling warnings remain; the host copies the built assets.

## Limits

This is Electron Chromium, not an embedded Brave executable. Brave cookies were
not copied. Real signed-in providers, extension loading, protected media/DRM,
long video sessions, and OS pointer control are not verified. The existing
Spotify SDK in the live workspace reports “No supported keysystem was found.”
The local fixture tests do not establish model planning quality or real provider
permission behavior. The packaged app still needs the canonical backend running.

The API and development desktop were restarted to load the integration. Other
services and unrelated working-tree changes were retained. No commit, push, or
pull request was created.
