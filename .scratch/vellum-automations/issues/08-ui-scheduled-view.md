# 08 — UI: Scheduled view + create/edit

**What to build:** The Vellum Default Re-designed frontend gains the Automations surface: a Scheduled view listing automations (name, schedule, destination, status) with recent runs, run-now, pause/resume, edit, and delete; a manual create form covering all fields; edit surfaces with model-tier + reasoning-mode pickers; a prominent full-access opt-in toggle; and the Create button that starts the chat-guided flow.

**Blocked by:** 03, 05, 06, 07

**Status:** ready-for-agent

- [ ] Scheduled view: list + recent runs + run-now / pause / resume / edit / delete
- [ ] Manual create form (instructions, schedule, destination, model profile, permission)
- [ ] Edit surface with VSelect-based model-tier + reasoning-mode pickers
- [ ] Full-access opt-in as deliberate confirmation (toggle + warning copy, never silently on)
- [ ] Create button → chat-guided flow
- [ ] `api/automations.js` client extended to the new endpoints; frontend tests + rendered QA on the design-upload URL
