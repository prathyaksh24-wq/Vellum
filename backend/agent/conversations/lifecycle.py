"""Canonical persistence and lifecycle operations for Vellum conversations."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from contextlib import suppress
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from threading import Lock, RLock
from time import sleep
from typing import Any, Callable
from uuid import uuid4

from agent.conversations.library import organization_id, organize_conversation
from agent.contracts.conversations import ConversationProject


_PATH_LOCKS: dict[str, RLock] = {}
_PATH_LOCKS_GUARD = Lock()
_READ_SNAPSHOTS: OrderedDict[str, tuple[tuple[int, int, int], dict[str, Any]]] = OrderedDict()
_READ_SNAPSHOTS_LOCK = RLock()
# Parsed per-chat message files keyed by file identity, so re-reading the index
# after a write only parses the chats that actually changed.
_MESSAGE_FILES: dict[str, tuple[tuple[int, int], list[Any]]] = {}
_MESSAGE_FILES_LOCK = Lock()
# Storage v2: conversations.json is a small index of chat details; each chat's
# messages live in conversations/<id>.json and only changed chats are written.
STORAGE_VERSION = 2
_SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,99}")


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
        delete_fts: Callable[[str], int] | None = None,
        delete_session: Callable[[str], None] | None = None,
        rename_session: Callable[[str, str], None] | None = None,
        conversation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._indexer = indexer or (lambda _conversation: {})
        self._delete_fts = delete_fts or (lambda _thread_id: 0)
        self._delete_session = delete_session or (lambda _thread_id: None)
        self._rename_session = rename_session or (lambda _thread_id, _title: None)
        self._conversation_id_factory = conversation_id_factory or (lambda: f"chat_{uuid4().hex}")
        self._lock = _path_lock(self.path)

    def _messages_dir(self) -> Path:
        return self.path.with_name(self.path.stem)

    def _message_file(self, conversation_id: Any) -> Path:
        cid = str(conversation_id or "")
        # Windows paths are case-insensitive, so only lower-case ids are used
        # verbatim; anything else gets a stable hashed name.
        name = cid if _SAFE_NAME.fullmatch(cid) else "id-" + sha256(cid.encode("utf-8")).hexdigest()[:40]
        return self._messages_dir() / f"{name}.json"

    def _load_messages(self, conversation_id: Any) -> list[Any]:
        target = self._message_file(conversation_id)
        try:
            stat = target.stat()
        except OSError:
            return []
        key = str(target)
        signature = (stat.st_mtime_ns, stat.st_size)
        with _MESSAGE_FILES_LOCK:
            cached = _MESSAGE_FILES.get(key)
        if cached and cached[0] == signature:
            return cached[1]
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        messages = loaded.get("messages") if isinstance(loaded, dict) else loaded
        messages = messages if isinstance(messages, list) else []
        with _MESSAGE_FILES_LOCK:
            _MESSAGE_FILES[key] = (signature, messages)
        return messages

    def _read_payload(self) -> dict[str, Any]:
        """Private, file-versioned read cache; the JSON writer remains authoritative."""
        key = str(self.path.resolve(strict=False)).casefold()
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            with _READ_SNAPSHOTS_LOCK:
                cached = _READ_SNAPSHOTS.get(key)
            if cached and cached[0] == signature:
                return cached[1]
            payload = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        payload = {'conversations': payload} if isinstance(payload, list) else payload
        if not isinstance(payload, dict):
            return {}
        if payload.get('storage_version') == STORAGE_VERSION and isinstance(payload.get('conversations'), list):
            rows = []
            for meta in payload['conversations']:
                if not isinstance(meta, dict):
                    continue
                record = {k: v for k, v in meta.items() if k != 'message_count'}
                if 'message_count' in meta:
                    record['messages'] = self._load_messages(meta.get('id'))
                rows.append(record)
            payload = {**payload, 'conversations': rows}
        elif isinstance(payload.get('conversations'), list) and self._messages_dir().is_dir():
            # An older build may have rewritten the index without messages;
            # recover them from the per-chat files instead of losing them.
            payload = {**payload, 'conversations': [
                {**row, 'messages': self._load_messages(row.get('id'))}
                if isinstance(row, dict) and 'messages' not in row and self._message_file(row.get('id')).is_file() else row
                for row in payload['conversations']
            ]}
        with _READ_SNAPSHOTS_LOCK:
            _READ_SNAPSHOTS[key] = (signature, payload)
            _READ_SNAPSHOTS.move_to_end(key)
            while len(_READ_SNAPSHOTS) > 4:
                _READ_SNAPSHOTS.popitem(last=False)
        return payload

    def prepare_storage(self) -> bool:
        """Convert a single-file history to per-chat files and warm the cache.

        Returns True when a conversion ran. A backup of the original file is
        kept as conversations.v1-backup.json.
        """
        with self._lock:
            payload = self._read_payload()
            if payload.get('storage_version') == STORAGE_VERSION or not self.path.exists():
                return False
            self._write(self.list())
            self._read_payload()
            return True

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            conversations = self._read_payload().get('conversations', [])
            if not isinstance(conversations, list):
                return []
            return [self._normalize_loaded(deepcopy(item)) for item in conversations if isinstance(item, dict)]

    def list_view(self) -> list[dict[str, Any]]:
        """Read-only rows for projections such as the chat list and search.

        Rows share nested data with the read cache, so callers must not mutate
        them; mutations go through list(). Skipping the deep copy keeps the
        sidebar and library fast when the history is tens of megabytes.
        """
        with self._lock:
            conversations = self._read_payload().get('conversations', [])
            if not isinstance(conversations, list):
                return []
            return [self._normalize_loaded(item) for item in conversations if isinstance(item, dict)]

    def projects(self) -> list[dict[str, Any]]:
        """Conversation folders share the conversation writer, not vault projects."""
        with self._lock:
            rows = self._read_payload().get('projects', [])
            if not isinstance(rows, list):
                return []
            result = []
            for row in rows:
                try:
                    result.append(ConversationProject.model_validate(row).model_dump())
                except (ValueError, TypeError):
                    continue
            return result

    def change_project(self, operation: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            projects, conversations = self.projects(), self.list()
            project = None
            if operation != 'create':
                project = next((row for row in projects if row['id'] == values.get('project_id')), None)
                if project is None:
                    raise ConversationLifecycleError('PROJECT_NOT_FOUND', 'Project not found.')
                if values.get('target_revision') is not None and values['target_revision'] != project['revision']:
                    raise ConversationLifecycleError('STALE_ACTION_TARGET', 'The project changed. Refresh and try again.')
            now = self._clock().isoformat()
            changed_conversations = []
            changed_previous = {}
            if operation in {'create', 'update'}:
                patch = values.get('patch', {}) if operation == 'update' else values
                record = dict(project or {'id': 'project_' + uuid4().hex, 'created_at': now})
                if 'name' in patch and not isinstance(patch['name'], str):
                    raise ConversationLifecycleError('INVALID_PROJECT_NAME', 'Project name must be text.')
                if 'name' in patch:
                    record['name'] = ' '.join(patch['name'].split())
                for key in ('pinned', 'memory'):
                    if key in patch:
                        record[key] = patch[key]
                record.update(updated_at=now, revision=(project['revision'] + 1 if project else 0))
                record = ConversationProject.model_validate(record).model_dump()
                projects = [record if row['id'] == record['id'] else row for row in projects] if project else [record, *projects]
                project = record
            elif operation == 'remove':
                projects = [row for row in projects if row['id'] != project['id']]
                for index, conversation in enumerate(conversations):
                    if conversation.get('projectId') != project['id']:
                        continue
                    updated = self._normalize(conversation['id'], {**conversation, 'projectId': None}, current=conversation)
                    updated['revision'] = int(conversation.get('revision', 0)) + 1
                    changed_previous[updated['id']] = conversation
                    conversations[index] = updated
                    changed_conversations.append(updated)
            else:
                raise ConversationLifecycleError('INVALID_PROJECT_OPERATION', 'Unknown project operation.')
            self._write(conversations, projects=projects)
            for conversation in changed_conversations:
                self._update_effects(conversation, changed_previous[conversation['id']])
            return {'projects': projects, 'project': project, 'conversations': changed_conversations}

    def replace_all(self, conversations: list[dict[str, Any]]) -> None:
        with self._lock:
            self._write([
                self._normalize_loaded(item)
                for item in conversations
                if isinstance(item, dict)
            ])

    def get(self, conversation_id: str) -> dict[str, Any]:
        clean_id = str(conversation_id or "").strip()
        with self._lock:
            for conversation in self._read_payload().get('conversations', []):
                if isinstance(conversation, dict) and clean_id in {
                    str(conversation.get("id") or ""), str(conversation.get("thread_id") or ""),
                }:
                    return self._normalize_loaded(deepcopy(conversation))
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
            # Membership changes belong to patch/App Actions. An in-flight message
            # autosave must not move a chat back after a sidebar assignment.
            payload = {**payload, 'projectId': current.get('projectId')} if current else payload
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

    def deliver_automation(self, *, delivery_id: str, text: str, name: str,
                           thread_id: str = "", project_id: str | None = None,
                           instructions: str = "", new_chat_id: str = "") -> bool:
        """Atomically append an idempotent automation message using this owner."""
        with self._lock:
            conversations = self.list()
            chat_id = new_chat_id or delivery_id
            target = next((item for item in conversations if str(item.get("thread_id")) == thread_id), None) if thread_id else \
                next((item for item in conversations if item.get("id") == chat_id), None)
            if thread_id and target is None:
                raise ConversationLifecycleError("CONVERSATION_NOT_FOUND", "Automation destination conversation is unavailable.")
            if target and any(message.get("id") == delivery_id for message in target.get("messages", [])):
                return False
            if target:
                payload = deepcopy(target)
            else:
                payload = {"thread_id": chat_id, "title": name, "messages": [], "projectId": project_id}
            if instructions:
                payload.setdefault("messages", []).append({"role": "user", "text": instructions, "id": f"{delivery_id}-prompt"})
            payload.setdefault("messages", []).append({"role": "assistant", "text": text, "id": delivery_id})
            self.save(str(target["id"]) if target else chat_id, payload)
            return True

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

    def edit_user_message(
        self, conversation_id: str, message_id: str, text: str, *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Correct a saved request through the conversation writer; retain its sent time."""
        if not message_id or not isinstance(text, str) or not text.strip() or len(text) > 100_000:
            raise ConversationLifecycleError("INVALID_MESSAGE_EDIT", "Enter a message of 1 to 100,000 characters.")
        with self._lock:
            conversation = self.get(conversation_id)
            messages = deepcopy(conversation.get("messages") or [])
            message = next((row for row in messages if str(row.get("id")) == message_id), None)
            if message is None or message.get("role") != "user":
                raise ConversationLifecycleError("USER_MESSAGE_NOT_FOUND", "The request is no longer available to edit.")
            if message.get("transcribing") or any(row.get("streaming") for row in messages):
                raise ConversationLifecycleError("CONVERSATION_BUSY", "Wait for the current response before editing a request.")
            if message.get("text") != text:
                message["text"] = text
                message["edited_at"] = self._now().isoformat(timespec="seconds")
            return self.patch(conversation_id, {"messages": messages}, expected_revision=expected_revision)

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
                deleted_fts = self._delete_fts(thread_id)
                self._delete_session(thread_id)
                return {
                    "deleted": True,
                    "conversation": conversation,
                    "changed": True,
                    "deleted_fts_rows": deleted_fts,
                }
        raise ConversationLifecycleError("CONVERSATION_NOT_FOUND", "Conversation not found.")

    def fork(
        self,
        conversation_id: str,
        *,
        through_message_id: str = "",
        title: str = "",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            source = self.get(conversation_id)
            current_revision = int(source.get("revision", 0))
            if expected_revision is not None and expected_revision != current_revision:
                raise ConversationLifecycleError(
                    "STALE_ACTION_TARGET",
                    "The conversation changed before it could be forked.",
                )
            source_messages = source.get("messages") if isinstance(source.get("messages"), list) else []
            boundary = str(through_message_id or "").strip()
            messages = source_messages
            if boundary:
                boundary_index = next(
                    (index for index, message in enumerate(source_messages)
                     if isinstance(message, dict) and str(message.get("id") or "") == boundary),
                    None,
                )
                if boundary_index is None:
                    raise ConversationLifecycleError(
                        "FORK_BOUNDARY_NOT_FOUND",
                        "The selected message is not part of this conversation.",
                    )
                messages = source_messages[: boundary_index + 1]

            existing_ids = {
                value
                for item in self.list()
                for value in (str(item.get("id") or ""), str(item.get("thread_id") or ""))
                if value
            }
            destination_id = ""
            for _attempt in range(10):
                candidate = str(self._conversation_id_factory() or "").strip()
                if candidate and candidate not in existing_ids:
                    destination_id = candidate
                    break
            if not destination_id:
                raise ConversationLifecycleError("FORK_ID_UNAVAILABLE", "A new conversation ID could not be allocated.")

            source_title = str(source.get("title") or "New chat")
            requested_title = " ".join(str(title or "").split())
            fork_title = (requested_title or f"{source_title} (fork)")[:160]
            record = deepcopy(source)
            record.update({
                "id": destination_id,
                "thread_id": destination_id,
                "title": fork_title,
                "created": "Today",
                "pinned": False,
                "archived": False,
                "messages": deepcopy(messages),
                "revision": 0,
                "fork": {
                    "source_conversation_id": str(source.get("id") or conversation_id),
                    "source_thread_id": str(source.get("thread_id") or source.get("id") or conversation_id),
                    "through_message_id": boundary or None,
                    "message_count": len(messages),
                },
            })
            record.pop("updated_at", None)
            mutation = self.save(destination_id, record)
            destination = mutation["conversation"]
            return {
                **mutation,
                "source_conversation": source,
                "fork_boundary": boundary or None,
            }

    @staticmethod
    def _replace_file(target: Path, text: str) -> None:
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            for attempt in range(7):
                try:
                    temporary.replace(target)
                    break
                except PermissionError:
                    # A Windows reader or scanner can briefly deny replacement.
                    # Keep the old file intact and bound the wait to 1.6 seconds.
                    if attempt == 6:
                        raise
                    sleep(.025 * (2 ** attempt))
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _write(self, conversations: list[dict[str, Any]], *, projects: list[dict[str, Any]] | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current = self._read_payload()
        migrating = current.get('storage_version') != STORAGE_VERSION
        if migrating and self.path.exists():
            # Keep the original single-file history once, before the first v2 write.
            backup = self.path.with_name(f"{self.path.stem}.v1-backup.json")
            if not backup.exists():
                shutil.copy2(self.path, backup)
        previous = {str(item.get('id') or ''): item for item in current.get('conversations', []) if isinstance(item, dict)}
        directory = self._messages_dir()
        directory.mkdir(parents=True, exist_ok=True)
        index_rows: list[dict[str, Any]] = []
        kept_files: set[str] = set()
        try:
            for record in conversations:
                if not isinstance(record, dict):
                    continue
                meta = {key: value for key, value in record.items() if key != 'messages'}
                if 'messages' in record:
                    messages = record.get('messages') if isinstance(record.get('messages'), list) else []
                    meta['message_count'] = len(messages)
                    cid = str(record.get('id') or '')
                    target = self._message_file(cid)
                    kept_files.add(target.name.casefold())
                    old = previous.get(cid)
                    # Only chats whose messages changed are written.
                    if migrating or old is None or old.get('messages') != messages or not target.exists():
                        self._replace_file(target, json.dumps({'id': cid, 'messages': messages}, ensure_ascii=False, separators=(',', ':')))
                index_rows.append(meta)
            payload = {key: value for key, value in current.items() if key != 'conversations'}
            payload['storage_version'] = STORAGE_VERSION
            payload['conversations'] = index_rows
            if projects is not None:
                payload['projects'] = projects
            self._replace_file(self.path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        finally:
            with _READ_SNAPSHOTS_LOCK:
                _READ_SNAPSHOTS.pop(str(self.path.resolve(strict=False)).casefold(), None)
        # Remove message files of deleted chats only after the index stops naming them.
        for removed in set(previous) - {str(row.get('id') or '') for row in index_rows}:
            target = self._message_file(removed)
            if target.name.casefold() not in kept_files:
                with suppress(OSError):
                    target.unlink(missing_ok=True)

    def _update_effects(
        self,
        conversation: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if conversation.get("temporary_side_chat") and not conversation.get("messages"):
            return self._empty_update_effects()
        if previous is None or previous.get("title") != conversation.get("title"):
            thread_id = str(conversation.get("thread_id") or conversation.get("id") or "")
            self._rename_session(thread_id, str(conversation.get("title") or "New chat"))
        return {
            "memory_index": self._indexer(conversation),
        }

    @staticmethod
    def _empty_update_effects() -> dict[str, Any]:
        return {"memory_index": {}}

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
