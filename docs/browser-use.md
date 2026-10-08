# Browser use

Vellum's main agent delegates interactive website, tab and download tasks to
`BrowserAgent` through the existing AgentCatalog and DelegationRuntime. The
specialist has exclusive permission to the browser capabilities in the shared
ToolRegistry. The main model does not receive raw browser tools.

## Using the browser

YouTube Agent has a **Refresh history** control in its overview and chat. After
signing into YouTube in this browser, the control and watch-history questions
read a bounded recent page snapshot through this same browser owner. General
browser tools remain exclusive to BrowserAgent; the YouTube capability accepts
no arbitrary URL or script. The local Knowledge Core snapshot is scoped to a
hashed browser-account identity, with sign-out and account-switch checks. Google
OAuth likes/subscriptions and Takeout archives use their separate account sources.
History reads use a temporary background tab and close it afterward, preserving
the visible page and panel state. A background-only session does not request
that the UI open the browser panel; explicitly opening Browser still does.

Install the backend dependencies and Brave, then restart Vellum. Select an
installed local chat model. Open **Browser** in the sidebar, or ask Vellum to
open a website. The right panel shows the separate browser while chat remains
available beside it. **More** exposes the remaining sidebar destinations.

- Opening a blank session and creating a tab shows Vellum's local homepage.
  Existing websites remain open when you reopen the panel. Exact names such as
  `google`, `youtube`, `reddit`, `wikipedia`, `spotify`, `x` and `twitter` open
  their websites directly; other search phrases use the selected engine. Full website
  addresses open directly too. This removes the search detour when opening those
  sites, but Google and destination sites can still require a human check.
- Use the address field to enter a website or search with the selected engine. Local development
  addresses such as `localhost:5173` use HTTP. Back, Forward, Reload and tab
  controls work alongside the address field.
- The picker beside the homepage title offers Google, Brave, DuckDuckGo,
  Startpage and SearXNG. Each has its own approved wallpaper and control palette;
  choosing a search engine does not change the dedicated Brave runtime. The
  native homepage uses local DOM controls and stops frame streaming while visible.
- SearXNG requires the URL of an instance you run or trust. Use **SearXNG instance**
  in the picker to change it. Search URLs are constructed locally; this feature
  uses ordinary search websites, not paid search APIs.
- **Add shortcut** saves a named website; a shortcut's remove control appears on
  hover or keyboard focus. The existing browser owner stores preferences in
  `data/browser-session/preferences.json`; reads and writes use the typed
  `browser.session.control` App Action with operation `preferences`. These local
  preferences survive closing the session and are excluded from Git.
- **Home** returns to the local homepage. **Expand browser** fills the workspace
  and **Restore split view** restores chat without remounting the browser. The
  browser menu contains session information and **Close session**. Escape stays
  inside browser input; it does not hide the panel. Page/video fullscreen remains
  separate from workspace expansion. Whole-Vellum themes are deferred.
- **Pause** stops subsequent agent actions; **Resume agent** returns ownership.
  If the task has already yielded, ask Vellum to continue it after resuming.
- Clicking the page takes control and forwards that click after checking that
  the displayed document is still current. **Take over** also allows typing,
  paste, keypresses and scrolling. Navigation and tab controls yield ownership
  to the user. **Resume agent** returns control when you finish.
- Sign in manually in this dedicated session. Its profile survives closing and
  reopening. Your daily Brave profile and its tabs are separate.
- **Downloads** lists files saved during this backend process. **Show in folder**
  selects a saved file in Windows Explorer. Vellum does not execute downloads.
- **Close session** closes the dedicated browser; hiding the panel leaves it
  running. Expand restores or enlarges the browser view.

The default uses the installed Brave executable. On Windows it uses Brave's
normal renderer with its owned native windows hidden behind the in-app preview;
other platforms currently run headlessly. An optional `BROWSER_EXECUTABLE_PATH` can select an installed
Chromium browser such as Chrome or Edge. Other browser engines and daily-profile
attachment are outside this slice. A Chromium override still uses the Brave
label in this initial UI.

