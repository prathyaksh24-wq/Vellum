---
type: design-spec
topic: vellum-x-actions
created: 2026-05-20
status: accepted-for-implementation
sources:
  - https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code
  - https://docs.x.com/fundamentals/authentication/guides/v2-authentication-mapping
  - https://docs.x.com/x-api/posts/manage-tweets/integrate
  - https://docs.x.com/x-api/users/get-bookmarks
  - https://docs.x.ai/developers/tools/x-search
---

# Vellum X Actions

## Brainstorm Summary

Vellum already has xAI OAuth for Grok-powered public X Search and scheduled
archive ingestion. The new request is broader: let the Vellum agent perform X
account actions such as posting, reading bookmarks, and searching X.

Three approaches were considered:

1. Browser automation against `x.com`.
   - Pros: resembles a human session and can cover many UI actions.
   - Cons: fragile selectors, account-risky, hard to audit, and conflicts with
     Vellum's existing browser safety rules that block sending messages.
2. Hermes/X plugin delegation.
   - Pros: faster if a maintained plugin exposes every desired action.
   - Cons: reintroduces a CLI dependency the user previously rejected, and
     makes safety/audit boundaries harder to own inside Vellum.
3. Direct Vellum-owned API clients.
   - Pros: explicit OAuth scopes, testable endpoints, stable tool surface, and
     clear write gates.
   - Cons: X write/bookmark endpoints require an X developer app and OAuth 2.0
     user token; xAI OAuth alone is not enough.

Chosen design: direct Vellum-owned clients. Public search uses the existing
xAI `x_search` integration. Account actions use X API v2 OAuth 2.0 PKCE and a
separate local token store.

## Scope

This implementation provides a safe first slice:

- `x_action(action="search", query=..., max_results=...)` uses xAI X Search.
- `x_action(action="me")` verifies X API OAuth and returns the authenticated
  account.
- `x_action(action="bookmarks", max_results=...)` reads the authenticated
  account's bookmarks.
- `x_action(action="post", text=..., confirm=True)` posts a tweet, but only
  when `X_TOOL_ALLOW_POSTS=true` is also configured.

Out of scope for this slice: media uploads, DMs, likes, follows, deleting
tweets, retweets, quote tweets, timelines, and browser-control fallback.

## Architecture

Add a small X API OAuth setup script:

- `scripts/setup_x_api_oauth.py` opens a browser against X OAuth 2.0 PKCE.
- It requires `X_API_CLIENT_ID` in `.env`; optional `X_API_CLIENT_SECRET` is
  supported for confidential clients.
- It requests `tweet.read users.read tweet.write bookmark.read offline.access`.
- It writes `data/x-api-oauth.json`.

Add an API client module:

- `scripts/x_api_client.py` loads and refreshes `data/x-api-oauth.json`.
- It implements `get_me`, `get_bookmarks`, and `post_tweet`.
- It returns sanitized errors and never logs token contents.

Add an agent tool:

- `backend/agent/tools/x.py` exposes one LangChain tool, `x_action`.
- Reads are split by privacy:
  - `search` is public and uses xAI search.
  - `me` and `bookmarks` require `X_TOOL_ALLOW_PRIVATE_READS=true`.
- Posting requires both `confirm=True` and `X_TOOL_ALLOW_POSTS=true`.
- The tool returns compact JSON strings suitable for agent responses.

Wire the tool into `backend/agent/graph/agent.py` and update the prompt with
strict use rules.

## Failure Modes

- Missing xAI OAuth: search returns a setup instruction for
  `scripts/setup_xai_oauth.ps1`.
- Missing X API OAuth: account actions return a setup instruction for
  `X_API_CLIENT_ID` plus `scripts/setup_x_api_oauth.ps1`.
- Missing X developer app: setup cannot complete; this is expected because
  official X API v2 account actions require developer-app credentials.
- Missing read gate: `me`/`bookmarks` return `X_TOOL_ALLOW_PRIVATE_READS=true`
  requirement.
- Missing post gate: `post` returns `X_TOOL_ALLOW_POSTS=true` and
  `confirm=True` requirement.
- 401/403 from X API: return sanitized OAuth/access-level guidance without
  token data.
- Rate limits: return HTTP 429 and a short retry-oriented message.

## Brainstorm Audit

1. Assumption-check: xAI OAuth does not imply X API write/bookmark access.
   Resolved by separating `data/xai-oauth.json` and `data/x-api-oauth.json`.
2. Architecture stress: missing credentials, missing gates, 401/403, 429, and
   absent bookmark data all return controlled messages.
3. Alternative dismissal: browser and Hermes approaches were rejected on
   reliability, safety, and ownership grounds, not by default.
4. Requirement gap: user wants "and more"; accepted risk. This slice provides a
   stable extension point instead of pretending to implement all X actions.
5. Composability claim: search and account actions compose through one
   `x_action` tool but separate clients and token stores.
6. Scope honesty: media/DM/follow/like are explicitly out of scope.
7. API surface drift: user-facing tool has generic `action` plus stable
   parameters; endpoint-specific churn remains inside clients.
8. Failure mode map: all primary credential/gate/API failures are enumerated.
9. YAGNI sweep: only search, me, bookmarks, and post are included.

No unresolved design findings remain; the accepted risk is that X API account
actions require a developer app, which may not be available on the user's
current account.
