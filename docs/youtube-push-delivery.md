# YouTube push delivery and HTTPS setup

Vellum supports YouTube WebSub callbacks through a dedicated receiver. Knowledge
Core owns durable subscriptions and the existing upload outbox. AutomationStore
owns notifications and read state. No hosted relay, domain, tunnel, Windows
service, or operating-system notification permission is provisioned automatically.

For collection while the laptop is off, use the optional personal
[Cloudflare Workers/D1 receiver](youtube-hosted-relay.md). It has a persistent
HTTPS address, hosted lease renewal and authenticated seven-day catch-up. The
local backend still owns duration checks, relevance and notification delivery.
The tunnel instructions below describe local receiver mode.

## What must be running

- Vellum backend: subscription maintenance, duration validation, delivery, and RSS recovery.
- Callback receiver: accepts signed public YouTube upload metadata into Knowledge Core.
- HTTPS tunnel: routes YouTube callbacks to the receiver on loopback.

The receiver mounts only `GET` and `POST /youtube/websub/{opaque-token}`. It has
no chat, account, automation, browser-control, OpenAPI, or documentation routes.
The HTTPS tunnel provider handles callback traffic containing public upload
metadata and opaque callback URLs. Channel registration discloses the monitored
channel IDs to Google's hub. Watch history, search queries, conversations, and
the local relevance profile do not cross this callback transport.
Never publish the main backend on port 8000 through the tunnel. The receiver
defaults to port 8001 and must share the backend's local Knowledge Core paths.

## Quick Tunnel for a development check

1. Install `cloudflared` from the [official downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/).
2. From the Vellum repository, start the callback receiver:

   ```powershell
   .\scripts\start-youtube-push.ps1
   ```

3. In a separate terminal, start the tunnel:

   ```powershell
   cloudflared tunnel --url http://127.0.0.1:8001
   ```

4. Copy the HTTPS origin printed by `cloudflared` into the local `.env`:

   ```dotenv
   YOUTUBE_PUSH_CALLBACK_BASE=https://generated-name.trycloudflare.com
   ```

   Use the origin only, with no callback path or secret. Vellum generates a
   separate random callback token and HMAC secret for each channel.

5. Restart the receiver and Vellum backend so both load that origin:

   ```powershell
   .\scripts\start-youtube-push.ps1 -Restart
   ```

   Then restart Vellum's backend through its normal launcher. The receiver script
   verifies the live port owner's command line before restarting it, rather than
   trusting a saved PID that Windows might have reused. Another application on
   that port is never stopped. Do not run multiple receivers on the same port.
6. Keep **YouTube creator uploads** active with its existing full-access opt-in.
   Connect/reconnect the read-only Google connector for subscription snapshots
   and video duration metadata. The configured tracking account must match the
   connected account for automatic subscription refresh. An explicitly combined
   local profile can pin `subscription_account_id` to the verified connected
   channel ID while retaining its existing history and upload account key;
   accounts are never silently linked. Routine policy updates preserve this pin.
7. Read `GET http://127.0.0.1:8000/api/plugins/youtube/creators/push`, or reopen
   the YouTube connection dialog, which refreshes push status every ten seconds
   while open. Registered channels progress from pending to
   active after Google's verification request. This read returns counts and
   sanitized warnings, never callback tokens or HMAC secrets.

Cloudflare documents Quick Tunnels as development-only: the hostname changes
between runs, there is no uptime guarantee, and interactive email authentication
does not support non-interactive clients. Do not put email login or a Cloudflare
Access login in front of a machine callback. The callback itself verifies its
subscription token, exact channel/topic, and HMAC signature.

