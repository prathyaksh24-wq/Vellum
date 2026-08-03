# 02 — Schedule parsing (4 formats)

**What to build:** Users can describe when an automation runs in four natural formats — a relative delay (`30m`), an interval (`every 2h`), a 5-field cron expression (`0 9 * * *`), or an ISO timestamp — and get a canonical schedule record the scheduler understands. Garbage input is rejected with a clear error the UI and agent tool can surface.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] Add `croniter` dependency
- [ ] Parser accepts relative / interval / cron / ISO formats → canonical record
- [ ] Unknown or malformed formats rejected with clear error message
- [ ] Unit tests: all four formats, edge cases (durations, time-of-day intervals), rejection of garbage
