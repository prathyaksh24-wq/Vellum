# 04 — Reasoning mode control (core agent)

**What to build:** The reasoning (ChatGPT-style chat) agent and its sub-agents gain a Codex-style reasoning-mode control — `light` / `medium` / `high` / `extra high` / `max` / `ultra` — that adjusts inference effort on each turn. Interactive chat turns can use it directly, and automations will set it via their model profile. The coding mode is untouched.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] Reasoning-mode enum/values (light → ultra) on the reasoning agent path
- [ ] Mapped into the provider call (effort/token-budget parameters) for interactive turns
- [ ] Sub-agents inherit or override the mode
- [ ] Coding mode behavior verified unchanged
- [ ] Tests: default = standard; explicit mode flows into provider call; sub-agent wiring
