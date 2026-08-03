# 06 — Built-in job migration

**What to build:** The five hardcoded background jobs (memory dreaming, nightly digest, vault retention, YouTube intelligence projection, skill curator ticker) become ordinary store records, seeded on first startup, so they appear in the Automations view and can be edited/paused like user automations. They are flagged built-in and protected: deleting one restores its default schedule instead of losing it. The scheduler registers all jobs from the store at startup and re-registers individual jobs on mutation.

**Blocked by:** 01, 03

**Status:** ready-for-agent

- [ ] Idempotent seeding of built-ins into the store on startup
- [ ] Built-ins visible + editable + pausable like user automations
- [ ] Delete on a built-in restores the default schedule (protected from permanent removal)
- [ ] `start_scheduler` re-registers jobs from the store; mutation re-registers only the affected job
- [ ] Tests: seeding idempotency, delete-restore, re-registration on mutation
