"""Thin local Honcho client wrapper.

The self-hosted Honcho service is optional at import time so tests and offline
developer sessions can run before the container and SDK are installed.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.request import urlopen

try:
    from honcho import Honcho
except Exception:  # pragma: no cover - depends on optional SDK
    Honcho = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class HonchoMemory:
    def __init__(self, *, base_url: str, app_id: str, user_id: str, conversations_path: Path | None = None):
        self.base_url = base_url
        self.app_id = app_id
        self.user_id = user_id
        if conversations_path is None:
            from agent.config import REPO_ROOT
            conversations_path = REPO_ROOT / "data" / "ui" / "conversations.json"
        self.conversations_path = Path(conversations_path)
        self._client = None
        self._app = None
        self._user = None

    @property
    def available(self) -> bool:
        if Honcho is None:
            return False
        try:
            with urlopen(f"{self.base_url.rstrip('/')}/health", timeout=1) as response:
                return response.status == 200
        except Exception:
            return False

    def _ensure(self) -> Any | None:
        if Honcho is None:
            return None
        if self._client is not None:
            return self._client
        try:
            self._client = Honcho(
                base_url=self.base_url,
                workspace_id=self.app_id,
                timeout=120,
            )
            if hasattr(self._client, "peer") and hasattr(self._client, "session"):
                self._user = self._client.peer(self.user_id)
                return self._client

            # Compatibility with Honcho 1.x clients.
            apps = self._client.apps
            self._app = getattr(apps, "get_or_create", lambda name: None)(name=self.app_id)
            app_id = getattr(self._app, "id", self.app_id)
            users = self._client.apps.users
            self._user = getattr(users, "get_or_create", lambda **_: None)(
                app_id=app_id,
                name=self.user_id,
            )
            return self._client
        except Exception as exc:
            logger.warning("[HONCHO] Unavailable: %s", exc)
            self._client = None
            return None

    def get_or_create_session(self, session_id: str) -> str:
        client = self._ensure()
        if client is None:
            return session_id
        if hasattr(client, "session"):
            try:
                client.session(session_id)
                return session_id
            except Exception as exc:
                logger.warning("[HONCHO] Session unavailable: %s", exc)
                return session_id
        try:
            app_id = getattr(self._app, "id", self.app_id)
            user_id = getattr(self._user, "id", self.user_id)
            sessions = client.apps.users.sessions
            session = getattr(sessions, "get_or_create", lambda **_: None)(
                app_id=app_id,
                user_id=user_id,
                name=session_id,
            )
            return str(getattr(session, "id", session_id))
        except Exception as exc:
            logger.warning("[HONCHO] Session unavailable: %s", exc)
            return session_id

    def add_message(self, session_id: str, *, content: str, role: str) -> None:
        client = self._ensure()
        if client is None:
            return None
        if hasattr(client, "peer") and hasattr(client, "session"):
            try:
                peer_name = self.user_id if role == "user" else "vellum"
                peer = client.peer(peer_name)
                session = client.session(session_id)
                session.add_messages([peer.message(content)])
                return None
            except Exception as exc:
                logger.warning("[HONCHO] Message skipped: %s", exc)
                return None
        try:
            app_id = getattr(self._app, "id", self.app_id)
            user_id = getattr(self._user, "id", self.user_id)
            client.apps.users.sessions.messages.create(
                app_id=app_id,
                user_id=user_id,
                session_id=session_id,
                content=content,
                role=role,
            )
        except Exception as exc:
            logger.warning("[HONCHO] Message skipped: %s", exc)
        return None

    def _profile_session_ids(self) -> list[str]:
        """Constrain derived portraits to extant canonical, non-temporary chats."""
        from agent.conversations.lifecycle import ConversationLifecycle
        sessions = []
        for conversation in ConversationLifecycle(path=self.conversations_path).list():
            messages = conversation.get("messages") or []
            first_user = next((str(message.get("text") or message.get("content") or "")
                for message in messages if message.get("role") == "user"), "")
            if not first_user or re.search(r"\b(?:for this chat only|demonstration project)\b", first_user, re.I):
                continue
            thread = str(conversation.get("thread_id") or conversation.get("id") or "")
            if thread:
                sessions.append(thread)
        return list(dict.fromkeys(sessions))

    def chat(self, *, session_id: str, query: str) -> str:
        client = self._ensure()
        if client is None:
            return ""
        if hasattr(client, "peer"):
            try:
                peer = client.peer(self.user_id)
                session_ids = self._profile_session_ids()
                if not session_ids:
                    return ""
                response = peer.chat(query, reasoning_level="minimal", sessions=session_ids)
                return str(getattr(response, "content", response) or "")
            except Exception as exc:
                logger.warning("[HONCHO] Context skipped: %s", exc)
                return ""
        try:
            app_id = getattr(self._app, "id", self.app_id)
            user_id = getattr(self._user, "id", self.user_id)
            response = client.apps.users.sessions.chat(
                app_id=app_id,
                user_id=user_id,
                session_id=session_id,
                query=query,
            )
            return str(getattr(response, "content", response) or "")
        except Exception as exc:
            logger.warning("[HONCHO] Context skipped: %s", exc)
            return ""
