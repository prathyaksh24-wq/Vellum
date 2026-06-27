# Vellum X Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe Vellum agent actions for X search, authenticated account lookup, bookmarks, and posting.

**Architecture:** Keep public search on the existing xAI `x_search` OAuth integration. Add a separate official X API v2 OAuth PKCE setup and client for account actions, then expose both through one gated LangChain tool, `x_action`.

**Tech Stack:** Python 3.14, pytest, httpx, LangChain `@tool`, X API v2 OAuth 2.0 PKCE, xAI Responses API `x_search`.

---

### Task 1: X API OAuth Setup Script

**Files:**
- Create: `scripts/setup_x_api_oauth.py`
- Create: `scripts/setup_x_api_oauth.ps1`
- Modify: `.gitignore`
- Test: `backend/tests/test_setup_x_api_oauth.py`

- [x] **Step 1: Write failing tests**

Tests cover authorize URL construction, token exchange payload, and token file format.

- [x] **Step 2: Verify tests fail**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests\test_setup_x_api_oauth.py -q`
Expected: fails because `scripts/setup_x_api_oauth.py` does not exist.

- [x] **Step 3: Implement setup script**

Create a browser OAuth 2.0 PKCE loopback flow with:
- authorize endpoint `https://x.com/i/oauth2/authorize`
- token endpoint `https://api.x.com/2/oauth2/token`
- callback `http://127.0.0.1:56122/callback`
- scopes `tweet.read users.read tweet.write bookmark.read offline.access`
- token output `data/x-api-oauth.json`

- [x] **Step 4: Add PowerShell wrapper**

Wrapper invokes the venv Python if present.

- [x] **Step 5: Verify**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests\test_setup_x_api_oauth.py -q`
Expected: pass.

### Task 2: X API Client

**Files:**
- Create: `scripts/x_api_client.py`
- Test: `backend/tests/test_x_api_client.py`

- [x] **Step 1: Write failing tests**

Tests cover token loading, refresh with saved client ID, sanitized auth errors,
`GET /2/users/me`, `GET /2/users/:id/bookmarks`, and `POST /2/tweets`.

- [x] **Step 2: Verify tests fail**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests\test_x_api_client.py -q`
Expected: fails because client module does not exist.

- [x] **Step 3: Implement client**

Implement:
- `XApiAuthError`
- `XApiError`
- `get_me(oauth_file=...)`
- `get_bookmarks(user_id, max_results=10, oauth_file=...)`
- `post_tweet(text, oauth_file=...)`

- [x] **Step 4: Verify**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests\test_x_api_client.py -q`
Expected: pass.

### Task 3: Agent Tool

**Files:**
- Create: `backend/agent/tools/x.py`
- Modify: `backend/agent/config.py`
- Modify: `backend/agent/graph/agent.py`
- Test: `backend/tests/test_x_tool.py`
- Test: `backend/tests/test_agent_prompt.py`

- [x] **Step 1: Write failing tests**

Tests cover:
- `search` dispatches to xAI search without write gates.
- `bookmarks` requires `X_TOOL_ALLOW_PRIVATE_READS=true`.
- `post` requires both `confirm=True` and `X_TOOL_ALLOW_POSTS=true`.
- agent tool list includes `x_action`.
- prompt documents the X action safety rules.

- [x] **Step 2: Verify tests fail**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests\test_x_tool.py tests\test_agent_prompt.py -q`
Expected: fails because tool is not registered.

- [x] **Step 3: Implement tool and config gates**

Add settings:
- `x_tool_allow_private_reads: bool = false`
- `x_tool_allow_posts: bool = false`

Expose `x_action(action, query="", text="", tweet_id="", max_results=10, confirm=False)`.

- [x] **Step 4: Wire prompt and agent**

Import and add `x_action` to sync/async tool lists. Update prompt rules.

- [x] **Step 5: Verify**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests\test_x_tool.py tests\test_agent_prompt.py -q`
Expected: pass.

### Task 4: End-to-End Verification

**Files:**
- Existing X tests
- Existing targeted agent tests

- [x] **Step 1: Run X/action suite**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests\test_setup_x_api_oauth.py tests\test_x_api_client.py tests\test_x_tool.py tests\test_setup_xai_oauth.py tests\test_xai_x_search_client.py tests\test_x_drivers.py tests\test_handle_config.py tests\test_x_ingest.py tests\test_filter_profiles.py tests\test_x_dedup.py -q`
Expected: pass.

- [x] **Step 2: Run smoke commands**

Run:
- `.\.venv\Scripts\python.exe scripts\setup_x_api_oauth.py --help`
- `.\.venv\Scripts\python.exe scripts\poll_x.py --dry-run`

Expected: both exit 0.

## Plan Audit

- Spec coverage: all accepted design scope is covered by Tasks 1-4.
- Placeholder scan: no placeholders or deferred implementation steps.
- Type consistency: token file is `data/x-api-oauth.json`; agent tool is
  `x_action`; gates are `x_tool_allow_private_reads` and `x_tool_allow_posts`.
- Edge cases: credential absence, auth rejection, private-read gate, post gate,
  and token refresh are explicitly tested.
- Alternative stress: browser/Hermes approaches remain out of scope; official
  API client requires X developer app credentials by design.
