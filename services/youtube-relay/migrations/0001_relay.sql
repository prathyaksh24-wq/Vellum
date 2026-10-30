-- Public transport buffer only. Canonical upload knowledge and pings stay local.
CREATE TABLE relay_state (
  id INTEGER PRIMARY KEY CHECK (id=1),
  epoch TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
  revision TEXT NOT NULL DEFAULT '',
  retention_floor INTEGER NOT NULL DEFAULT 0,
  stored_bytes INTEGER NOT NULL DEFAULT 0,
  event_count INTEGER NOT NULL DEFAULT 0,
  last_received_at INTEGER NOT NULL DEFAULT 0,
  last_maintenance INTEGER NOT NULL DEFAULT 0,
  job_until INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT ''
);
INSERT INTO relay_state(id) VALUES(1);
CREATE TABLE channels (
  channel_id TEXT PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,
  secret TEXT NOT NULL,
  desired INTEGER NOT NULL DEFAULT 1,
  revision TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'subscribe',
  requested_at INTEGER NOT NULL DEFAULT 0,
  next_at INTEGER NOT NULL DEFAULT 0,
  lease_expires INTEGER NOT NULL DEFAULT 0,
  renew_at INTEGER NOT NULL DEFAULT 0,
  failures INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX channels_due ON channels(next_at, renew_at);
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,
  digest TEXT NOT NULL UNIQUE,
  body TEXT NOT NULL,
  received_at INTEGER NOT NULL,
  bytes INTEGER NOT NULL
);
CREATE INDEX events_retention ON events(received_at,id);
CREATE TRIGGER events_capacity BEFORE INSERT ON events
WHEN NOT EXISTS (SELECT 1 FROM events WHERE digest=NEW.digest)
  AND ((SELECT stored_bytes+NEW.bytes>67108864 OR event_count>=20000 FROM relay_state WHERE id=1))
BEGIN SELECT RAISE(ABORT,'relay_capacity'); END;
CREATE TRIGGER events_insert AFTER INSERT ON events BEGIN
  UPDATE relay_state SET stored_bytes=stored_bytes+NEW.bytes,event_count=event_count+1,
    last_received_at=MAX(last_received_at,NEW.received_at) WHERE id=1;
END;
CREATE TRIGGER events_delete AFTER DELETE ON events BEGIN
  UPDATE relay_state SET stored_bytes=stored_bytes-OLD.bytes,event_count=event_count-1 WHERE id=1;
END;
