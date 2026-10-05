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
