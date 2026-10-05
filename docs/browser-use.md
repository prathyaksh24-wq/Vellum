# Browser use

Vellum's main agent delegates interactive website, tab and download tasks to
`BrowserAgent` through the existing AgentCatalog and DelegationRuntime. The
specialist has exclusive permission to the browser capabilities in the shared
ToolRegistry. The main model does not receive raw browser tools.

## Using the browser

Install the backend dependencies and Brave, then restart Vellum. Select an
installed local chat model. Open **Browser** in the sidebar, or ask Vellum to
open a website. The right panel shows the separate browser while chat remains
available beside it. **More** exposes the remaining sidebar destinations.

- Use the address field to enter a website or search Google. Local development
  addresses such as `localhost:5173` use HTTP. Back, Forward, Reload and tab
  controls work alongside the address field.
- **Pause** stops subsequent agent actions; **Resume agent** returns ownership.
  If the task has already yielded, ask Vellum to continue it after resuming.
- **Take over** allows clicks, typing, paste, keypresses and scrolling in the
  live preview. Navigation and tab controls also yield ownership to the user.
- Sign in manually in this dedicated session. Its profile survives closing and
  reopening. Your daily Brave profile and its tabs are separate.
- **Downloads** lists files saved during this backend process. **Show in folder**
  selects a saved file in Windows Explorer. Vellum does not execute downloads.
- **Close session** closes the dedicated browser; hiding the panel leaves it
  running. Expand restores or enlarges the browser view.

The default uses the installed Brave executable, running headlessly behind the
in-app preview. An optional `BROWSER_EXECUTABLE_PATH` can select an installed
Chromium browser such as Chrome or Edge. Other browser engines and daily-profile
attachment are outside this slice. A Chromium override still uses the Brave
label in this initial UI.

Set `PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true` to enable BrowserAgent navigation and
confirmed page interactions, consistent with the existing browser tool gate.
Manual UI controls express the user's direct intent and do not require this
environment flag. No Playwright-managed Chromium download is required when
using an installed browser executable.

## Ownership and privacy

The existing Playwright worker and client own the session, browser lifecycle,
serialization and idle cleanup. On Windows it starts an owned, hidden browser
process with an ephemeral loopback debugging port and attaches only to that
process's application profile. This avoids the persistent-profile download crash
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
`/api/browser/frame` return typed contracts with no-store caching. Readiness is
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

The preview is a JPEG capture of a 1280×800 browser viewport, refreshed roughly
once per second while visible. It contains only the active page, with letterbox
space where needed; it is not a virtual desktop or native browser window. Input
coordinates account for scaling. Stale tab/document inputs are rejected.
Keyboard Tab leaves the preview for accessible app navigation. There is no file
picker/upload bridge, desktop control, audio/video streaming, native browser
menu, password-manager UI, or manual JavaScript-dialog control in this slice.
CAPTCHA, DRM and sites that reject automation remain compatibility checks.

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
