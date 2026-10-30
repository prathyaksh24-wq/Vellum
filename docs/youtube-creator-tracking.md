# Adaptive YouTube creator tracking

Creator tracking extends the YouTube plugin, Knowledge Core, Automations, and
ConversationLifecycle. It uses public channel Atom feeds, optional WebSub push, and saved local watch
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

Explicit YouTube/YT feed questions use this local creator feed, including
"what is youtube feed looking like?" Generic X feed matching cannot override
the named YouTube domain. The specialist directory describes creator feeds
and notification reads so model-based delegation has the same domain boundary.

`youtube.notifications` is a typed local-only read of the existing AutomationStore,
restricted to YouTubeAgent and creator-upload built-ins. Filtering occurs before
pagination and counts, so other tasks' notifications cannot enter the answer.
"YouTube notifications" reads unread items received within 24 hours; "my YouTube
notification history" reads retained older/read items. Chat reads preserve read
state, return verified video links, and do not import YouTube's native bell inbox.
Unsupported date constraints and mutation requests are not silently treated as
unfiltered reads. Returning to a visible tab refreshes the notification projection
immediately, and an open History view participates in the existing polling loop.

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

## Related interests and the local feed

The profile combines explicitly linked browser/Takeout watch observations and
Takeout searches locally. Repeated watches still select creators automatically.
Related discovery examines title topic matches and cached public channel topic
labels on at least three saved days within the last 367 days. A topic activates through viewing on three distinct
days in the last 21 days, or two viewing days corroborated by two search days.
Searches alone never activate notifications or endorse a creator. Basketball,
American football, Formula One, chess, Clash Royale, technology and AI use
bounded keyword patterns; this is transparent topic matching, not semantic
understanding of every video.

By default at most three additional related channels per active topic are
selected, within the overall channel capacity. Their priority reflects supported
days; broad inferred channels retain active-topic upload filters. Existing
explicit topic filters, former relationships and exclusions are preserved.
Related channels return to quiet when the supporting interest fades. The local
upload feed ranks confirmed eligible uploads by freshness and creator activity
and includes reasons. It reuses known channel identities from saved activity;
it does not search the entire YouTube catalog for unknown creators.

Public descriptions and topic categories help classify channels whose saved
titles are generic. The existing connector reads at most 50 known channel IDs
per batch, once per hour, with a default cap of 24 API units per UTC day reserved
before I/O. Only derived topic labels are retained, at most 1,000 channel entries,
and they are refreshed after 30 days. A public label requires saved watch support
and does not itself endorse a creator. Failures remain visible and fall back to
saved title evidence. No private search or conversation text is sent to Google.

`topic_preferences` records explicit current or excluded topics. Current seeds
last 30 days. Optional `conversation_topics` is off by default; when enabled,
it reads direct, recent user interest declarations from eligible local
conversations. Assistant text, quoted examples, hypothetical statements, archived,
temporary, profile-ineligible and memory-disabled chats are excluded. Global memory/reference/history
privacy settings remain authoritative. Only the latest user turn can use a
chat-update timestamp when individual message timing is absent. This reader is
bounded to 200 chats and 20 recent user messages each; ambiguous wording is
ignored. No conversation text or search query is sent for public metadata reads.

## Long-form upload policy

`min_duration_seconds=180` means strictly longer than three minutes, including
excluding regular videos of three minutes or less. Atom feeds have no duration;
the existing read-only YouTube connector fetches `videos.list` metadata for up
to 50 public IDs in one call. RSS-only processing permits one duration batch per rolling 15 minutes
and 96 API units per UTC day are reserved before I/O by default. Verified duration
is bound to video and channel identity and expires after six hours for feed
eligibility. The local cache retains at most 1,000 entries and 90 days. Provider
failures defer retries for an hour; unresolved, upcoming or active-live entries
stay queued without a ping. No media is downloaded. This policy needs the
connected Google read-only API even when Atom reads succeed.

Google `invalid_grant` responses mark the existing connector authorization as
requiring renewal, without removing credentials, saved history or channel identity.
Further automatic metadata reads do not repeat a rejected refresh until renewed
tokens are saved. The YouTube agent's Google account button opens connection and
creator status; the dialog exposes **Reconnect with Google** and coverage warnings.
Transient provider failures continue to use bounded backoff and do not mark a
grant revoked. Reconnecting preserves the existing read-only OAuth scope.

"What did ohnePixel upload yesterday?" reads retained channel/day upload records
before any model planner or public search. Publication timestamps use the profile
timezone, and date filtering happens before the result limit. Current channel
quietness does not hide historical uploads. Distinct main/raw/live channel
identities remain separate; an unambiguous saved variant is labelled explicitly.
Coverage is partial, and older retained records can have unverified duration.
Personalized-feed requests use this same local assessment. YouTube's native bell
inbox is not imported; the official Data API exposes subscriptions and public
channel push events, not the personal notification inbox.

## Polling and delivery

