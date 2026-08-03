# 03 — Automations CRUD API

**What to build:** Users and the agent can create, list, edit, pause/resume, delete, run-now, and inspect run history of automations through the real `/api/automations` endpoints, replacing the current mock. The manual form and the agent tool both call these endpoints, so this is the single source of truth for automation management.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] `GET /api/automations` — list automations + recent runs
- [ ] `POST /api/automations` — create (validates schedule through the parser)
- [ ] `PATCH /api/automations/{id}` — edit any field incl. pause/resume
- [ ] `POST /api/automations/{id}/run` — run-now
- [ ] `DELETE /api/automations/{id}` — remove
- [ ] `GET /api/automations/{id}/runs` — run history
- [ ] Mock route replaced; API tests for CRUD + validation errors
