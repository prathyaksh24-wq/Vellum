"""Per-conversation references to live or snapshotted Vault/Knowledge content."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.obsidian.vault import ObsidianVault
from agent.obsidian.wiki_runtime import get_knowledge_wiki
from agent.privacy.classifier import DataClass, classify


class ConversationContextStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_context (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    ref TEXT NOT NULL,
                    title TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    snapshot_text TEXT,
                    attached_at TEXT NOT NULL,
                    UNIQUE(conversation_id, kind, ref)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS conversation_context_thread ON conversation_context(conversation_id, attached_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def attach(
        self,
        *,
        conversation_id: str,
        kind: str,
        ref: str,
        mode: str,
        vault_root: str | Path,
    ) -> dict[str, Any]:
        clean_conversation = conversation_id.strip()
        clean_kind = kind.strip().casefold()
        clean_ref = ref.strip()
        clean_mode = mode.strip().casefold() or "live"
        if not clean_conversation or clean_kind not in {"vault_note", "wiki_page"} or clean_mode not in {"live", "snapshot"}:
            raise ValueError("A conversation, valid context kind, and live/snapshot mode are required.")
        content, title = self._read(clean_kind, clean_ref, vault_root)
        if not content.strip():
            raise KeyError(clean_ref)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        snapshot = content if clean_mode == "snapshot" else None
        attachment_id = uuid4().hex
        attached_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_context(id,conversation_id,kind,ref,title,mode,content_hash,snapshot_text,attached_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(conversation_id,kind,ref) DO UPDATE SET
                    title=excluded.title, mode=excluded.mode, content_hash=excluded.content_hash,
                    snapshot_text=excluded.snapshot_text, attached_at=excluded.attached_at
                """,
                (attachment_id, clean_conversation, clean_kind, clean_ref, title, clean_mode, digest, snapshot, attached_at),
            )
            row = connection.execute(
                "SELECT * FROM conversation_context WHERE conversation_id=? AND kind=? AND ref=?",
                (clean_conversation, clean_kind, clean_ref),
            ).fetchone()
        return dict(row)

    def list(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,conversation_id,kind,ref,title,mode,content_hash,attached_at FROM conversation_context WHERE conversation_id=? ORDER BY attached_at",
                (conversation_id.strip(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def remove(self, conversation_id: str, attachment_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversation_context WHERE conversation_id=? AND id=?",
                (conversation_id.strip(), attachment_id.strip()),
            )
        return cursor.rowcount > 0

    def clear(self, conversation_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversation_context WHERE conversation_id=?",
                (conversation_id.strip(),),
            )
        return int(cursor.rowcount)

    def resolve(self, conversation_id: str, *, vault_root: str | Path, max_chars: int = 12000) -> dict[str, Any]:
        resolved: list[dict[str, Any]] = []
        remaining = max(1000, int(max_chars))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_context WHERE conversation_id=? ORDER BY attached_at",
                (conversation_id.strip(),),
            ).fetchall()
        for row in rows:
            item = dict(row)
            try:
                if item["mode"] == "snapshot":
                    content = str(item.get("snapshot_text") or "")
                else:
                    content, title = self._read(item["kind"], item["ref"], vault_root)
                    item["title"] = title
            except (KeyError, ValueError, OSError):
                item["status"] = "missing"
                resolved.append(item)
                continue
            excerpt = content[:remaining]
            remaining -= len(excerpt)
            item.update({"status": "ready", "content": excerpt})
            resolved.append(item)
            if remaining <= 0:
                break
        ready = [item for item in resolved if item.get("status") == "ready"]
        context = "\n\n".join(
            f"## {item['title']}\nReference: {item['kind']}:{item['ref']} ({item['mode']})\n{item['content']}"
            for item in ready
        )
        return {"attachments": resolved, "context": context}

    @staticmethod
    def _read(kind: str, ref: str, vault_root: str | Path) -> tuple[str, str]:
        if kind == "vault_note":
            vault = ObsidianVault(vault_root)
            target = vault._safe_relative(ref)
            if target.suffix.casefold() != ".md" or not target.is_file():
                raise KeyError(ref)
            content = target.read_text(encoding="utf-8", errors="ignore")
            if is_sensitive_context(ref, content):
                raise ValueError("Sensitive Vault notes cannot be attached to model context.")
            title = next((line.lstrip("# ").strip() for line in content.splitlines() if line.startswith("# ")), target.stem)
            return content, title
        page = get_knowledge_wiki().read_page(ref)
        content = str(page.get("content") or "")
        if is_sensitive_context(str(page.get("title") or ref), content):
            raise ValueError("Sensitive wiki pages cannot be attached to model context.")
        return content, str(page.get("title") or ref)


def is_sensitive_context(ref: str, content: str) -> bool:
    combined = f"{ref}\n{content}"
    data_class, _reason = classify(combined)
    if data_class == DataClass.RED:
        return True
    if re.search(r"(?:^|[/\\._ -])(?:api[ _-]?keys?|secrets?|passwords?|credentials?|\.env)(?:$|[/\\._ -])", ref, re.IGNORECASE):
        return True
    return bool(
        re.search(
            r"(?im)^\s*[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET|CLIENT_SECRET|AUTH_TOKEN|CT0)\s*=\s*\S+",
            content,
        )
    )
