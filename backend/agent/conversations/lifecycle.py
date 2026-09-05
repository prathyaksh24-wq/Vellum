"""Canonical persistence and lifecycle operations for Vellum conversations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable

from agent.conversations.library import organization_id, organize_conversation


_PATH_LOCKS: dict[str, RLock] = {}
_PATH_LOCKS_GUARD = Lock()


def _path_lock(path: Path) -> RLock:
    key = str(path.resolve(strict=False)).casefold()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, RLock())


class ConversationLifecycleError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ConversationLifecycle:
    """Own conversation mutations shared by HTTP and App Action adapters."""

    def __init__(
        self,
        *,
        path: Path,
        clock: Callable[[], datetime] | None = None,
        indexer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        projector: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        archiver: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        delete_fts: Callable[[str], int] | None = None,
        clear_context: Callable[[str], int] | None = None,
        delete_session: Callable[[str], None] | None = None,
        rename_session: Callable[[str, str], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._indexer = indexer or (lambda _conversation: {})
        self._projector = projector or (lambda _conversation: {})
        self._archiver = archiver or (lambda _conversation: {"ok": True})
        self._delete_fts = delete_fts or (lambda _thread_id: 0)
        self._clear_context = clear_context or (lambda _thread_id: 0)
        self._delete_session = delete_session or (lambda _thread_id: None)
        self._rename_session = rename_session or (lambda _thread_id, _title: None)
        self._lock = _path_lock(self.path)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            conversations = payload.get("conversations") if isinstance(payload, dict) else payload
            if not isinstance(conversations, list):
                return []
            return [self._normalize_loaded(item) for item in conversations if isinstance(item, dict)]

    def replace_all(self, conversations: list[dict[str, Any]]) -> None:
        with self._lock:
            self._write([
                self._normalize_loaded(item)
                for item in conversations
                if isinstance(item, dict)
            ])

    def get(self, conversation_id: str) -> dict[str, Any]:
        clean_id = str(conversation_id or "").strip()
        for conversation in self.list():
            if clean_id in {
                str(conversation.get("id") or ""),
                str(conversation.get("thread_id") or ""),
            }:
                return conversation
        raise ConversationLifecycleError("CONVERSATION_NOT_FOUND", "Conversation not found.")

    def resolve(self, reference: str) -> dict[str, Any]:
        clean = " ".join(str(reference or "").split()).strip()
        if not clean:
            raise ConversationLifecycleError("CONVERSATION_TARGET_REQUIRED", "Name the conversation to update.")
        conversations = self.list()
        direct = [
            item for item in conversations
            if clean in {
                str(item.get("id") or ""),
                str(item.get("thread_id") or ""),
            }
        ]
        if direct:
            return direct[0]
        matches = [
            item for item in conversations
            if str(item.get("title") or "").strip().casefold() == clean.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ConversationLifecycleError(
                "AMBIGUOUS_CONVERSATION_REFERENCE",
                "More than one conversation has that title.",
                details={"candidates": [str(item.get("id")) for item in matches]},
            )
        raise ConversationLifecycleError("CONVERSATION_NOT_FOUND", "Conversation not found.")

    def save(self, conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        clean_id = str(conversation_id or "").strip()
        if not clean_id:
            raise ConversationLifecycleError("INVALID_CONVERSATION_ID", "conversation_id is required.")
        with self._lock:
            conversations = self.list()
            current = next((item for item in conversations if str(item.get("id")) == clean_id), None)
            record = self._normalize(clean_id, payload, current=current)
            changed = current is None or self._comparable(current) != self._comparable(record)
            if current is not None:
                record["revision"] = int(current.get("revision", 0)) + (1 if changed else 0)
                if not changed:
                    record["updated_at"] = current.get("updated_at")
            remaining = [item for item in conversations if str(item.get("id")) != clean_id]
            if changed:
                self._write([record, *remaining])
            effects = self._update_effects(record, current) if changed else self._empty_update_effects()
            return {
                "conversation": record,
                "previous_conversation": current,
                "changed": changed,
                **effects,
            }

    def patch(
        self,
        conversation_id: str,
        values: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            conversations = self.list()
            for index, conversation in enumerate(conversations):
                if str(conversation.get("id")) != conversation_id:
                    continue
                current_revision = int(conversation.get("revision", 0))
                if expected_revision is not None and expected_revision != current_revision:
                    raise ConversationLifecycleError(
                        "STALE_ACTION_TARGET",
                        "The conversation changed before this action could be applied.",
                    )
                updated = self._normalize(conversation_id, {**conversation, **values}, current=conversation)
                changed = self._comparable(conversation) != self._comparable(updated)
                updated["revision"] = current_revision + (1 if changed else 0)
                if not changed:
                    updated["updated_at"] = conversation.get("updated_at")
                conversations[index] = updated
                if changed:
                    self._write(conversations)
                effects = self._update_effects(updated, conversation) if changed else self._empty_update_effects()
                return {
                    "conversation": updated,
                    "previous_conversation": conversation,
                    "changed": changed,
                    **effects,
                }
        raise ConversationLifecycleError("CONVERSATION_NOT_FOUND", "Conversation not found.")

    def set_organization(
        self,
        conversation_id: str,
        organization: dict[str, Any] | None,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            conversations = self.list()
            for index, conversation in enumerate(conversations):
                if str(conversation.get("id")) != conversation_id:
                    continue
                current_revision = int(conversation.get("revision", 0))
                if expected_revision is not None and expected_revision != current_revision:
                    raise ConversationLifecycleError(
                        "STALE_ACTION_TARGET",
                        "The conversation changed before this action could be applied.",
                    )
                base = dict(conversation)
                if organization is None or organization.get("assignment") == "automatic":
                    base.pop("organization", None)
                else:
                    values = dict(organization)
                    space_label = str(values.get("space_label") or "").strip()
                    space_id = str(values.get("space_id") or "").strip()
                    if space_label and not space_id:
                        values["space_id"] = organization_id(space_label)
                    elif space_id and not space_label:
                        values["space_label"] = space_id.replace("-", " ").title()
                    topic_label = str(values.get("topic_label") or "").strip()
                    topic_id = str(values.get("topic_id") or "").strip()
                    if topic_label and not topic_id:
                        values["topic_id"] = organization_id(topic_label)
                    elif topic_id and not topic_label:
                        values["topic_label"] = topic_id.replace("-", " ").title()
                    values["assignment"] = "manual"
                    values["confidence"] = 1.0
                    base["organization"] = values
                updated = self._normalize(conversation_id, base, current=conversation)
                changed = self._comparable(conversation) != self._comparable(updated)
                updated["revision"] = current_revision + (1 if changed else 0)
                if not changed:
                    updated["updated_at"] = conversation.get("updated_at")
                conversations[index] = updated
                if changed:
                    self._write(conversations)
                effects = self._update_effects(updated, conversation) if changed else self._empty_update_effects()
                return {
                    "conversation": updated,
                    "previous_conversation": conversation,
                    "changed": changed,
                    **effects,
                }
        raise ConversationLifecycleError("CONVERSATION_NOT_FOUND", "Conversation not found.")

    def delete(
        self,
        conversation_id: str,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            conversations = self.list()
            for conversation in conversations:
                if str(conversation.get("id")) != conversation_id:
                    continue
                current_revision = int(conversation.get("revision", 0))
                if expected_revision is not None and expected_revision != current_revision:
                    raise ConversationLifecycleError(
                        "STALE_ACTION_TARGET",
                        "The conversation changed before this action could be applied.",
                    )
                self._write([
                    item for item in conversations
                    if str(item.get("id")) != conversation_id
                ])
                thread_id = str(conversation.get("thread_id") or conversation.get("id") or conversation_id)
                projection = self._archiver(conversation)
                deleted_fts = self._delete_fts(thread_id)
                deleted_context = self._clear_context(thread_id)
                self._delete_session(thread_id)
                return {
                    "deleted": True,
                    "conversation": conversation,
                    "changed": True,
                    "deleted_fts_rows": deleted_fts,
                    "deleted_context_refs": deleted_context,
                    "obsidian_projection": projection,
                }
        raise ConversationLifecycleError("CONVERSATION_NOT_FOUND", "Conversation not found.")

    def _write(self, conversations: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps({"conversations": conversations}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _update_effects(
        self,
        conversation: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if previous is None or previous.get("title") != conversation.get("title"):
            thread_id = str(conversation.get("thread_id") or conversation.get("id") or "")
            self._rename_session(thread_id, str(conversation.get("title") or "New chat"))
        return {
            "memory_index": self._indexer(conversation),
            "obsidian_projection": self._projector(conversation),
        }

    @staticmethod
    def _empty_update_effects() -> dict[str, Any]:
        return {"memory_index": {}, "obsidian_projection": {}}

    def _normalize(
        self,
        conversation_id: str,
        payload: dict[str, Any],
        *,
        current: dict[str, Any] | None,
    ) -> dict[str, Any]:
        record = dict(payload)
        record["id"] = str(record.get("id") or conversation_id)
        record["thread_id"] = str(record.get("thread_id") or record["id"])
        record["title"] = str(record.get("title") or "New chat")
        record["created"] = str(record.get("created") or (current or {}).get("created") or "Today")
        record["pinned"] = bool(record.get("pinned", False))
        record["archived"] = bool(record.get("archived", False))
        record["projectId"] = record.get("projectId")
        record["messages"] = record.get("messages") if isinstance(record.get("messages"), list) else []
        record["revision"] = int((current or {}).get("revision", record.get("revision", 0)) or 0)
        record["updated_at"] = self._now().isoformat(timespec="seconds")
        record["organization"] = organize_conversation(record)
        return record

    @staticmethod
    def _normalize_loaded(record: dict[str, Any]) -> dict[str, Any]:
        value = dict(record)
        value["revision"] = max(0, int(value.get("revision", 0) or 0))
        value["pinned"] = bool(value.get("pinned", False))
        value["archived"] = bool(value.get("archived", False))
        return value

    @staticmethod
    def _comparable(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key not in {"revision", "updated_at"}}

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
