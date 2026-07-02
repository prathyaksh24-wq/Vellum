# Routing Settings UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Vellum Configuration UI by reusing `VSelect` for every routing dropdown and making the routing and credential controls responsive and production-ready.

**Architecture:** Keep the existing single-file React preview and routing API boundary. Add routing-specific layout classes, replace only native routing selects with the established `VSelect`, and retain the backend routing contracts without introducing a second component system.

**Tech Stack:** React 19 via Babel preview, Vellum `VSelect`, CSS, FastAPI routing API, Node/esbuild contract checks, pytest, in-app browser QA.

---

### Task 1: Lock the visual and component contract

**Files:**
- Modify: `design/Velllum/uploads/check-default.mjs`
- Test: `design/Velllum/uploads/check-default.mjs`

- [ ] Add assertions for the four routing `VSelect` accessible labels, routing layout classes, and absence of `select.agent-select` in the routing surface.
- [ ] Run `node design/Velllum/uploads/check-default.mjs` and confirm it fails because native routing selects remain.

### Task 2: Standardize routing controls and layout

**Files:**
- Modify: `design/Velllum/uploads/Vellum Default Re-designed.html`

- [ ] Add `.routing-row`, `.routing-control`, `.routing-actions`, and `.credential-add-grid` styles with constrained-width stacking and no horizontal overflow.
- [ ] Replace optimization, fallback model, credential strategy, and credential provider native selects with `VSelect`, using unique `ariaLabel` values.
- [ ] Keep handlers and payload values unchanged so UI-only work cannot alter backend semantics.
- [ ] Run the contract test and confirm it passes.

### Task 3: Verify production behavior

**Files:**
- Verify: `design/Velllum/uploads/Vellum Default Re-designed.html`
- Verify: `design/Velllum/uploads/api/settings.js`
- Verify: `backend/agent/llm/routing/`

- [ ] Run routing API, engine, pool, store, model, runtime, and secret tests.
- [ ] Run frontend tests and production build.
- [ ] Start the local API and Vite servers, then verify the exact `/design-uploads/Vellum%20Default%20Re-designed.html` URL.
- [ ] Exercise Settings → Configuration, open and change a routing dropdown, confirm no horizontal overflow or relevant console errors, and verify galaxy plus Spotify remain present.
- [ ] Review `git diff --check`, stage only intended files, and commit on the current branch.