On Windows the dedicated browser is assigned to a backend-owned job with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Normal close saves the browser session
before releasing that handle. If the backend is killed, Windows terminates the
owned browser so its profile does not remain locked. Daily Brave processes are
not assigned to this job. Pre-existing orphaned sessions from older backend
versions require a one-time close before relaunch; Vellum does not discover or
automatically attach to unknown running browsers.

Set `PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true` to enable BrowserAgent navigation and
confirmed page interactions, consistent with the existing browser tool gate.
Manual UI controls express the user's direct intent and do not require this
environment flag. No Playwright-managed Chromium download is required when
using an installed browser executable.

## If websites will not open

- Start the backend and UI with `scripts/start.ps1` from the repository root.
  A previously loaded Vellum page can remain visible after its servers stop;
  the in-app browser needs the backend process to open and navigate websites.
  Reload Vellum after the servers are ready.
- Enter a website address such as `google.com` or `https://www.youtube.com` in
  the browser address field and press Enter. Check the panel's error message if
  navigation fails.
- Address-bar navigation and manual input give you control. If chat says the
  browser is paused or you have control, click **Resume agent**, then ask Vellum
  to open the website again. Resuming does not rerun a task that already returned
  a blocked response.
- For chat tasks, select an installed local model and enable
  `PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true` in the local configuration before
  starting the backend. Manual address-bar navigation does not need that flag.

## Ownership and privacy

