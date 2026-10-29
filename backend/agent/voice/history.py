"""Local completed-dictation recordings and transcripts; no agent-memory ingestion."""

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import sqlite3
from uuid import uuid4

from agent.config import REPO_ROOT
from agent.contracts.voice import (DictationHistoryEntry, DictationHistoryPage,
    DictationPreferences, DictationTranscript)


class DictationStore:
    def __init__(self,path: Path):
        self.path=path

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA secure_delete=ON')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS dictations (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, text TEXT NOT NULL, language TEXT, requested_language TEXT NOT NULL, duration_seconds REAL NOT NULL, model TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS dictations_date ON dictations(created_at DESC,id DESC)')
            db.execute('CREATE TABLE IF NOT EXISTS recordings (entry_id TEXT PRIMARY KEY REFERENCES dictations(id) ON DELETE CASCADE, wav BLOB NOT NULL)')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _preferences(db):
        row=db.execute('SELECT value FROM preferences WHERE id=1').fetchone()
        return DictationPreferences.model_validate_json(row['value']) if row else DictationPreferences()

    def preferences(self) -> DictationPreferences:
        with self.connection() as db:
            return self._preferences(db)

    def update_preferences(self,patch: dict) -> DictationPreferences:
        # Validate only the supplied fields; omitted values retain their owner.
        if not patch:
            raise ValueError('At least one dictation preference is required.')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current=self._preferences(db)
            updated=DictationPreferences.model_validate({**current.model_dump(),**patch})
            db.execute('INSERT INTO preferences VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(updated.model_dump_json(),))
            return updated

    def save(self,transcript: DictationTranscript,audio: bytes | None=None) -> str | None:
        if not transcript.text.strip():
            return None
        entry=DictationHistoryEntry(id=uuid4().hex,created_at=datetime.now(timezone.utc).isoformat(),
            text=transcript.text,language=transcript.language,requested_language=transcript.requested_language,
            duration_seconds=transcript.duration_seconds,model=transcript.model)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._preferences(db).save_history:
                return None
            db.execute('INSERT INTO dictations VALUES(?,?,?,?,?,?,?)',(entry.id,entry.created_at,entry.text,entry.language,entry.requested_language,entry.duration_seconds,entry.model))
            if audio:
                db.execute('INSERT INTO recordings VALUES(?,?)',(entry.id,audio))
        return entry.id

    def history(self,*,offset=0,limit=30,query='',language='') -> DictationHistoryPage:
        pattern='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        where="WHERE text LIKE ? ESCAPE '\\' AND (?='' OR COALESCE(language,'unknown')=?)"
        args=(pattern,language,language)
        with self.connection() as db:
            total=db.execute('SELECT count(*) FROM dictations '+where,args).fetchone()[0]
            rows=db.execute('SELECT dictations.*,EXISTS(SELECT 1 FROM recordings WHERE entry_id=dictations.id) AS has_recording FROM dictations '+where+' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
            counts={row['language'] or 'unknown':row['count'] for row in db.execute('SELECT language,count(*) AS count FROM dictations GROUP BY language')}
            return DictationHistoryPage(settings=self._preferences(db),items=[DictationHistoryEntry.model_validate(dict(row)) for row in rows],
                total=total,offset=offset,limit=limit,language_counts=counts)

    def recording(self,entry_id: str) -> bytes | None:
        from agent.contracts.voice import DictationHistoryDelete
        DictationHistoryDelete(entry_id=entry_id)
        with self.connection() as db:
            row=db.execute('SELECT wav FROM recordings WHERE entry_id=?',(entry_id,)).fetchone()
            return bytes(row['wav']) if row else None

    def delete(self,*,entry_id: str | None=None,all: bool=False) -> int:
        from agent.contracts.voice import DictationHistoryDelete
        command=DictationHistoryDelete(entry_id=entry_id,all=all)
        with self.connection() as db:
            cursor=db.execute('DELETE FROM dictations' if command.all else 'DELETE FROM dictations WHERE id=?',() if command.all else (command.entry_id,))
            return cursor.rowcount


@lru_cache(maxsize=1)
def get_dictation_store() -> DictationStore:
    return DictationStore(REPO_ROOT/'data/voice/dictation.db')
