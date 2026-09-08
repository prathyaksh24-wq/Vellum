"""Confirmation-gated local conversation exports."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4


class ConversationShareError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ConversationShareService:
    """Prepare export reviews and execute only confirmed local exports.

    External providers are intentionally unavailable until a provider can enter
    through Vellum's privacy gate with a typed, allowlisted disclosure contract.
    """

    def __init__(
        self,
        *,
        export_dir: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.export_dir = Path(export_dir)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def review(self, conversation: dict[str, Any], *, provider_id: str = "") -> dict[str, Any]:
        self._require_local_export(provider_id)
        messages = conversation.get("messages") if isinstance(conversation.get("messages"), list) else []
        attachment_count = sum(
            len(message.get("attachments") or [])
            for message in messages
            if isinstance(message, dict) and isinstance(message.get("attachments"), list)
        )
        return {
            "destination": "local_export",
            "external_disclosure": False,
            "format": "json",
            "title": str(conversation.get("title") or "New chat"),
            "message_count": len(messages),
            "attachment_count": attachment_count,
            "conversation_revision": int(conversation.get("revision", 0)),
        }

    def share(self, conversation: dict[str, Any], *, provider_id: str = "") -> dict[str, Any]:
        review = self.review(conversation, provider_id=provider_id)
        payload = {
            "schema_version": 1,
            "exported_at": self._now().isoformat(timespec="seconds"),
            "conversation": conversation,
        }
        self.export_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(conversation.get("id") or "conversation")).strip("-._")
        safe_id = safe_id[:80] or "conversation"
        revision = int(conversation.get("revision", 0))
        target = self.export_dir / f"{safe_id}-r{revision}.json"
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        return {
            "provider_id": "local_export",
            "review": review,
            "export_path": str(target.resolve(strict=False)),
            "public_url": None,
        }

    @staticmethod
    def _require_local_export(provider_id: str) -> None:
        clean = str(provider_id or "").strip()
        if not clean:
            return
        raise ConversationShareError(
            "SHARE_PROVIDER_UNAVAILABLE",
            "That share provider is not enabled. A local export is available instead.",
            details={"provider_id": clean, "fallback": "local_export"},
        )

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
