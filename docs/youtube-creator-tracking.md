# Adaptive YouTube creator tracking

Creator tracking extends the YouTube plugin, Knowledge Core, Automations, and
ConversationLifecycle. It uses public channel Atom feeds and saved local watch
evidence. It does not reproduce YouTube's personalized homepage.

`youtube.creators.configure` is an authorized App Action with a typed
`CreatorTrackingConfig`: account ID, explicitly linked history account IDs,
enabled state, relationship rules, and polling capacity. A rule requires a
verified channel ID, except a provisional hard exclusion can use an exact
channel name and aliases until metadata resolves its ID. IDs remain excluded
after renames. Updates preserve omitted excluded/former rules. To replace a
relationship, supply an explicit rule for that identity. No subscriptions,
likes, or YouTube account settings are changed.

`GET /api/plugins/youtube/creators` returns a typed, uncached local assessment.
The YouTube connection dialog shows monitored creators and exclusion count.
The YoutubeAgent's `youtube.subscription_feed` tool reads this same projection
and saved uploads, restricted to the local specialist. Ask "Which YouTube
creators are you tracking?" or "Show my YouTube creator uploads."

## Relationships and evidence

- Long-term relationships are explicit and remain eligible during quiet periods.
- Current-interest seeds last 30 days. Repeated activity must sustain them later.
- Automatic selection requires at least three saved video/day records on three
  separate days in the last 21 days. Scores decay with a 14-day exponential
  scale. Single watches and searches do not reactivate former/excluded creators.
- Seasonal relationships remain saved when quiet and become eligible again
  through repeated recent activity. This is evidence-led, not a guessed sports
  calendar. Topic terms conservatively gate both watch evidence and upload
  titles for broad channels. Keyword matching can miss titles without the terms;
  it is not semantic understanding or verified video content.
- Former relationships and hard exclusions override inferred engagement.
  Existing positive Knowledge preferences for them are invalidated while raw
  observations remain available as private historical evidence.
- Search history remains inquiry evidence in the existing Takeout projection.
  No homepage exposure, ignored recommendation counts, completion rates, or
  continuous personal search capture are inferred.

Counts are distinct video/day records in the selected saved history. The same
video on the same day across linked browser and Takeout sources counts once;
Takeout timestamps are converted into the configured history timezone first.
For topic-filtered creators the assessment counts matching titles. Exact repeat
plays, complete lifetime views, and watch duration remain unknown. Missing or
explicit ad records do not become positive creator signals. A bounded public
metadata lookup can attribute previously missing video ownership; recovered
ownership alone cannot establish whether an old record was an advertisement.
Unavailable videos remain unattributed, are counted separately from queued
attribution, and do not starve later lookups.

## Polling and delivery

The paused-by-default **YouTube creator uploads** built-in runs every 15 minutes
when enabled, through the normal Automation scheduler and run receipts. Its
handler is deterministic and calls no chat model. It runs while Vellum's backend
is running; it does not install an operating-system service.

Default limits are 20 monitored channels, 8 feed requests per rolling 15-minute
window (including manual checks), and 768 per UTC day. Each active channel is
due after 30 minutes; capacity may lengthen that interval. These are Vellum's
own limits, not official guaranteed YouTube allowances. Atom reads use no API
key. Intermittent feed failures can use the connected read-only Data API's
public uploads playlist. This reserves at most two API units per fallback check,
with a separate default cap of 1,536 units per UTC day. Cached playlist IDs save
one call; budgeting conservatively reserves two. The same rolling window limits
manual fallback checks. The fallback can be disabled in tracking settings.
Missing-ownership attribution uses the connected read-only Data API, one
batch of at most 50 public video IDs per 15 minutes; no search text or watch
timestamps are sent. Provider failures defer attribution for an hour.

Feed and API transports share baseline, outbox, and delivery identities, so a
transport switch does not duplicate notifications. The API fallback reads only
the newest 15 upload entries. Playlist ownership is validated before accepting
entries. Google documents one unit for each [channels.list](https://developers.google.com/youtube/v3/docs/channels/list)
and [playlistItems.list](https://developers.google.com/youtube/v3/docs/playlistItems/list)
call. These quotas are separate from public Atom request limits.

Feeds have a 256 KiB response cap, 50-entry parsing cap, fixed HTTPS host, no
redirects, connect/read deadlines, and conditional ETag/Last-Modified requests.
Invalid identities and entity declarations are rejected. Backoff grows to a
day; 429 pauses the provider across channels and honors Retry-After. The first
successful read records a quiet baseline. Subsequent unseen relevant uploads
published within two days enter a canonical outbox. Title edits update the
same channel/video record and never create a fresh upload notification.

Collection and outbox state commit together in Knowledge Core. A database
lease prevents overlapping workers and expires after a crashed worker. Delivery
uses a stable account/channel/video receipt through ConversationLifecycle;
retrying after delivery but before acknowledgment does not duplicate the
conversation message. Missing destinations fail visibly and leave the outbox
pending. Exclusions and relevance are checked again before delivery.

Poll errors and coverage gaps remain visible in creator status and Automation
receipts. Initial feed collection progresses within the same request limits;
status reports the number baselined and remains `baselining` until every
selected creator has a successful baseline. Atom is a short recent-upload window; missed uploads after long
downtime cannot be guaranteed recoverable. Nonpending outbox records are pruned
after 90 days, while the two-day publication gate prevents old entries from
being renotified after pruning.

## Storage and verification

Knowledge Core schema 15 adds derived creator activity, bounded day aggregates
(367 days per channel), upload outbox, and worker leases. Raw observations are
retained. Source filtering occurs before pagination. Projection checkpoints and
aggregates commit atomically, so replay is idempotent and steady polls process
only newly inserted watch observations. Changing linked account scope, history
timezone, or topic filters resets only this rebuildable projection. Repeated
configuration preserves explicit corrections within the 200-rule bound and
retains interest seed timestamps only for current rules. Explicit user choices live in canonical local
sync cursor state and are not a cloud or global Codex memory write.

Tests cover current-interest decay, seasonal reactivation, exclusions and
renames, account isolation and scope changes, search/ad exclusions, topic gates,
baseline/title edits, restart and delivery retries, backoff/request budgets,
lease recovery, HTTP/action contracts, and a 20-year history fixture. Fixture
simulation is evidence of implementation behavior, not a claim of years of
unattended live operation.
