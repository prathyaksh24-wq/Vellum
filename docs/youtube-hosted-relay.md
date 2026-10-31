# Personal YouTube receiver on Cloudflare's free plan

The personal receiver in `services/youtube-relay` replaces the laptop tunnel
when `YOUTUBE_PUSH_RELAY_BASE` is configured. A Worker receives signed YouTube
events; D1 buffers them while the laptop is off. Cloudflare Cron maintains
channel leases independently of Vellum's local scheduler. Vellum's existing
scheduler imports missed events into Knowledge Core and delivers through the
existing AutomationStore. No hosted copy of Vellum's private profile is created.

This package is for one personal installation/owner per deployment. It does not
implement a shared multi-tenant Vellum service. Source and deployment configuration
are reusable by other users in their own Cloudflare accounts.

## Setup

1. Install the pinned development tools in `services/youtube-relay` with
   `pnpm install --frozen-lockfile` (Node 22.13+). `pnpm-workspace.yaml` allows
   only the required esbuild and workerd installation scripts.
2. Run `pnpm exec wrangler login --scopes account:read user:read workers_scripts:write d1:write`.
   Sign into your Cloudflare account and review the requested permissions.
3. Create the D1 database with `pnpm exec wrangler d1 create vellum-youtube-relay`.
   Put its ID into a copy of `wrangler.jsonc` named `wrangler.local.json` (ignored
   by Git). Existing accounts with several databases must select the intended
   personal account explicitly. Do not upgrade the account to a paid plan.
4. Apply the schema using
   `pnpm exec wrangler d1 migrations apply vellum-youtube-relay --remote --config wrangler.local.json`.
5. Generate a 32-byte URL-safe random bearer secret, keep it in the local `.env`
   as `YOUTUBE_PUSH_RELAY_TOKEN`, and use `wrangler secret put VELLUM_RELAY_TOKEN`
   to supply the exact same secret to the Worker. Do not commit or paste it into
   chat, URLs, screenshots or provider dashboards with visible logs. The included
   `scripts/configure-youtube-relay.py` prepares an ignored secret file for
   `wrangler secret bulk` without exposing the value to the terminal.
6. Deploy with `pnpm exec wrangler deploy --config wrangler.local.json`, set the
   returned HTTPS origin as `vars.PUBLIC_ORIGIN` in the local config, and deploy
   again. An empty PUBLIC_ORIGIN prevents renewal; it never infers a callback
   origin from user-supplied request headers. The included `workers.dev` hostname
   avoids purchasing a domain. No tunnel is needed.
7. Run `python scripts/configure-youtube-relay.py --origin https://your-worker.your-subdomain.workers.dev`
   and restart Vellum's backend. The helper changes only the hosted receiver
   origin/token settings; it preserves the old local callback setting for rollback.
8. Keep **YouTube creator uploads** active with its existing unattended permission.
   Open the YouTube connection dialog. The full target list is sent atomically,
   and active counts require Google's verification callback. Initial registration
   is gradual: at most twenty-four requests per minute. 302 eligible channels need
   approximately thirteen successful ticks, with additional time for retries.

## Protocol and ownership

Only channel IDs and per-channel callback tokens/HMAC secrets are uploaded in
the authenticated target manifest. Neither creator names nor Google OAuth
credentials, watch history, searches, conversations, exclusions or scores are
sent to Cloudflare. The host necessarily sees the monitored channel set and the
public upload payloads. Its bearer secret authorizes one owner, not arbitrary
Vellum users. All management and catch-up requests require this secret in an
Authorization header; redirects are disabled. Browser UI calls only the local
backend and never receives the secret.

The Worker exposes callback GET/POST at `/youtube/websub/{opaque-token}`, and
authenticated `/v1/channels` (PUT), `/v1/status` and `/v1/events?after=N` (GET),
and `/v1/ack` (POST, version/epoch/durable local checkpoint).
It has no public chat, account, browser-control or local Vellum API routes.
Provider response bodies and callback credentials are not logged.

Signed callback bodies are durably buffered before HTTP 204. Exact callback
replays reuse a body digest; title updates can create another transport event,
but the existing local account/channel/video identity prevents another ping.
The local canonical parser validates exact channel/video/date/XML structure.
Malformed events are skipped with a bounded content-free warning so one event
cannot prevent later valid uploads from syncing.

