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
receipt, and offers Undo. The first automatic receipt explains the rule; Undo
suppresses that preference. Rules never authorize privacy, data, plugin, or
external actions. Session-only presentation overrides are not learned or
overridden by automatic rules. Rule state is not a separate backend database or
cloud memory.

## Required Verification

Run these checks before treating a frontend/backend boundary change as ready:

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_api.py -k capabilities -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```
