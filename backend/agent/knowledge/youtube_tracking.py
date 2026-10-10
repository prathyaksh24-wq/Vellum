"""YouTube derived projections and outbox, owned by KnowledgeStore.

No independent database or scheduler. All mutations use the canonical store's
connections; checkpoints and aggregate changes commit together.
"""
from contextlib import closing
from datetime import date, timedelta
import json
from typing import Any


def migrate_tracking(connection):
    connection.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS youtube_creator_activity (
            account_id TEXT NOT NULL, video_id TEXT NOT NULL, day TEXT NOT NULL,
            channel_id TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '',
            observation_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', PRIMARY KEY(account_id, video_id, day)
        );
        CREATE INDEX IF NOT EXISTS youtube_creator_activity_channel
            ON youtube_creator_activity(account_id, channel_id, day);
        CREATE INDEX IF NOT EXISTS youtube_creator_activity_pending
            ON youtube_creator_activity(account_id, day) WHERE channel_id = '';
        CREATE TABLE IF NOT EXISTS youtube_creator_stats (
            account_id TEXT NOT NULL, channel_id TEXT NOT NULL, name TEXT NOT NULL,
            total INTEGER NOT NULL, last_day TEXT NOT NULL, days_json TEXT NOT NULL,
            PRIMARY KEY(account_id, channel_id)
        );
        CREATE INDEX IF NOT EXISTS youtube_creator_stats_recent
            ON youtube_creator_stats(account_id, last_day);
        CREATE TABLE IF NOT EXISTS youtube_upload_outbox (
            account_id TEXT NOT NULL, channel_id TEXT NOT NULL, video_id TEXT NOT NULL,
            title TEXT NOT NULL, creator TEXT NOT NULL, published_at TEXT NOT NULL,
            status TEXT NOT NULL, discovered_at TEXT NOT NULL,
            PRIMARY KEY(account_id, channel_id, video_id)
        );
        CREATE INDEX IF NOT EXISTS youtube_upload_outbox_pending
            ON youtube_upload_outbox(account_id, status, published_at);
        CREATE TABLE IF NOT EXISTS youtube_tracking_leases (
            account_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at REAL NOT NULL
        );
        PRAGMA user_version = 15;
        COMMIT;
    """)


class YouTubeTrackingStoreMixin:
    def youtube_tracking_reset_projection(self, account):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM youtube_creator_stats WHERE account_id=?", (account,))
            connection.execute("DELETE FROM youtube_creator_activity WHERE account_id=?", (account,))
            connection.execute("DELETE FROM sync_cursors WHERE connector='youtube_creator_projection' AND account_id=?", (account,))

    def youtube_tracking_exclude_preferences(self, channel_ids, names):
        """Invalidate derived positive preferences, retaining raw observations."""
        subjects = set()
        with closing(self._connect()) as connection, connection:
            rows = connection.execute("SELECT DISTINCT subject_key,metadata_json FROM user_signals WHERE category='youtube_channel' AND eligible=1").fetchall()
            for row in rows:
                metadata = json.loads(row["metadata_json"])
                name = " ".join(str(metadata.get("channel_title", "")).casefold().split())
                if metadata.get("channel_id") in channel_ids or name in names:
                    subjects.add(row["subject_key"])
            for subject in subjects:
                connection.execute("UPDATE user_signals SET eligible=0 WHERE category='youtube_channel' AND subject_key=?", (subject,))
                connection.execute("DELETE FROM preference_states WHERE subject_key=?", (subject,))
        return len(subjects)

    def youtube_tracking_page(self, accounts, after=0, limit=500):
        marks = ",".join("?" for _ in accounts)
        with closing(self._connect()) as connection:
            rows = connection.execute(f"""
                SELECT o.rowid AS position, o.id, o.action, o.observed_at, o.payload_json
                FROM observations o JOIN sources s ON s.id=o.source_id
                WHERE o.rowid>? AND s.account_id IN ({marks}) AND s.status='active'
                AND ((o.origin='youtube_takeout' AND o.action='youtube.watch') OR
                     (o.origin='youtube_browser_history' AND o.action='youtube.history_presence'))
                ORDER BY o.rowid LIMIT ?
            """, [after, *accounts, min(limit, 500)]).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in rows]

    @staticmethod
    def _youtube_add_stat(connection, account, channel, name, day):
        old = connection.execute("SELECT * FROM youtube_creator_stats WHERE account_id=? AND channel_id=?",
                                 (account, channel)).fetchone()
        days = json.loads(old["days_json"]) if old else {}
        last = max(day, old["last_day"] if old else day)
        cutoff = (date.fromisoformat(last) - timedelta(days=366)).isoformat()
        days[day] = days.get(day, 0) + 1
        days = {key: value for key, value in days.items() if key >= cutoff}
        connection.execute("""INSERT INTO youtube_creator_stats VALUES (?,?,?,?,?,?)
            ON CONFLICT(account_id,channel_id) DO UPDATE SET name=excluded.name,
            total=excluded.total,last_day=excluded.last_day,days_json=excluded.days_json""",
            (account, channel, name, (old["total"] if old else 0) + 1, last, json.dumps(days)))

    def youtube_tracking_ingest(self, account, events, cursor, now):
        from agent.knowledge.models import SyncCursorInput
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for event in events:
                inserted = connection.execute("INSERT OR IGNORE INTO youtube_creator_activity VALUES (?,?,?,?,?,?,?)",
                    (account, event["video_id"], event["day"], event["channel_id"], event["name"], event["id"], event["title"]))
                if inserted.rowcount and event["channel_id"] and event["relevant"]:
                    self._youtube_add_stat(connection, account, event["channel_id"], event["name"], event["day"])
            self._upsert_sync_cursor(connection, SyncCursorInput(connector="youtube_creator_projection",
                account_id=account, cursor=str(cursor)), succeeded_at=now)

    def youtube_tracking_stats(self, account):
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM youtube_creator_stats WHERE account_id=? ORDER BY last_day DESC LIMIT 5000", (account,)).fetchall()
        return [dict(row) | {"days": json.loads(row["days_json"])} for row in rows]

    def youtube_tracking_pending(self, account, limit=50):
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT DISTINCT video_id FROM youtube_creator_activity WHERE account_id=? AND channel_id='' ORDER BY day DESC LIMIT ?",
                                      (account, limit)).fetchall()
        return [row[0] for row in rows]

    def youtube_tracking_attribute(self, account, metadata):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for video, item in metadata.items():
                rows = connection.execute("SELECT * FROM youtube_creator_activity WHERE account_id=? AND video_id=? AND channel_id=''", (account, video)).fetchall()
                for row in rows:
                    connection.execute("UPDATE youtube_creator_activity SET channel_id=?,name=? WHERE account_id=? AND video_id=? AND day=?",
                        (item["channel_id"], item["name"], account, video, row["day"]))
                    if not item.get("topic_terms") or any(term.casefold() in row["title"].casefold() for term in item["topic_terms"]):
                        self._youtube_add_stat(connection, account, item["channel_id"], item["name"], row["day"])

    def youtube_tracking_unavailable(self, account, videos):
        with closing(self._connect()) as connection, connection:
            for video in videos:
                connection.execute("UPDATE youtube_creator_activity SET channel_id='unavailable' WHERE account_id=? AND video_id=? AND channel_id=''", (account, video))

    def youtube_tracking_pending_count(self, account):
        with closing(self._connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM youtube_creator_activity WHERE account_id=? AND channel_id=''", (account,)).fetchone()[0]

    def youtube_tracking_unavailable_count(self, account):
        with closing(self._connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM youtube_creator_activity WHERE account_id=? AND channel_id='unavailable'", (account,)).fetchone()[0]

    def youtube_tracking_prune(self, account, before):
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM youtube_upload_outbox WHERE account_id=? AND discovered_at<? AND status!='pending'", (account, before))

    def youtube_tracking_lock(self, account, owner, now, duration=180):
        with closing(self._connect()) as connection, connection:
            result = connection.execute("""INSERT INTO youtube_tracking_leases VALUES (?,?,?)
                ON CONFLICT(account_id) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at
                WHERE youtube_tracking_leases.expires_at<=?""", (account, owner, now+duration, now))
            return bool(result.rowcount)

    def youtube_tracking_unlock(self, account, owner):
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM youtube_tracking_leases WHERE account_id=? AND owner=?", (account, owner))

    def youtube_tracking_save_feed(self, account, channel, entries, state, now):
        from agent.knowledge.models import SyncCursorInput
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in entries:
                connection.execute("""INSERT INTO youtube_upload_outbox VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(account_id,channel_id,video_id) DO UPDATE SET title=excluded.title,creator=excluded.creator""",
                    (account, channel, item["video_id"], item["title"], item["creator"], item["published_at"], item["status"], now))
            self._upsert_sync_cursor(connection, SyncCursorInput(connector="youtube_creator_feed",
                account_id=account+":"+channel, state=state), succeeded_at=now)

    def youtube_tracking_uploads(self, account, *, pending=False, limit=100):
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM youtube_upload_outbox WHERE account_id=? AND status IN (?,?) ORDER BY published_at DESC LIMIT ?",
                (account, "pending" if pending else "delivered", "pending" if pending else "baseline", min(limit, 100))).fetchall()
        return [dict(row) for row in rows]

    def youtube_tracking_ack(self, account, channel, video, status="delivered"):
        with closing(self._connect()) as connection, connection:
            connection.execute("UPDATE youtube_upload_outbox SET status=? WHERE account_id=? AND channel_id=? AND video_id=? AND status='pending'",
                               (status, account, channel, video))
