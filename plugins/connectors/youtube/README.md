# YouTube connector

This portable connector implements read-only Google OAuth and bounded YouTube
Data API access. Vellum owns runtime configuration, OS-keyring persistence,
Knowledge Core ingestion, API routes, and scheduling through its backend
adapter.

The scope is `youtube.readonly`. It reads channel identity, subscriptions, and
the authenticated account's recent liked videos. Watch history and watch-time
behavior are not available through the YouTube Data API and are imported by
Vellum's backend Takeout adapter so this package does not become a second data
store.

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
