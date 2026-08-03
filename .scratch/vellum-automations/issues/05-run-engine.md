# 05 — Run engine (runner + scheduler wiring)

**What to build:** When the scheduler fires an automation, a full reasoning turn executes with the automation's instructions, model profile, and reasoning mode, and the result lands where the destination says — a fresh conversation in the Scheduled feed, or appended into the pinned existing chat. One run at a time per automation (a fire that overlaps a running run is skipped); failures are recorded in run history with the error surfaced. Runs with the full-access opt-in execute unattended; runs without it do not run unattended.

**Blocked by:** 01, 03, 04

**Status:** ready-for-agent

- [ ] Fired job → run record created → full reasoning turn (same tools/memory as interactive chat)
- [ ] Model profile + reasoning mode applied to the run
- [ ] Destination delivery: standalone feed vs pinned-thread append
- [ ] Full-access permission enforcement (no silent unattended execution without opt-in)
- [ ] max_instances=1 + misfire grace; overlapping fire skipped
- [ ] Failures recorded with error; integration-style tests (pattern of existing scheduler tests)
