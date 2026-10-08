# YouTube connector

This portable connector implements read-only Google OAuth and bounded YouTube
Data API access. Vellum owns runtime configuration, OS-keyring persistence,
Knowledge Core ingestion, API routes, and scheduling through its backend
adapter.

The Google connector scope is `youtube.readonly`. It reads channel identity,
subscriptions, and the authenticated account's recent liked videos. The browser
login is separate: changing it does not switch the Google connector account.

Open the YouTube Agent and click **Refresh history** after signing into YouTube
in Vellum's Browser. Watch-history questions also refresh automatically in a
temporary background tab, without opening the panel or changing its current
page. The
fixed reader uses the existing dedicated browser owner and saves account-scoped
snapshots and deduplicated video/day observations in Knowledge Core with private-local-only sensitivity and deny-raw
external disclosure. It reads up to 100 recent rendered entries, preserves the
page's day labels and verified video links, and checks account identity before
and after reading. It does not infer precise watch timestamps, watch duration,
repeat-watch counts, or an all-time total. A refresh does not run a continuous
background monitor.

Signed-out, paused, unidentified-account, changed-account and unrecognized-page
states fail explicitly without returning an older account's snapshot or a public
search. Current watch-history queries use the browser account; explicitly
imported or Takeout history still uses the existing archive adapter. The archive
and browser evidence stay separate. Enable **YouTube history refresh** in
Automations to accumulate recent pages every 15 minutes while the backend runs.
The automation starts paused, uses a temporary background tab, and retains saved
dated records after they disappear from the latest page. Its 100-entry page limit
is independent of the accumulated count. Saved retrieval is scoped to the last
successfully read browser account.

Vellum counts subscriptions from the complete paginated account read. Count-only
questions return the total without a channel list; list questions show up to 50
channels and identify a longer list explicitly. Recent liked-video replies show
all fetched entries (20 by default) with links; this recent batch is not an
all-time liked-video total. Imported subscription counts are labeled as Takeout
snapshots when the live account is disconnected.

The YouTube agent uses the selected local model to interpret the requested
entity, quantity, creator filter, and format, then executes a validated read-only
plan. Channel lists derived from likes deduplicate channel IDs and cover up to
50 recent liked videos; fewer available channels are reported without padding.
The existing specialist chat context retains the actual displayed order for
follow-ups such as “link to the second video.” Missing lists, unavailable data,
and connector failures explain the limitation instead of substituting a public
search. Lists shown before this retention was added must be requested again.
