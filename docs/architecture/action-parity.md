# Action Parity verification

Issue #176 inventories the served interface in `frontend/ui/action-parity.inventory.json`.
The inventory separates covered visual controls, non-state exemptions, and
surfaces that still need a canonical App Action. A deferral is not a claim of
parity.

The frontend contract test parses the JSX actually served by the main and
coding workspace HTML pages, including their external React components. It
locks the tag/event/handler-expression multiset for 1,068 reviewed handlers.
An added, removed, or rewired handler fails the test until its Action mapping
or narrow exemption is reviewed and the fingerprint is updated. Covered
controls also have source probes; the backend contract test checks that each
listed Action ID exists in the composed App Action catalog. This is a change
gate, not whole-program proof that every callback reaches a dispatcher. In
particular, source probes do not prove a backend receipt is applied at runtime.

Review rule: when a visual handler changes, classify the control as an App
Action, a non-committing gesture, or a specifically named deferral. Do not
refresh a fingerprint alone to make the test pass. If a deferral acquires an
Action, move it into `covered` and add a behavior test. If a new React script
is served, add it to the scanner first.

## Browser validation (disposable fixture)

The served Vite page was checked against `backend/tests/action_parity_live_server.py`.
That fixture puts conversations, plugin enablement, and automations under a
temporary directory; it uses the real App Action planner/dispatcher, plugin
registry, automation store, and observability action adapter. Its chat answer,
agent selection, observability metrics, and scheduler availability are
synthetic. It never calls a model, launches a coding session, schedules a real
run, or touches a user profile. This is UI-to-contract validation, not a
production end-to-end claim.

To repeat the browser check, start the fixture from `backend/tests` with the
repository's `backend` directory on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = (Resolve-Path ../../backend).Path
python -m uvicorn action_parity_live_server:create_app --factory --host 127.0.0.1 --port 8018
```

In another shell, run `npm --prefix frontend run dev -- --port 5176` from the
repository root. Open
`http://127.0.0.1:5176/design-uploads/Vellum%20Default%20Re-designed.html?backend=http%3A%2F%2F127.0.0.1%3A8018`.
Stop the fixture after validation; its data directory is discarded.

| Area | Verified in the served browser | Limit |
| --- | --- | --- |
| NLP/click parity and mixed turns | “hide the sidebar” matched the click path; “hide the sidebar and tell me a joke” hid it and preserved a conversational reply. | Reply text is a fixture string, not inference. |
| Workspace Layout, persistence, reset, Undo | Sidebar hide/expand, composer size, reload persistence, Reset surfaces, and sidebar Undo worked. Ctrl+Shift+S recovered the sidebar while hidden. | Kernel protection for all eight combinations of optional surface visibility is asserted in the backend contract test. |
| Conversations | Open, pin and reload, cancel a delete confirmation, and fork a chat worked. | Message-level fork was not exercised with a persisted message; native new-window correctly reported that desktop support is required. |
| Attachments | Composer Add opened the file/recents picker. | No file was uploaded in the browser; attachment preparation/dispatch is covered by backend tests. |
| Plugins | A temporary plugin was disabled and re-enabled through `plugin.state.set`, with the card and receipt updating. | External connectors and OAuth were not exercised. |
| Observability | The empty fixture snapshot rendered; Live/Pause/Resume/Refresh changed state through App Actions. | No real model run or usage ledger was present. |
| Automations | Created a temporary task, paused it, read empty history, and confirmed its paused state after reload. | No actual scheduler or model run was started. |
| Agents | The fixture Books specialist appeared and selection returned a receipt. | Specialist inference and local profile settings were not exercised. |
| Pets | Show pet switched on/off with receipts. | Gallery installation was not exercised. |
| Adaptive UI | Rule controls and settings rendered; layout learning/Undo paths are covered by focused tests. | No learned rule existed in the fixture to click through. |
| GitHub PRs | Coding workspace showed Pull requests disabled with “Open a coding session first” while its backend was offline. | No GitHub PR was opened or created in the browser. The create-PR visual control is deferred. |

The full frontend test suite and production build are required. The selected
backend regression set includes App Actions, conversations, adaptive UI,
attachments, knowledge sources, automations, lifecycle, observability, Pets,
coding GitHub, plugin contributions, privacy, memory, and chat streaming.
Run the complete backend suite in CI; the local full backend suite was skipped
at the user's request.
