from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent.organization.models import AgentMessage, TaskRoom
from agent.organization.store import OrganizationStore


MESSAGE_TYPES = {
    "question", "evidence_proposal", "critique", "decision_proposal",
    "artifact_reference", "clarification_request", "final_contribution",
}


class TaskRoomService:
    def __init__(self, store: OrganizationStore) -> None:
        self.store = store

    def create(self, *, owner: str, purpose: str, participants: list[str], ttl_seconds: int = 86400) -> TaskRoom:
        expires = (datetime.now(UTC) + timedelta(seconds=max(1, ttl_seconds))).isoformat()
        return self.store.add_room(owner, purpose, participants, expires)

    def add_participant(self, room_id: str, *, actor: str, participant: str) -> TaskRoom:
        room = self._room_for(room_id, actor)
        if actor != room.owner:
            raise PermissionError("task room unavailable")
        self.store.update_room(room_id, participants=tuple(dict.fromkeys((*room.participants, participant))))
        return self.store.get_room(room_id)  # type: ignore[return-value]

    def post(self, room_id: str, sender: str, recipient: str, message_type: str, claim: str, evidence_refs: list[str], confidence: float, *, task: str = "", visibility: str = "recipient") -> AgentMessage:
        room = self._room_for(room_id, sender)
        if recipient not in room.participants or message_type not in MESSAGE_TYPES:
            raise PermissionError("task room unavailable")
        if visibility not in {"recipient", "room"}:
            raise PermissionError("task room unavailable")
        return self.store.add_message(room_id, sender, recipient, message_type, claim, evidence_refs, confidence, task=task or room.purpose, visibility=visibility)

    def list_messages(self, room_id: str, *, actor: str) -> list[AgentMessage]:
        room = self._room_for(room_id, actor)
        return [message for message in self.store.messages(room_id) if message.visibility == "room" or actor in {message.sender, message.recipient, room.owner}]

    def update_message(self, message_id: str, **changes) -> None:
        raise RuntimeError("agent messages are immutable")

    def complete(self, room_id: str, *, actor: str) -> dict:
        room = self._room_for(room_id, actor)
        if actor != room.owner:
            raise PermissionError("task room unavailable")
        messages = self.store.messages(room_id)
        self.store.close_room(room_id)
        return {
            "proposals": [
                {"sender": message.sender, "claim": message.claim, "confidence": message.confidence, "evidence_refs": list(message.evidence_refs)}
                for message in messages if message.type in {"evidence_proposal", "decision_proposal", "final_contribution"}
            ],
            "published": [],
        }

    def expire(self, room_id: str) -> None:
        room = self.store.get_room(room_id)
        if room is not None and room.status == "active":
            self.store.update_room(room_id, status="expired")

    def _room_for(self, room_id: str, actor: str) -> TaskRoom:
        room = self.store.get_room(room_id)
        expired = bool(room and room.expires_at and datetime.fromisoformat(room.expires_at) <= datetime.now(UTC))
        if expired and room is not None:
            self.store.update_room(room_id, status="expired")
        if room is None or room.status != "active" or expired or actor not in room.participants:
            raise PermissionError("task room unavailable")
        return room
