# YouTube receiver quota, rotation and adaptive notifications

Observed on 18 October 2026, IST. No Git publication performed.

## Incident evidence

The personal receiver's D1 REST metadata reported 9,732,096 bytes stored.
Today's GraphQL analytics reported 5,253,301 row reads and 39,029 row writes.
The D1 query endpoint rejected queries with code 7500, explicitly naming the
free-tier daily row-read limit. This was an exhausted usage allowance, not a
full database. The existing 24-hour query-insights window attributed 5,515,995
row reads to the retention-floor MAX(id) update across 1,382 invocations.
The query preferred the rowid index and scanned fresh events when no rows had
expired. Final deployed version: ee616527-3eec-4575-88d5-b49e2f8ab7f0.

The local duration budget was dated 2026-10-18 with 37 of 200 units consumed;
metadata checks were recorded after the 05:30 reset. Existing local notification
receipts included Nightcap at 17:36 IST. These receipts prove storage of some
notifications, not that the user saw a ping or that WebSub delivery was timely.
The local receiver cursor's last successful hosted sync was 17:00 IST.

## Changes

- Force the existing retention timestamp index. Bound each atomic floor/deletion
  batch to 500 events. No database recreation or new migration is needed.
- Acknowledge only a durably committed local checkpoint, including database epoch
  checks. Rotate acknowledged cloud events older than 24 hours; unacknowledged
  events retain up to seven days subject to the existing 20,000-event/64 MiB cap.
  Cleanup is periodic, so these are retention thresholds, not exact deletion times.
- Preserve ingestion progress if an acknowledgment fails. A cloud outage no longer
  prevents processing already-local uploads. Expose a sanitized daily database
  limit code and warning instead of echoing provider errors or credentials.
- Persist direct, eligible channel notification feedback in existing local
  Knowledge Core cursors. Reduced frequency permits at most one qualifying ping
  per rolling 24 hours; mute is separate. Notification-volume language does not
  exclude an entire interest topic. Existing watch/search/seasonal relevance
  remains in use. Conversational recognition is bounded and phrase based.
- Optional rediscovery requires ten saved video/day records and 90 days without
  a saved watch. Permit one ping per rolling seven days overall and avoid the
  same creator for 90 days. Explicit exclusions, former relationships, muted
  channels, topic filtering, >180-second duration, freshness and dedup gates apply.
- Preserve creator lifetime aggregates when recent activity fades. Notification
  history remains capped at 200 per task; upload detail retains its existing
  90-day policy. This does not promise indefinite retention of every upload.

## Verification

- Before the fix, native workerd/D1 maintenance over 10,000 fresh events scanned
  10,008 rows. The same regression now passes with fewer than 100 rows read.
- Receiver suite: 12 passed, including native workerd crypto/D1, indexed retention,
  acknowledgment boundaries, retries, capacity, authentication and error redaction.
- Affected backend suites plus API suite: 209 passed, one existing Starlette/AnyIO
  deprecation warning. This includes the twenty-year history aggregate fixture.
- Additional two-creator rediscovery regression: 1 passed, confirming the global
  weekly cap and excluding former/muted creators after cooldown expiry.
- Affected rendered frontend/notification adapter suites: 23 passed in three files.
- Python compile and scoped whitespace checks passed. No frontend source changed;
  no new full production build or manual visual test is claimed.
- Local profile enabled rediscovery and conversation preferences and set ChessBase
  India to reduced frequency. Account linkage and other settings were preserved;
  the normal backend startup script restarted successfully.

## Live boundary

The deployed receiver returns HTTP 503 with `daily_database_limit`, confirming
the sanitized error path against the real provider condition. D1 remains blocked
until its next daily reset: 19 October 2026 at 05:30 IST (00:00 UTC). The fix cannot
reset that account-wide counter. No paid plan, replacement database, or quota
bypass was used. Live post-reset callback, rotation and fresh notification
delivery remain unverified. Google retries and bounded RSS do not guarantee that
every upload during the outage will be recovered. Rotation also consumes row
writes; future workloads remain subject to both free daily usage limits.
