# Vellum Skill API, CLI, Slash, and UI Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mock skill surfaces with one persisted management service shared by FastAPI, CLI/slash commands, and the existing Skills UI.

**Architecture:** `SkillSurfaceService` composes registry, manager, usage, bundles, hub, and curator into typed catalog/action responses. API routes and CLI commands delegate to it. Slash expansion turns `/learn` and direct skill/bundle commands into normal agent turns; management commands return locally without model use. The UI refreshes server state after every mutation.

**Tech Stack:** Python 3.11+, FastAPI, Rich CLI, existing standalone React-in-HTML UI, pytest.

---

## Tasks

1. Add proposed approval and active retirement moves to `SkillManager`; test full package preservation and state updates.
2. Implement `SkillSurfaceService.catalog/detail/action` with active/proposed/retired/archived cards, usage/provenance/security fields, bundles, hub installs, suggestions, and curator status.
3. Replace mock `GET /api/skills`; add detail, action, learn, bundle, hub, and curator endpoints with HTTP error mapping.
4. Add CLI `/skills`, `/curator`, `/learn`, direct `/<skill>`, and bundle expansion using the same service.
5. Extend `frontend/ui/api/plugins.js` and `vellum-default.html` so approve/retire are persisted and catalog refreshes after mutation; show Archived and Curator status.
6. Mirror changes into the active design upload only if it is byte-identical to the maintained UI source before editing; otherwise keep the canonical frontend target only.
7. Run service/API/CLI tests and targeted UI contract checks.

## Safety

- API never returns absolute package paths or secret values.
- Mutation endpoints require explicit `confirm: true`.
- `/learn` uses the privacy-gated agent sourcing workflow.
- UI optimistic state is replaced by server refresh; failed mutations display an error instead of silently diverging.

