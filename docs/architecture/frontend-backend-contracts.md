# Vellum Frontend/Backend Contract Boundary

Vellum's production frontend is `frontend/ui/Vellum Default Re-designed.html`.
The UI must not call backend endpoints directly from view logic. Backend access
belongs in `frontend/ui/api/*.js`, and backend routes must publish stable,
versioned contracts.

## Contract Discovery

The frontend discovers available backend surfaces through:

```text
GET /api/capabilities
```

The response is versioned with `api_version: "v1"` and `contract_version: 1`.
It declares the canonical frontend entry, supported feature surfaces, endpoint
paths, plugin ownership, and supported chat stream events.

## Integration Rules

- UI components call `window.VellumApi.*` adapter methods, not raw `fetch`.
- Backend route handlers return typed Pydantic contracts or dictionaries built
  from contract modules under `backend/agent/contracts`.
- Plugin-owned features, including Spotify, Hermes skills, and the memory
  orchestrator, are exposed as capabilities rather than hardcoded UI assumptions.
- Breaking response-shape changes require a new contract version.
- Experimental features must be hidden or disabled from capability discovery
  until the backend route and frontend adapter are both ready.

## Adaptive UI contract

Adaptive UI extends the Workspace Layout owner and its existing
`vellum-workspace-layout-v1` device-local record. The App Action context carries
the current layout, adaptive rule state, and active project, agent, and window
identifiers. UI-originated presentation changes count as learning signals only
when the control explicitly sets `adaptive_learning_signal`; responsive layout
changes and other programmatic UI effects do not teach a preference. Submitted
NLP presentation actions can also contribute signals.

`ui.adaptive.rule.*` actions create, list, explain, enable/disable, remove, and
suppress rules. `ui.adaptive.apply` revalidates context and the reversible
presentation allowlist on the backend, returns a normal Workspace Layout
receipt, and offers Undo. The first automatic receipt includes the rule explanation; Undo
suppresses that preference. Rules never authorize privacy, data, plugin, or
external actions. Session-only presentation overrides are not learned or
overridden by automatic rules. Rule state is not a separate backend database or
cloud memory.

Appearance no longer renders the workspace layout or learned-rule editor. The
existing App Actions and chat commands still own these changes. Routine
successful navigation and visibility receipts apply normally without success
toasts, including automatic layout rules during page changes. Errors and
confirmations remain visible; rule explanations remain in their receipts and
the existing chat commands. Device settings accept `background: "next"` and
resolve it against the current device snapshot to another registered background
before producing the usual revision-checked patch.

## Natural settings and response preferences

`settings.device.update` remains the device settings writer. Its revisioned
snapshot includes the current and previous background, saved profile names,
and Personalization. Profile editing, the Custom Instructions dialog and chat
commands all dispatch that action. `settings.device.inspect` exposes actual
device values, including background history; a generic previous-background
follow-up is resolved only when the preceding request concerned backgrounds.

The main model has a directly visible `app_action` tool over the same catalog,
dispatcher, confirmations and receipts. It discovers and inspects typed schemas
before submitting changes. Failed argument validation returns the schema for a
retry. A final settings completion claim is replaced with actual failed or
pending receipt messages if the requested write was not applied. Model-driven
actions emit the same `app.action.requested` and `app.action.receipt` stream
events as parsed commands; nonstream chat responses include `action_receipts`.
Action turns retain both submitted text and assistant results in the chat.

`model.select` accepts a provider. An available configured model is selected for
the originating chat. Otherwise the existing master-thread state records the
pending provider and the receipt opens secure key entry. After the ordinary
credential confirmation and save, the settings service refreshes the canonical
provider registry and resumes that pending selection. The completion patch names
its originating conversation explicitly, including when a different chat is
currently open. Secret values never pass through the model action tool.

Personalization is projected from the submitted device snapshot into a scoped
response context; it is not another persistent preference store. Style, warmth,
enthusiasm, formatting, emojis, custom instructions and profile context reach
main and specialist prompts. Fast answers omit identity/memory context for
general questions. Recording references and automatic web/connector searches
are restricted by the shared tool policy; explicit searches retain their normal
permissions. The Voice toggle gates the existing composer entry. Voice uploads optionally
include typed Personalization for the existing STT/chat/TTS route. Canvas and
Advanced voice remain visibly unavailable in this branch because their editors
or hands-free runtime are separate work; enabling them reports unavailable.

## Required Verification

Run these checks before treating a frontend/backend boundary change as ready:

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_api.py -k capabilities -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```
