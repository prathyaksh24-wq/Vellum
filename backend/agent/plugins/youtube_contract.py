"""Stable YouTube connector identifiers shared without loading connector runtimes."""

YOUTUBE_REDIRECT_URI = "http://127.0.0.1:8000"
YOUTUBE_CONNECTION_START_ACTION_ID = "youtube.connection.start"
YOUTUBE_SYNC_ACTION_ID = "youtube.sync"
YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID = "youtube.connection.disconnect"
YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID = "youtube.intelligence.rebuild"
YOUTUBE_ACTION_IDS = frozenset({
    YOUTUBE_CONNECTION_START_ACTION_ID,
    YOUTUBE_SYNC_ACTION_ID,
    YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID,
    YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID,
})
