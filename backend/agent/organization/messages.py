from __future__ import annotations

from agent.organization.models import AgentMessage, TaskRoom
from agent.organization.store import OrganizationStore


MESSAGE_TYPES = {
    "question", "evidence_proposal", "critique", "decision_proposal",
    "artifact_reference", "clarification_request", "final_contribution",
}


class TaskRoomService:
    def __init__(self, store: OrganizationStore) -> None:
        self.store = store

    def create(self, *, owner: str, purpose: str, participants: list[str]) -> TaskRoom:
        return self.store.add_room(owner, purpose, participants)

    def post(self, room_id: str, sender: str, recipient: str, message_type: str, claim: str, evidence_refs: list[str], confidence: float) -> AgentMessage:
        room = self._room_for(room_id, sender)
        if recipient not in room.participants or message_type not in MESSAGE_TYPES:
            raise PermissionError("task room unavailable")
        return self.store.add_message(room_id, sender, recipient, message_type, claim, evidence_refs, confidence)

    def list_messages(self, room_id: str, *, actor: str) -> list[AgentMessage]:
        self._room_for(room_id, actor)
        return self.store.messages(room_id)

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

    def _room_for(self, room_id: str, actor: str) -> TaskRoom:
        room = self.store.get_room(room_id)
        if room is None or room.status != "active" or actor not in room.participants:
            raise PermissionError("task room unavailable")
        return room
