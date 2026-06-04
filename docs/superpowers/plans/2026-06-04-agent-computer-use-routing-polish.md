# Agent Computer-Use Routing Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested routing policy and route-advice tool for Vellum computer-use tasks.

**Architecture:** A pure policy module classifies instructions into `browser`, `desktop`, `workspace`, or `coming_soon`. A LangChain tool exposes the policy to the agent, and the system prompt tells Vellum to use the policy for ambiguous automation tasks.

**Tech Stack:** Python, LangChain tools, pytest.

---

### Task 1: Routing Policy

**Files:**
- Create: `backend/agent/computer_use/routing_policy.py`
- Test: `backend/tests/test_computer_use_routing_policy.py`

- [ ] Write failing tests for browser, desktop, workspace, and coming-soon classifications.
- [ ] Run `pytest backend/tests/test_computer_use_routing_policy.py -v` and confirm import failure.
- [ ] Implement the pure classifier with serializable route dictionaries.
- [ ] Run `pytest backend/tests/test_computer_use_routing_policy.py -v` and confirm pass.

### Task 2: Route Tool And Prompt

**Files:**
- Create: `backend/agent/tools/computer_use_route.py`
- Modify: `backend/agent/graph/agent.py`
- Modify: `backend/tests/test_agent_prompt.py`

- [ ] Write failing tests that the route tool is exposed to sync and async agents and the prompt documents the routing priority.
- [ ] Implement `computer_use_route` as a non-mutating LangChain tool.
- [ ] Add it to both agent tool lists.
- [ ] Update the prompt to remove stale installed-app removal language and document native `open_app`/`launch_app` as valid desktop app routes.
- [ ] Run focused prompt/tool tests and confirm pass.

### Task 3: Verification And Publish

**Files:**
- All files touched above.

- [ ] Run focused tests for routing, prompt, and computer-use behavior.
- [ ] Commit the branch.
- [ ] Push `agent-routing-polish` to origin.