Catch-up returns at most twenty events and 1 MiB of raw payload per page. The
local checkpoint advances only after that page is committed to the existing
upload outbox. A partial local write retries the same page safely. A changed
database epoch resets the sequence and reports missing coverage. The host's
retention floor detects laptop downtime beyond the retained window. RSS remains
a bounded recovery path, not a guarantee of complete history.

New relevant uploads still need verified duration strictly over 180 seconds for
the current personal policy. Unknown duration remains pending. Uploads more
than 24 hours old are saved as quiet baseline evidence for recall instead of
creating fresh pings. Private relevance decisions and notification read state
remain canonical and local. A powered-off laptop cannot display notifications.

After committing a page locally, Vellum acknowledges its checkpoint at most once
per five minutes. The host rotates acknowledged events older than 24 hours in
atomic batches of at most 500; larger cleanup backlogs continue at the normal
15-second catch-up cadence. Unacknowledged events remain eligible for seven-day
catch-up, subject to capacity limits. A failed acknowledgment retries without
rewinding the local cursor or blocking delivery. This is a personal single-owner
receiver: do not share it among independent installations with different cursors.
Rotation removes transport copies, not canonical saved uploads or memories.

## Free-plan bounds and failures

- At most 1,000 monitored channels; a larger manifest fails without truncation.
- Callback body at most 256 KiB. Only SHA-1/SHA-256 HMAC signatures are accepted.
- Buffer retains unacknowledged events up to seven days and acknowledged events
  for at least 24 hours, at most 20,000 events and 64 MiB of raw payload.
  Capacity failures return retryable HTTP 503 instead of acknowledging lost data.
- Cron runs once per minute, reserves at most twenty-four hub attempts before network
  I/O, uses a two-minute worker lease, and retries failures with backoff.
- Local event sync normally checks every fifteen seconds, with sixty-second
  failure backoff. Registration/status sync uses the existing thirty-second job;
  unchanged manifests are not uploaded repeatedly. Both share a local sync lease.
- Google duration/subscription metadata uses the existing connector and shared
  persisted budgets. Cloudflare hosting does not create a new Google quota pool.
  The fast worker checks pending uploads only. Unknown duration retries start
  after two minutes and back off to one hour; ordinary RSS checks may enrich
  recent quiet baseline records. Today's usage is never reset during deployment.
- Health reports deferred sync, stale hosted maintenance, quota/capacity gaps and
  malformed event skips. Free-plan provider quotas and outages can still defer
  delivery. No paid subscription or uptime guarantee is created by deployment.
- Retention queries force the existing timestamp index and bound deletion work;
  fresh retained events do not get scanned every minute. Daily read/write usage
  is separate from stored row count. Rotation does not reset an exhausted daily
  allowance and deletions themselves consume writes. Free D1 includes 5 million
  row reads and 100,000 row writes per UTC day; monitor both for the actual channel
  workload. An account-wide limit blocks callbacks until reset, even with free
  storage remaining. Google retries and bounded RSS cannot guarantee complete
  recovery of every upload during a provider outage.
- A hosted outage is visible in status but does not prevent duration checks and
  delivery of uploads already saved locally.

## Stop or roll back

Set `YOUTUBE_PUSH_RELAY_BASE=` and restart the local backend to return to its old
callback origin; the local receiver/tunnel must then be running again. Before
retiring the hosted service, send an authenticated empty channel manifest to
`PUT /v1/channels` so Cron unsubscribes channels. Existing public buffered events
expire after seven days. Rotate the bearer secret or remove the deployment in
your Cloudflare account to revoke its access. Merely pausing local notifications
does not stop an already deployed host from collecting public events.

## Verification

Run `node --test test/worker.test.mjs` in the receiver package, the backend
`test_youtube_relay.py` and `test_youtube_push.py` suites, and the rendered
YouTube connection policy test. Before claiming live availability, verify a
Google subscription challenge, a signed HTTPS event, catch-up with the local
backend stopped, one local notification after reconnect, and duplicate replay.
