"""Lossless local store for tool results that leave the model's working prompt.

Tool results are trimmed (MCP projections) or removed (compaction) to keep the
prompt inside its budget. The full original is kept here so the model can page
back through it with `conversation_history(evidence_id=...)` instead of
re-running the tool or losing the evidence.

Ownership and privacy:
- Local SQLite beside the conversation checkpoints; nothing here is uploaded.
- Each record belongs to one conversation thread and is readable only from it.
  Results captured below the thread boundary (inside an MCP call) start
  unclaimed and become readable once the graph's tool step claims them for the
  thread; unclaimed records expire after an hour.
- Deleting a conversation deletes its evidence (SessionsReader.delete).
  Evidence older than 90 days is removed, matching conversation history retention.
- Retrieved text is returned as untrusted tool evidence, exactly like the
  original tool result, so it follows the same disclosure path to the model.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAX_CHARS = 2 * 1024 * 1024
PAGE_CHARS = 6000
RETENTION_DAYS = 90
UNCLAIMED_HOURS = 1
EVIDENCE_ID = re.compile(r"\bev_[A-Za-z0-9_-]{20,40}\b")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  thread_id TEXT,
  tool TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  chars INTEGER NOT NULL,
  content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_thread ON evidence(thread_id, created_at);
"""
_stores: dict[Path, "EvidenceStore"] = {}
_stores_lock = threading.Lock()


def default_path() -> Path:
    from agent.config import REPO_ROOT
    return Path(REPO_ROOT) / "data" / "memory" / "evidence.db"


def evidence_store(path: Path | None = None) -> "EvidenceStore":
    path = Path(path or default_path())
    with _stores_lock:
        if path not in _stores:
            _stores[path] = EvidenceStore(path)
        return _stores[path]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._pruned_at: datetime | None = None

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def put(self, content: str, *, tool: str = "", thread_id: str | None = None) -> str:
        """Save one tool result; returns its evidence id."""
        evidence_id = "ev_" + secrets.token_urlsafe(18)
        text = str(content)[:MAX_CHARS]
        with self._connect() as conn:
            conn.execute("INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?)",
                         (evidence_id, thread_id or None, str(tool)[:120], _now().isoformat(), len(text), text))
        self.prune()
        return evidence_id

    def claim(self, evidence_ids: list[str], thread_id: str) -> int:
        """Bind unclaimed results to the conversation that received them."""
        if not evidence_ids or not thread_id:
            return 0
        marks = ",".join("?" for _ in evidence_ids)
        with self._connect() as conn:
            return conn.execute(f"UPDATE evidence SET thread_id = ? WHERE thread_id IS NULL AND evidence_id IN ({marks})",
                                (thread_id, *evidence_ids)).rowcount

    def read(self, evidence_id: str, thread_id: str, *, page: int = 1, query: str = "",
             page_chars: int = PAGE_CHARS) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE evidence_id = ? AND thread_id = ?",
                               (evidence_id, thread_id)).fetchone()
        if row is None:
            return {"ok": False, "error": "This evidence is not available in the current conversation."}
        content = row["content"]
        pages = max(1, -(-len(content) // page_chars))
        result: dict[str, Any] = {"ok": True, "evidence_id": evidence_id, "tool": row["tool"],
                                  "captured_at": row["created_at"], "total_chars": len(content), "pages": pages,
                                  "untrusted_tool_evidence": True}
        if query.strip():
            result["matches"] = _matches(content, query, limit=page_chars)
            return result
        page = min(max(int(page), 1), pages)
        start = (page - 1) * page_chars
        result.update(page=page, text=content[start:start + page_chars],
                      next_page=page + 1 if page < pages else None)
        return result

    def delete_thread(self, thread_id: str) -> int:
        with self._connect() as conn:
            return conn.execute("DELETE FROM evidence WHERE thread_id = ?", (thread_id,)).rowcount

    def prune(self, *, now: datetime | None = None, force: bool = False) -> int:
        now = now or _now()
        if not force and self._pruned_at and now - self._pruned_at < timedelta(hours=1):
            return 0
        self._pruned_at = now
        with self._connect() as conn:
            removed = conn.execute("DELETE FROM evidence WHERE created_at < ?",
                                   ((now - timedelta(days=RETENTION_DAYS)).isoformat(),)).rowcount
            removed += conn.execute("DELETE FROM evidence WHERE thread_id IS NULL AND created_at < ?",
                                    ((now - timedelta(hours=UNCLAIMED_HOURS)).isoformat(),)).rowcount
        return removed


def _matches(content: str, query: str, *, limit: int) -> list[dict[str, Any]]:
    """Keyword-ranked passages with their character offsets, bounded to `limit`."""
    terms = {term for term in re.findall(r"\w{3,}", query.casefold())}
    passages, position = [], 0
    for part in re.split(r"(\n+)", content):
        if part.strip():
            passages.append((position, part))
        position += len(part)
    ranked = sorted(passages, key=lambda item: -len(terms & set(re.findall(r"\w{3,}", item[1].casefold()))))
    chosen, used = [], 0
    for offset, text in ranked:
        if not terms & set(re.findall(r"\w{3,}", text.casefold())) or used >= limit:
            break
        fragment = text[:max(0, limit - used)]
        chosen.append({"offset": offset, "text": fragment})
        used += len(fragment)
    return sorted(chosen, key=lambda item: item["offset"])


def attach_evidence(projected: str, raw: str, *, tool: str, structured: bool) -> str:
    """Keep the full original of a trimmed MCP result and point the projection at it.

    Called below the thread boundary, so the record starts unclaimed; the
    graph's tool step claims it for the conversation that receives the result.
    """
    if not raw or raw == projected:
        return projected
    try:
        evidence_id = evidence_store().put(raw, tool=tool)
    except (OSError, sqlite3.Error):
        return projected  # the projection alone is still a correct, bounded result
    note = "Full original kept locally; page it with conversation_history(evidence_id=...)."
    if structured:
        try:
            value = json.loads(projected)
        except ValueError:
            value = None
        if isinstance(value, dict):
            value.update(evidence_id=evidence_id, evidence_note=note)
            return json.dumps(value, ensure_ascii=False)
    closing = "</MCP_RESULT_SUMMARY>"
    line = f"evidence_id: {evidence_id} ({note})"
    if projected.rstrip().endswith(closing):
        return projected.rstrip()[:-len(closing)] + line + "\n" + closing
    return projected + "\n" + line
