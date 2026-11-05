# Shared commands and workspace shell — 2026-11-03

## Implementation

`desktop/electron/commands.cjs` defines 46 commands, their labels, bindings, availability and focus rules. It has no DOM, storage or IPC access. Vite imports the same module through `commands-entry.js`; Electron requires it directly. The App owns one runtime whose handlers invoke the existing conversation, workspace, browser and settings owners. Electron menus forward command identities; native browser key events forward normalized input to that runtime.

Command search (`Ctrl+K`, or `Ctrl+Shift+P` while editing), the shortcut reference, native menu definitions and shortcut tooltips use these definitions. Existing Vellum aliases remain. Editor bold/link keys, composition, AltGraph and previously handled events retain their owners. Browser fullscreen Escape remains native; local overlays consume dismissal before app-level dismissal. Dictation's configurable hold/release behavior stays in its existing hook and its current bindings appear in the reference.

Number keys default to Ctrl+1–9 for browser tabs and Alt+1–9 for sidebar chats; Settings → Shortcuts can swap the arrangement. The choice uses `settings.device.update`, not a separate preference store. Nine selects the final item. Unsupported temporary-chat, unread-management, side-chat and coding/review features are explicitly listed as unavailable.

Browser new/close/cycle/reopen, navigation, cache-bypassing reload and Find use the existing `browser.session.control` queue and UI source validation. Reopening retains at most 20 HTTP(S) URLs in process memory, keyed by the existing profile; embedded credentials are excluded, history cleanup clears that profile's recovery list, and no new persistent tab store is introduced. A reopened tab reuses the sole blank page where possible. Native Find targets only an owned WebContents; regular browser Find uses the existing page owner.

The destination rail reveals the hidden main sidebar on fine-pointer hover, including landing and chat. Crossing from the rail into the revealed sidebar keeps it open; leaving both hides the temporary reveal. Pinning remains the existing layout action. Home clears the selected chat to show the landing page without creating a conversation.

The shell removes outer workspace, landing, Music and Plugins frames. The More menu and Library dropdowns use `SharedRowBackground`; Library uses the incumbent `VSelect`. Morphing tooltips derive shortcut hints from the registry and participate in native-browser occlusion. Hidden tooltip nodes no longer occlude the guest view. Plugins is labelled “Plugins”; Knowledge graph uses the shared `Nodes` icon.

## Checks performed

- Fifteen focused Node command/chrome tests passed: aliases, focus and overlay conflicts, composition/AltGraph, number-key swapping, Find/Analytics priority, repeat handling, duplicate-dispatch prevention, tab-close versus window-close, native editor keys and bounded IPC requests.
- Six backend tests passed with fake pages/targets only: profile-bound reopening without an extra blank page, empty recovery, bounded credential-free recovery memory, owned native Find, force-reload CDP cleanup and number-preference validation. The Windows sandbox prevented asyncio's internal socket pair from initializing; the same isolated tests passed outside that shell restriction.
- The focused Action Parity cache-query identity regression passed (one selected test; twelve unrelated tests skipped). Reviewed source identity now strips a cache query/fragment while still rejecting unknown components.
- The actual modified JSX parsed with no newly unbound names; Electron main/preload/native-browser syntax checks passed.
- Isolated headless Brave used actual presentation components and CSS with synthetic chat/file state, a fresh context, muted audio and blocked network. It observed Home returning to landing; sidebar reveal and leave behavior on both landing and chat; the Plugins tooltip; moving highlights in More and Library; keyboard command selection through the final project; changing the number-key preference; and no horizontal overflow at 640px. Landing (with and without a workspace toolbar), Music and Plugins measured 0px frame margin, border and corner radius. The command highlight aligned with its selected final row (0px offset). No page errors were recorded.
- The final desktop build passed in 13.97 seconds. It retains the existing classic-script and large-chunk warnings. Bundle: `Vellum Default Re-designed-DPdYqBJb.js`; stylesheet: `Vellum Default Re-designed-TDJEvlLy.css`.
- The web server on 5173 returned HTTP 200 and served the registry through Vite's ESM import transform. The live action catalog included `reopen_tab` and `number_shortcuts`.
- Reopened the compiled desktop app. Its served HTML referenced `DPdYqBJb.js`, and that bundle returned HTTP 200. The first launch detected an older backend build; only the verified backend for this workspace and the desktop instance launched by this task were restarted. Final checks returned HTTP 200 on 8000, 5173 and 5184, `/api/desktop/runtime` identified this nested checkout, and its build ID matched `sourceBuildId`. The final startup log recorded backend readiness at 539ms and document load at 768ms; these timings do not measure provider readiness or interaction latency.

Headless measurements and screenshots are in `.scratch/command-preview`; test/build logs are in `.scratch/commands-*.log`. These are local verification artifacts, not publication assets.

## Limits and outstanding unrelated state

The full Action Parity validator still flags the existing, untouched `components/plugin-workspace.jsx` fingerprint (127 recorded handlers versus 130 in the current dirty tree). Only files and probes belonging to this command/shell change were refreshed; that separate review state was preserved.

No full regression suite, hosted CI, live provider request, signed-in browser session or attended desktop key interaction was exercised. Opening the desktop process and checking its served bundle/runtime are separate evidence from the headless component checks. No installations or Git publication were performed.
