# YouTube push delivery verification — 16 October 2026

## Implemented scope

The separate WebSub ingress app exposes callback GET/POST only. It verifies
subscription/topic/lease intent and HMAC signatures, bounds streamed XML, and
commits accepted uploads to Knowledge Core's existing outbox before HTTP 204.
Schema 16 adds durable subscription state; credentials are absent from the
typed status API. No separate upload database or notification writer exists.

The existing backend scheduler runs renewal and delivery independently. Push
includes eligible saved subscriptions beyond the RSS capacity, refreshes the
subscription snapshot through the existing OAuth ingestion owner, validates
duration with shared persisted quotas, and rechecks exclusions before delivery.
RSS rotates over push channels for recovery. Quiet uploads remain available
for saved-upload answers. Successful push batches use AutomationStore's run
receipts and notification destination, without creating chats.

The notification API emits revision-only change events. The frontend adapter
owns EventSource lifetime; the existing inbox refreshes on changes, with polling,
visibility recovery, duplicate suppression and browser quiet mode preserved.

## Checks run

- Initial focused tests failed on the absent push module before implementation.
  The first Windows attempt also exposed the sandbox's blocked asyncio socket
  pair. Subsequent HTTP/client tests ran outside that sandbox with a writable
  repository-local temporary directory.
- Broad affected backend suites: **424 passed, 2 skipped**. This includes all
  YouTube tests, notification and automation APIs, built-ins and scheduler,
  digest, Knowledge Core/backup and Book discovery migration tests. The skipped
  browser tests are opt-in, not failed provider verifications.
- Final transport/notification/shared-tracker checks after refinements:
  **67 passed**. Coverage includes signed callbacks, 131 channel targets beyond
  profile capacity, account isolation, lease renewal, changed callback origin,
  durable replay, title edits, duration thresholds/retries/quota, malformed
  signatures/XML, delivery failure, expired worker leases, paused/unattended
  policy, canonical notifications and batch receipts, subscription sync scope,
  redacted status, and an exclusion changed during a metadata request.
- Backend capability discovery: **1 passed, 94 deselected**.
- Full frontend suite: **430 passed across 44 files**. Final focused notification
  and rendered push-status tests: **23 passed**; final status/action-parity checks:
  **11 passed**. These counts overlap and should not be summed.
- Production Vite build passed, retaining the existing classic-script warnings.
- PowerShell launcher parsed successfully and started the real callback app on
  isolated loopback port 8767 using a temporary Knowledge Core database. HTTP
  requests to `/docs`, `/openapi.json`, `/api/automations`, and an invalid callback
  returned 404. A second smoke test verified `-Restart` replaces the verified
  receiver and preserves route isolation. The exact QA processes were identified
  and stopped afterward.
- Scoped `git diff --check` passed. No new dependency was introduced.

The broad run exposed hard-coded schema-15 expectations; migration tests now
compare with the current schema constant. Its old YouTube history fake also
needed the existing browser preference contract. No production browser behavior
was changed for that fixture repair.

## Live activation and frontend test

The user subsequently authorized HTTPS setup and frontend verification. The
official Windows cloudflared 2026.10.1 binary was downloaded and its SHA-256
checked against the release asset digest. A Quick Tunnel exposes only the
callback receiver on loopback port 8001. The local `.env` was updated and the
receiver and main backend restarted; the frontend remains on port 5173.
Private API paths returned 404 through the public origin.

The connected read-only Google account's 289 subscriptions were imported using
the frontend's **Sync subscriptions** control. The existing combined `primary`
history profile was explicitly linked to that verified subscription account,
without moving its history or upload receipts. This revealed and fixed missing
subscription-source preservation during routine policy updates. The live daily
duration budget was raised from 96 to 200; prior usage was preserved.

Google's actual hub verification callbacks activated subscriptions. The first
temporary tunnel later became unavailable with `Tunnel not found` and its DNS
name disappeared. It was replaced, both services reconfigured, and Google
verified the replacement. Registration across the 309 eligible channels is
bounded and gradual; pending channels must not be presented as fully covered.
Status now retains the full desired count during an origin change. The open
connection dialog refreshes status every ten seconds.

For an end-to-end test independent of a creator's next upload time, a real,
previously unseen ChessBase India video (`dMY8x9ja_Co`, published
2026-10-16T11:07:31Z) was selected using the live Google metadata client and
normal persisted quota reservations. A **controlled signed replay** of that
public event was posted through the replacement HTTPS tunnel at 11:56:37Z.
It returned HTTP 204 and persisted `push_queued` before the response. This was
an operator-generated replay, not a Google-originated upload notification.

A stale ten-minute worker lease following the setup restart delayed processing.
Lease recovery and restart resumed the normal scheduler. A final restart to
load the status correction verified the API process, stopped it, confirmed port
8000 offline, and released its remaining leases before starting the backend.
No upload, date, duration, or notification was inserted or
changed to force a pass. The worker's live duration lookup recorded 1,076 seconds
and the canonical outbox became `delivered`. The existing AutomationStore
recorded one completed push batch and notification
`youtube-upload-4a5a9ce8ed069dcf90f95efc` at 11:59:24Z.

The open frontend inbox updated from five to six unread notifications and showed
the video without a reload. Its local `/notifications/events` stream returned
200. Replaying the identical callback at 12:00:08Z returned 204 again; the
notification count stayed six, with exactly one matching durable receipt and
the same delivered outbox identity. The screenshot is saved in
`youtube-push-live-2026-10-16/notification.jpg` (local development capture; omitted from this PR).
This verifies the real tunnel, receiver, scheduler, duration provider, durable
notification path, frontend updates, and deduplication. It does not establish
an uninterrupted long-session latency guarantee or prove a Google-originated
upload event arrived during this test.

Activation regression checks: **60 backend tests passed** after subscription
account-link changes. The rendered connection-dialog test passed after adding
ten-second status refresh. The final push transport suite, including the origin
rotation count regression, passed **21 tests** (one existing Starlette/AnyIO
deprecation warning). Counts overlap the earlier suites.

Final frontend/API check: backend health returned 200; the dialog updated from
33 to **39 active of 309 desired**, with **270 pending** and two uploads awaiting
duration verification. This is a point-in-time activation count, not full-list
coverage. The dialog screenshot is saved in
`youtube-push-live-2026-10-16/push-status.jpg` (local development capture; omitted from this PR).
The public `/api/automations` and `/docs` paths still returned 404.

## Live boundaries

The Quick Tunnel is temporary and has no uptime guarantee; the live failure
above demonstrates that boundary. No stable domain, named tunnel, hosted relay,
Windows service, or Git publication was created. The processes remain running
for testing, but do not automatically start after Windows reboots.

The local receiver requires the PC, receiver, backend and tunnel to be running.
It cannot retain remote events while powered off. RSS is a bounded recent window,
not guaranteed full recovery. Duration quotas and provider metadata availability
can defer otherwise valid uploads. Windows notifications and a shared hosted
multi-user collector remain outside this implementation.

Setup: [YouTube push delivery and HTTPS](../youtube-push-delivery.md).
