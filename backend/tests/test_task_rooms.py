from pathlib import Path

import pytest

from agent.organization import OrganizationStore, TaskRoomService


def test_task_room_messages_are_participant_scoped_and_immutable(tmp_path: Path) -> None:
    service = TaskRoomService(OrganizationStore(tmp_path / "organization.db"))
    room = service.create(owner="VellumAgent", purpose="Launch review", participants=["ResearchAgent", "MarketingAgent"])
    message = service.post(
        room_id=room.id,
        sender="ResearchAgent",
        recipient="MarketingAgent",
        message_type="evidence_proposal",
        claim="Segment A performed best",
        evidence_refs=["artifact:report-9"],
        confidence=0.86,
    )

    assert service.list_messages(room.id, actor="MarketingAgent")[0].id == message.id
    with pytest.raises(PermissionError):
        service.list_messages(room.id, actor="SportsAgent")
    with pytest.raises(RuntimeError, match="immutable"):
        service.update_message(message.id, claim="Changed")


def test_completing_room_returns_proposals_without_auto_publish(tmp_path: Path) -> None:
    service = TaskRoomService(OrganizationStore(tmp_path / "organization.db"))
    room = service.create(owner="VellumAgent", purpose="Review", participants=["ResearchAgent"])
    service.post(room.id, "ResearchAgent", "VellumAgent", "final_contribution", "Finding", [], 0.8)

    result = service.complete(room.id, actor="VellumAgent")

    assert result["proposals"][0]["claim"] == "Finding"
    assert result["published"] == []
