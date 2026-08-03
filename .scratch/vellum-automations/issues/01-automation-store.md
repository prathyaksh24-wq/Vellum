# 01 — Automation store (JSON job store)

**What to build:** A user-owned, durable automation store so automations and their run history survive restarts. Users can persist an automation with instructions, schedule, destination, model profile, permission profile, and state; the store keeps the last ~100 runs per automation, prunes older ones, and writes atomically so a crash never corrupts it.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] `data/automations.json` store with atomic write (temp file + rename)
- [ ] Record schema: id, name, instructions, schedule, destination, model profile, permission (full-access opt-in), state (active/paused), builtin flag, created/updated timestamps
- [ ] Bounded run history (~100 per automation, oldest pruned)
- [ ] Load/save API with the same conventions as the existing suggestions store
- [ ] Unit tests: atomic read/write, bounded pruning, corrupt-file recovery
