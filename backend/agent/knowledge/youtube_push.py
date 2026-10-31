"""Additive push subscriptions in Knowledge Core; uploads use its existing outbox."""
from contextlib import closing
import json


def migrate_push(connection):
    connection.executescript('''
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS youtube_push_subscriptions (
            account_id TEXT NOT NULL, channel_id TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE, state_json TEXT NOT NULL,
            PRIMARY KEY(account_id, channel_id)
        );
        CREATE INDEX IF NOT EXISTS youtube_push_subscription_sources
            ON sources(kind, account_id, status);
        PRAGMA user_version = 16;
        COMMIT;
    ''')


class YouTubePushStoreMixin:
    def youtube_push_targets(self, account):
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT title,metadata_json FROM sources WHERE kind='youtube_subscription' "
                "AND account_id=? AND status='active'", (account,)).fetchall()
        return {str(json.loads(row['metadata_json']).get('subscribed_channel_id', '')): row['title'] for row in rows}

    def youtube_push_subscriptions(self, account):
        with closing(self._connect()) as connection:
            rows = connection.execute('SELECT * FROM youtube_push_subscriptions WHERE account_id=?', (account,)).fetchall()
        return [dict(json.loads(row['state_json']), account_id=row['account_id'],
                     channel_id=row['channel_id'], token=row['token']) for row in rows]

    def youtube_push_subscription(self, token):
        with closing(self._connect()) as connection:
            row = connection.execute('SELECT * FROM youtube_push_subscriptions WHERE token=?', (token,)).fetchone()
        return dict(json.loads(row['state_json']), account_id=row['account_id'],
                    channel_id=row['channel_id'], token=row['token']) if row else None

    def youtube_push_register(self, account, channel, token, state):
        with closing(self._connect()) as connection, connection:
            connection.execute('INSERT OR IGNORE INTO youtube_push_subscriptions VALUES (?,?,?,?)',
                               (account, channel, token, json.dumps(state)))

    def youtube_push_patch(self, token, fields):
        with closing(self._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT state_json FROM youtube_push_subscriptions WHERE token=?', (token,)).fetchone()
            if row:
                state = dict(json.loads(row[0]), **fields)
                connection.execute('UPDATE youtube_push_subscriptions SET state_json=? WHERE token=?', (json.dumps(state), token))

    def youtube_push_enqueue(self, account, channel, entries, now):
        """Commit before HTTP acknowledgment; provider replay preserves delivery status."""
        with closing(self._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            count = connection.execute("SELECT COUNT(*) FROM youtube_upload_outbox WHERE account_id=? "
                                       "AND status='push_queued'", (account,)).fetchone()[0]
            if count + len(entries) > 10000:
                raise OverflowError('Push queue capacity reached; retry delivery later.')
            for item in entries:
                connection.execute('''INSERT INTO youtube_upload_outbox VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(account_id,channel_id,video_id) DO UPDATE SET
                    title=excluded.title,creator=excluded.creator''',
                    (account, channel, item['video_id'], item['title'], item['creator'],
                     item['published_at'], 'push_queued', now))

    def youtube_push_queued(self, account, limit=200):
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM youtube_upload_outbox WHERE account_id=? AND status='push_queued' "
                "ORDER BY discovered_at,channel_id,video_id LIMIT ?", (account, limit)).fetchall()
        return [dict(row) for row in rows]

    def youtube_push_promote(self, account, channel, video, status):
        with closing(self._connect()) as connection, connection:
            connection.execute("UPDATE youtube_upload_outbox SET status=? WHERE account_id=? AND channel_id=? "
                "AND video_id=? AND status='push_queued'", (status, account, channel, video))

    def youtube_push_queue_status(self, account, *, include_pending=False):
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) AS queued FROM youtube_upload_outbox "
                                     "WHERE account_id=? AND status IN ('push_queued',?)",
                                     (account, 'pending' if include_pending else 'push_queued')).fetchone()
        return int(row['queued'])
