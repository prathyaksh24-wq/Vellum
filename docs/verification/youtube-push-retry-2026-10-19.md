# Live YouTube push retry, 19 October 2026

Checked approximately 08:24–08:47 IST. The backend was initially stopped; the
normal `scripts/start-api.ps1` restored it. The hosted receiver remained online
and had retained public events. No OS DNS configuration was changed.

Router DNS initially timed out for Google and Cloudflare API hosts. Ordinary
resolution worked on the user's requested retry. A single explicit retry cleared
only failed duration wait timers under the canonical tracking lease; persisted
daily quota counters were retained. The normal delivery worker then performed
real Google duration checks and committed notifications through AutomationStore.

At 08:45 IST there were 14 new unread pings; by the final snapshot there were 19.
Examples include NFL, NotYourAverageFlight and a Premier League rediscovery.
Verified duration receipts included `vf4ksuXiQ1M` (1275 seconds), `q8QhLLocpt8`
(204 seconds), and `AE0-QKwgwBw` (1436 seconds). These were real catch-up records,
not synthetic callbacks inserted for this verification. No physical UI visibility
or new upload published during this check is claimed.

The final host snapshot reported 300 desired and 300 active channel targets,
recent events and maintenance, and no host warnings. The local cursor advanced
to 11457 and synced at 08:47:15 IST. Catch-up was still in progress, with 15677
public events buffered in the host (about 13.9 MB of raw payload). A transient
596-target registration set included rediscovery candidates; after delivery
consumed the weekly rediscovery slot, the normal profile reconciliation returned
to 300 desired targets. These are targets, not a claim of 596 Google subscriptions.

## Rotation correction

Native workerd reproduced `meta.changes=1000` for a 500-event deletion because
the counter trigger also updated state. Returning that value violated the local
ack contract and produced a false rotation-deferred warning. The receiver now
uses DELETE RETURNING IDs to count deleted events. Receiver tests: 12 passed,
including the real workerd/D1 regression. Deployed version:
`54b2736a-70b7-4bdf-b957-b296b8e41636`.

The real endpoint returned HTTP 200 with `pruned:500`, validating the correction
against hosted D1. Event pages additionally accept a bounded `limit` up to 100,
with the old default of 20 and unchanged 1 MiB raw payload cap. The current local
client still uses the default; no client catch-up acceleration is claimed.

Today's D1 analytics snapshot showed 132325 row reads and 57623 row writes.
Reads have headroom after the indexed-cleanup fix, but writes already consume
over half of the daily free allowance. Rotation consumes writes too; continued
free-tier availability under this workload is not guaranteed by this check.

## Remaining boundary

This confirms hosted collection and real duration-gated catch-up delivery with
the backend running. The packaged Electron app still expects an existing backend;
automatic backend startup and a cold desktop reopen test remain unfinished. No
new branch, Git commit, push, or PR was created.