Optional WebSub delivery now bypasses the RSS collection rotation for new events.
See [push delivery and HTTPS setup](youtube-push-delivery.md) for the callback-only
receiver, full saved-subscription coverage, lease renewal, shared duration quota,
and local notification change stream. It requires an explicitly configured
public HTTPS origin; the default remains RSS until that setup is complete.

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

The monitored-channel setting accepts 1–100 creators; 20 is its default.
Increasing that setting does not increase the request budget. At the default
eight checks per 15 minutes, an initial rotation takes approximately 45 minutes
for 20 creators, 105 minutes for 50, or 195 minutes for 100, before failures or
backoff. Creators outside the active group can remain in the saved assessment.
Active creators precede quiet inferred creators in bounded status reads. Saved
upload reads apply active-channel and title-topic filters before the result
limit, including older baseline records created before those filters existed.

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
uses a stable account/channel/video receipt. The default notification destination
persists a ping in AutomationStore before acknowledgment, without creating a
conversation. The notification bell retains video links and read state, and an
open UI receives notification change events, with a 15-second polling fallback. Chat destinations remain available
through ConversationLifecycle. Retrying delivery does not duplicate either
destination. Missing destinations fail visibly and leave the outbox
pending. Exclusions and relevance are checked again before delivery.

AutomationStore retains the latest 200 notifications per task and 100 runs.
The canonical upload outbox retains upload identities independently of the visible
notification window. Run now is visible in Scheduled task details; History lists
local dates, start and finish times, duration, output, and errors. Notifications
are in-app; retained unread items remain visible after reopening without replaying
old toasts. Operating-system notifications are not implemented.

Recent notifications are unread pings received within the last 24 hours. Older
and read items are available in a separate History view, grouped by local date
with creator/title search and 50-item pagination. Filtering happens before the
response limit. The recent badge counts only that fresh unread set; marking recent
items read uses the existing typed read action with `recent=true` and leaves older
read state unchanged. The default API view and aggregate `unread_count` remain
compatible; additional counts describe the fresh inbox and retained history.

While the browser panel is visible, the floating bell and upload toasts are hidden.
Opening the browser closes the notification panel; suppressed pings are not replayed
when it closes. Notifications remain accessible from the sidebar (under More in the
expanded sidebar). This is temporary presentation, not a tracking or retention
preference. Panel/list transitions are subtle and honor reduced motion.

Notification history remains bounded to the latest 200 pings per task. Moving an
item out of Recent does not remove its saved upload record; the canonical creator
outbox remains separately available to upload answers for its 90-day retention
window. This is local retained evidence, not an indefinite notification archive.

Poll errors and coverage gaps remain visible in creator status and Automation
receipts. Initial feed collection progresses within the same request limits;
status reports the number baselined and remains `baselining` until every
selected creator has a successful baseline. Atom is a short recent-upload window; missed uploads after long
downtime cannot be guaranteed recoverable. Nonpending outbox records are pruned
after 90 days, while the two-day publication gate prevents old entries from
being renotified after pruning.

## Storage and verification

Notification attention is separate from remembered affinity. Recent watches,
weak search hints, seasonal evidence, and eligible direct user declarations still
drive current relevance. Lifetime creator video/day counts and last-seen dates
remain local after recent interest fades; the 367-day detail bound does not erase
the lifetime aggregate. This is retained observed evidence, not a claim of
complete lifetime YouTube history.

Channel rules now accept `notification_frequency`: `adaptive` (existing relevance
policy), `reduced` (at most one qualifying ping per rolling 24 hours), or `muted`
(no pings). Fewer-notification requests do not exclude a creator or a topic.
When conversational preferences are enabled, direct, unambiguous statements from
eligible saved user messages update bounded local channel preferences. Explicit
feedback persists across restarts and conversational recency windows; later
feedback can restore volume. Assistant, quoted, hypothetical, temporary, and
memory-ineligible messages do not establish preferences. This bounded language
recognizer supports direct phrases; it is not unrestricted semantic learning.
Extra qualifying uploads remain quiet baseline records, available for recall.

Optional `rediscovery_notifications` uses established saved viewing, not merely a
subscription: at least ten video/day records and no saved watch for 90 days, with
a quiet or seasonally quiet relationship. It permits at most one rediscovery ping
per rolling seven days overall and does not resurface the same creator within 90
days. Excluded, former, topic-blocked and muted creators stay out. Ordinary long-form,
freshness, account, and deduplication gates still apply. Rediscovery does not
promote a creator to current interest or claim that the user feels nostalgic.
All pacing and feedback use existing Knowledge Core sync cursors; no new store or
model-training process is created. Canonical notification history and upload
detail retain their existing bounds even while creator affinity persists.

Knowledge Core schema 15 adds derived creator activity, bounded day aggregates
(367 days per channel), upload outbox, and worker leases. Schema 16 adds durable
push subscriptions and reuses that outbox for accepted events. Raw observations are
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
