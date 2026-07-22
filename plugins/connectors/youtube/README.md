# YouTube connector

This portable connector implements read-only Google OAuth and bounded YouTube
Data API access. Vellum owns runtime configuration, OS-keyring persistence,
Knowledge Core ingestion, API routes, and scheduling through its backend
adapter.

The initial scope is `youtube.readonly`. It synchronizes channel identity and
subscriptions. Watch history and watch-time behavior are not available through
the YouTube Data API and are imported separately from Google Takeout.
