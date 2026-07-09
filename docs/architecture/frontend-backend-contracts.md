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

## Required Verification

Run these checks before treating a frontend/backend boundary change as ready:

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_api.py -k capabilities -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```
