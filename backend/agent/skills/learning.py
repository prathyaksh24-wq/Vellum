from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from agent.skills.authoring import build_learn_prompt
from agent.skills.catalog import cosine_similarity
from agent.skills.privacy import SkillPrivacyGate


@dataclass(frozen=True)
class SkillSignal:
    kind: str
    summary: str
    fingerprint: str


class SkillLearningWorkflow:
    """Shared foreground/background procedural-learning intake."""

    def __init__(self, root: str | Path, *, embedder: Callable[[str], list[float]] | None = None):
        self.root = Path(root)
        self.path = self.root.parent / "data" / "skills" / "learning.db"
        self.gate = SkillPrivacyGate()
        self.embedder = embedder
        self._migrate()

    def compose(self, source: str, focus: str = "", *, source_path: str | Path | None = None) -> dict[str, Any]:
        prompt = build_learn_prompt(source, focus, source_path=source_path)
        return {"ok": True, "prompt": prompt, "origin": "foreground", "threshold": "explicit"}

    def record_signal(self, summary: str, *, kind: str, successful: bool = True) -> dict[str, Any]:
        if not successful:
            return {"stored": False, "reason": "unsuccessful"}
        clean = self.gate.sanitize(summary).text
        fingerprint = hashlib.sha256(" ".join(clean.casefold().split()).encode("utf-8")).hexdigest()
        vector = self._embed(clean)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO signals(kind,summary,fingerprint,vector_json,created_at) VALUES(?,?,?,?,?)",
                (kind, clean, fingerprint, json.dumps(vector) if vector else None, datetime.now(timezone.utc).isoformat()),
            )
            signal_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.commit()
        return {"stored": True, "id": signal_id, "fingerprint": fingerprint}

    def record_successful_turn(self, summary: str, *, complex_task: bool) -> dict[str, Any]:
        clean = self.gate.sanitize(summary).text
        with self._connect() as connection:
            connection.execute("INSERT INTO successful_turns(created_at) VALUES(?)", (datetime.now(timezone.utc).isoformat(),))
            connection.commit()
        signal = self.record_signal(clean, kind="successful_complex_task") if complex_task else {"stored": False}
        return {"turns": self.successful_turn_count(), "review_due": self.should_review(), "signal": signal}

    def review_candidates(self, *, minimum_signals: int = 3) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = [dict(row) for row in connection.execute("SELECT * FROM signals WHERE reviewed_at IS NULL ORDER BY id")]
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                group_key = row["fingerprint"]
                vector = json.loads(row["vector_json"]) if row.get("vector_json") else None
                if vector:
                    for existing_key, members in groups.items():
                        anchor_raw = members[0].get("vector_json")
                        if anchor_raw and cosine_similarity(vector, json.loads(anchor_raw)) >= 0.82:
                            group_key = existing_key
                            break
                groups.setdefault(group_key, []).append(row)
            candidates = []
            for fingerprint, members in groups.items():
                if len(members) < minimum_signals:
                    continue
                candidates.append({"fingerprint": fingerprint, "count": len(members), "summary": members[-1]["summary"], "origin": "background_review"})
                connection.executemany("UPDATE signals SET reviewed_at=? WHERE id=?", [(datetime.now(timezone.utc).isoformat(), item["id"]) for item in members])
            connection.commit()
            return candidates

    def successful_turn_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM successful_turns").fetchone()[0])

    def should_review(self) -> bool:
        count = self.successful_turn_count()
        return count > 0 and count % 10 == 0

    def _embed(self, text: str) -> list[float] | None:
        return list(self.embedder(text)) if self.embedder else None

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, summary TEXT NOT NULL, fingerprint TEXT NOT NULL, vector_json TEXT, created_at TEXT NOT NULL, reviewed_at TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS successful_turns(id INTEGER PRIMARY KEY, created_at TEXT NOT NULL)")
            connection.execute("PRAGMA user_version=1")
            connection.commit()
