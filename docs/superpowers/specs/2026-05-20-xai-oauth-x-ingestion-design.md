---
type: design-spec
topic: xai-oauth-x-ingestion
created: 2026-05-20
status: implemented
supersedes: 2026-05-16-multi-handle-x-quotes-design.md
---

# Direct xAI OAuth X Ingestion

## Summary

The X archive under `Vault/Library/X/<handle>/` now uses direct xAI OAuth
configuration instead of Apify. Vellum calls the xAI Responses API with the
server-side `x_search` tool and normalizes cited X posts into the existing
ingest format.

## Key Behavior

- Authentication comes from `XAI_OAUTH_ACCESS_TOKEN` or `data/xai-oauth.json`.
- `scripts/xai_x_search_client.py` calls `POST /v1/responses` with the
  `x_search` tool and requests strict JSON for one handle/date window.
- Only records with a cited `x.com/<handle>/status/<id>` or
  `twitter.com/<handle>/status/<id>` URL and clear text are ingested.
- Existing filters, text-hash dedup, manifests, notes, and indexes remain in
  place.
- Polling discovers handles from folders under `Vault/Library/X/`; unknown
  folders default to the `original_tweet` filter profile.
- Polling keeps the 6-hour cadence. Backfill uses 7-day windows because
  xAI search returns synthesized/cited results, not a raw dataset.

## Operations

- X ingestion no longer reads `APIFY_API_TOKEN` or the old Apify budget ledger.
- If OAuth is missing or invalid, drivers exit `3` and tell the user to set
  `XAI_OAUTH_ACCESS_TOKEN` or configure `data/xai-oauth.json`.
- Search/parsing failures on a handle are logged and the run continues to the
  next handle; final exit is `2` when any handle failed.

## Tests

- `test_xai_x_search_client.py`: Responses API request construction, JSON
  parsing, citation extraction, uncited/textless rejection, token refresh, auth
  error sanitization.
- `test_x_drivers.py`: polling/backfill do not require `APIFY_API_TOKEN`.
- Existing ingest/filter/dedup tests verify the normalized item shape still
  writes the current vault layout.