[Quick Tunnel reference](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Stable HTTPS for everyday use

Use a named Cloudflare Tunnel with a domain managed in Cloudflare:

1. Create a Cloudflare account and add your domain if you do not already have one.
2. Follow [Create a tunnel in the dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).
3. Install the Windows connector using the dashboard-generated instructions.
   Keep its token out of Git, screenshots, chat, and model prompts.
4. Add a published application hostname such as `youtube.yourdomain.com`, with
   service type **HTTP** and origin `127.0.0.1:8001`.
5. Set `YOUTUBE_PUSH_CALLBACK_BASE=https://youtube.yourdomain.com` in `.env`,
   restart both local processes, and verify that subscription counts become active.

With a locally managed tunnel, an optional path restriction is:

```yaml
ingress:
  - hostname: youtube.yourdomain.com
    path: ^/youtube/websub/[A-Za-z0-9_-]{43}$
    service: http://127.0.0.1:8001
  - service: http_status:404
```

Merge this into the named tunnel's own configuration containing its tunnel ID
and credential-file path. The catch-all returns 404 for other routes.
[Cloudflare ingress configuration](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/).

A domain may have a registration cost. This tunnel setup still depends on your
PC and Internet connection. Receiving uploads while the PC is powered off needs
a separately deployed, durable hosted collector; that is not part of this local
receiver. A tunnel is a network transport, not an offline queue.

## Coverage, filtering, and recovery

- Push registration includes all eligible **saved** subscriptions for the exact
  tracking account, plus explicitly tracked and currently eligible inferred
  creators. It does not apply the RSS `max_channels` cap. Former/excluded rules
  still win, including provisional name exclusions.
- The existing OAuth ingestion owner refreshes subscriptions at most every six
  hours while push is configured and the creator automation is active. An
  account mismatch or failed refresh is visible; the last saved list remains
  available. This does not import YouTube's native bell inbox or watch history.
- Registration and renewal run every 30 seconds on Vellum's existing scheduler,
  with at most eight hub requests per tick. The initial registration of a large
  list is gradual. Status is active only after verified callbacks, not merely
  after an accepted subscription request. Granted leases determine renewals at
  80 percent of their lifetime. Failed attempts back off, and restart state is durable.
- Accepted callbacks commit to the existing upload outbox **before** HTTP 204.
  XML is capped at 256 KiB and 50 entries; entity declarations, wrong channels,
  invalid IDs, invalid signatures and oversized payloads are rejected. At 10,000
  queued uploads, the receiver returns 503 so the sender can retry.
- The backend drains accepted events every five seconds. Relevant new uploads
  pass the same strictly-greater-than-duration policy as RSS. Push coalesces
  metadata calls to at most one batch per ten seconds, sharing the persisted
  daily duration quota with polling. Unknown duration stays queued, retries
  after two minutes, and provider failures defer further calls for five minutes.
  Quota exhaustion waits for the UTC daily reset and is visible in status.
- Quiet subscribed creators' uploads are saved as baseline records for recall,
  without pinging. Those records can have unverified duration, as disclosed in
  saved-upload answers. New push events published before monitoring began are
  also quiet. Title edits update the same channel/video identity without a new ping.
- RSS reconciliation still runs every 15 minutes within the existing rolling
  request/day budgets and now rotates over registered push channels too. Large
  lists take longer to reconcile. First RSS reads are quiet baselines, and the
  feed's short upload window cannot guarantee recovery after long downtime.
- Delivery uses the same account/channel/video receipt across push and RSS.
  Delivery errors retain pending uploads; pausing or revoking unattended
  permission blocks delivery. Successful nonempty push batches appear in the
  automation's bounded run history.
- The open UI subscribes to local notification change events. Its 15-second
  polling, focus/visibility refresh, durable inbox, and browser quiet mode remain
  recovery/presentation paths. SSE never travels through the public callback
  tunnel. No old toast is replayed just because a stream reconnects.

This is near-real-time delivery, not a latency guarantee. Google, the network,
duration metadata availability, quotas, and local process availability all
affect end-to-end latency. The app does not display notifications while powered off.

## Reconnecting Google

Public WebSub collection can remain healthy while Google rejects the local OAuth
grant used for video-length checks. Push status exposes `authorization_required`
and a reconnect warning in this case. Known rejected grants do not reserve more
duration-check units; a request that first discovers rejection still counts.
Unverified uploads remain queued under the existing long-form rule.

A successful OAuth callback for the explicitly linked subscription account
releases failed duration and subscription retry timers, without resetting daily
budgets, changing account linkage, or clearing saved evidence. If the tracking
worker is busy, an account-scoped recovery marker in existing Knowledge Core
sync cursors survives until the normal worker retries it. Recovery failure does
not turn a successfully connected Google grant into a failed OAuth result.

Google controls grant revocation and expiry. External OAuth apps whose publishing
status is Testing receive seven-day refresh tokens for YouTube scopes. An
`authorization_required` result alone does not establish whether the grant was
revoked or expired, or prove the project's publishing status. See
[Google's OAuth token-expiration rules](https://developers.google.com/identity/protocols/oauth2/).

## Storage and rollback

Knowledge Core schema 16 adds the subscription table and source lookup index.
Upload events reuse `youtube_upload_outbox` with a transient `push_queued` state.
No separate database, notification archive, chat writer, or scheduler is created.
Callback credentials remain machine-local and must not be included in public
exports or logs. Receiver access logging is disabled by the launcher.

Leave the HTTPS origin blank to disable registration and processing. Restore it
to resume durable work. Exclusions retire individual hub registrations; changing
the origin retires the old callback on a best-effort basis and registers the new
one. Old registrations also expire at the hub. Before running an older build
that only understands schema 15, back up the database and restore a compatible
pre-upgrade snapshot; older builds intentionally reject newer schema versions.

Protocol sources: [YouTube push events](https://developers.google.com/youtube/v3/guides/push_notifications),
[PubSubHubbub authenticated distribution and leases](https://pubsubhubbub.github.io/PubSubHubbub/pubsubhubbub-core-0.4.html).


### Limited Google grants

YouTube authorization can be managed from Plugins → YouTube → Manage Google connection, as well as the YouTube agent. The connection displays a provider-reported grant expiry when Google supplies one. Access-token refreshes do not make a limited refresh grant permanent. Renew before the displayed deadline; known expired grants pause duration checks while saved uploads and creator choices remain retained.

On 29 October 2026 a successful live refresh returned `refresh_token_expires_in` of approximately 604,727 seconds, establishing that the renewed grant itself was limited to about seven days. This does not independently establish the Cloud project's publishing status or the consent-screen setting that produced it. Google documents this field as the remaining refresh-token lifetime for time-based access: https://developers.google.com/identity/protocols/oauth2/web-server#time-based-access