The existing Playwright worker and client own the session, browser lifecycle,
serialization and idle cleanup. On Windows it starts an owned, hidden browser
process with an ephemeral loopback debugging port. It connects to the exact
websocket announced by that child's private stderr pipe, rather than discovering
another browser on a chosen port. Only windows belonging to that owned process
are hidden. Closing the final tab retains a blank replacement so native Brave
does not exit underneath the panel. This avoids the persistent-profile download crash
on the branded Chromium pipe transport reported in
[Playwright #42506](https://github.com/microsoft/playwright/issues/42506).
It closes that owned process on session close or backend shutdown. Other
platforms use Playwright's persistent-context pipe transport.
This is a transport extension, not a second
agent runtime. Existing Playwright MCP callers retain their legacy path until
the dedicated session is explicitly opened; subsequent browser tools use that
session. Raw evaluation/CDP is unavailable in the dedicated transport.

BrowserAgent uses the currently selected local Ollama chat model through the
canonical routed model adapter. A cloud-selected model is rejected before page
text is sent for planning. Local routing excludes cloud fallbacks. Requests
contain only the delegated goal, bounded user-provided context, current page
observation and bounded step history; they do not copy the parent conversation.
The specialist returns its result through the existing delegation visibility
and disclosure rules.

Page content is untrusted evidence. Agent clicks, typing and keypresses produce
a pending action in the existing confirmation store. Execution requires that
stored action, current agent ownership, its snapshot identity and unchanged
page observation. Navigation, tabs, scroll and close are bounded tools. Login,
passwords, CAPTCHA, uploads, purchases, messaging, deletion and account changes
are instructed to use manual takeover. This instruction is a model boundary,
not a website transaction classifier.

Manual controls dispatch the typed `browser.session.control` App Action through
`VellumApi.browser`; NLP-originated controls are rejected and must delegate.
Receipts include operation/session metadata rather than input text, page text,
URLs, screenshots or cookies. Read-only `/api/browser/status` and
`/api/browser/frame` return typed contracts with no-store caching. The read-only
`/api/browser/stream` WebSocket publishes changed JPEG frames to loopback web
origins; it accepts no browser input. All mutations retain the App Action path.
Readiness is
reported by browser status under the `/api/capabilities` feature contract.
Panel placement uses the existing Workspace Layout right-panel owner. The
debugging endpoint is local and ephemeral; software running as the same local
user can access it while the session is open. It is never a discovered endpoint
of the user's daily browser.

Local private data is stored in gitignored application directories:

| Data | Directory |
| --- | --- |
| Dedicated profile and sign-in state | `data/browser-session/profile` |
| Saved downloads, under unique IDs | `data/browser-downloads` |
| Explicit screenshot tool output | Configured browser cache directory |

## Limits and validation

The preview uses Brave's live JPEG frame feed. Its viewport follows the panel
size, bounded to 1920×1080; it reflows the website rather than centering a fixed
1280×800 image. A read-only WebSocket delivers changed frames while visible,
with HTTP frames as a fallback when sockets are unavailable. Rapid text and
wheel events are ordered and batched, without a status read for each event.
It contains the active page and remains a streamed browser view rather than
a native browser window. Input coordinates account for scaling, and stale
tab/document inputs are rejected.
Keyboard Tab leaves the preview for accessible app navigation. There is no file
picker/upload bridge, desktop control, streamed audio transport, native browser
menu, password-manager UI, or manual JavaScript-dialog control in this slice.
CAPTCHA, DRM and sites that reject automation remain compatibility checks.
Windows YouTube playback and captions passed a 95-second public-video check
with this normal-renderer launch; longer playback and other videos remain live
compatibility checks. Browser audio, when enabled, comes from the local Brave
process rather than the JPEG stream.

Escape in the page exits the remote document's fullscreen and is contained
inside the browser panel. New tabs focus an empty address bar immediately and
show the local homepage without a network load. Explicit website tabs load
independently. Loading state/errors are additive fields on the existing tab
contract; navigation or closing a tab cancels its pending load.
Status and preview reads skip browser awaits on these loading documents.
Background navigation does not stale the visible page's clicks; child-frame
navigation invalidates agent confirmations while retaining the live feed.

Use Alt+L to focus/select the address, Alt+T for a new tab, Alt+W to close the
active dedicated tab, Alt+1–8/9 to select a tab/the last tab, Alt+Left/Right for
history, and Alt+R or F5 to reload. Shortcuts apply while focus is inside the
panel. Standard Ctrl/Meta shortcuts are also handled if the host delivers the
key event. A regular Brave tab reserves shortcuts such as Ctrl+W/L/T before a
webpage receives them; reliable interception requires a desktop browser surface.
Sources selects the existing Activity drawer without closing the dedicated
session. Reopening Browser restores its session.

BrowserAgent is bounded to 12 decisions and a 180-second planning loop, with
45-second model-call deadlines. It yields on pause or takeover and does not
cache/replay browser side effects. Pause waits for an already-running serialized
browser operation to finish; it is not cancellation of an in-flight network
request. Downloads persist on disk after close/restart; their UI metadata list
is process-local. Closing during a download can cancel it.

Focused checks cover browser permissions, local disclosure, delegation context,
App Action receipts, takeover races and stale confirmations. Opt-in real Brave
tests use temporary profiles and localhost fixtures:

```powershell
$env:PYTHONPATH = 'backend'
$env:VELLUM_BROWSER_SMOKE = '1'
$env:PLAYWRIGHT_MCP_ALLOW_MUTATIONS = 'true'
python -m pytest -q backend/tests/test_browser_agent.py backend/tests/test_browser_session_live.py backend/tests/test_mcp_tools.py

$env:VELLUM_BROWSER_PLANNER_SMOKE = '1'
python -m pytest -q -s backend/tests/test_browser_planner_live.py
```

The UI smoke runs `backend/tests/browser_live_server.py` on localhost:8020 with
an explicit disposable `BROWSER_QA_ROOT`, and Vite on localhost:5180. It uses the
real adapters/actions and installed Brave without loading the user's backend,
conversations or daily browser profile. Set `PLAYWRIGHT_MODULE_PATH` to a Node
Playwright module and `BROWSER_EXECUTABLE` to Brave, then run
`frontend/scripts/browser-session-smoke.mjs`. It checks More, scaled manual
input, pause/resume, tabs, downloads, close/reopen and desktop/mobile layouts.

See [verification](verification/browser-use.md) for results and remaining gates.
