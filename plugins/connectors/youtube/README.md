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
