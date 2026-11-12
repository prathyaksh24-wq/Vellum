from datetime import datetime, timezone

import pytest

from agent.conversations.lifecycle import ConversationLifecycle, ConversationLifecycleError


def saved_request(tmp_path):
    service = ConversationLifecycle(
        path=tmp_path / "conversations.json",
        clock=lambda: datetime(2026, 11, 12, 4, 0, tzinfo=timezone.utc),
    )
    record = service.save("chat", {"messages": [
        {"id": "request", "role": "user", "text": "Original", "sent_at": "2026-11-11T05:57:00Z",
         "attachments": [{"name": "notes.txt"}]},
        {"id": "reply", "role": "assistant", "text": "Existing reply"},
    ]})["conversation"]
    return service, record


def test_edit_request_retains_original_time_attachments_and_reply(tmp_path):
    service, record = saved_request(tmp_path)
    result = service.edit_user_message("chat", "request", "Corrected", expected_revision=record["revision"])
    messages = service.get("chat")["messages"]
    assert result["changed"] is True
    assert messages[0]["text"] == "Corrected"
    assert messages[0]["sent_at"] == "2026-11-11T05:57:00Z"
    assert messages[0]["attachments"] == [{"name": "notes.txt"}]
    assert messages[0]["edited_at"] == "2026-11-12T04:00:00+00:00"
    assert messages[1] == record["messages"][1]


def test_stale_edit_does_not_replace_newer_request(tmp_path):
    service, record = saved_request(tmp_path)
    service.edit_user_message("chat", "request", "Newer", expected_revision=record["revision"])
    with pytest.raises(ConversationLifecycleError, match="changed before"):
        service.edit_user_message("chat", "request", "Stale", expected_revision=record["revision"])
    assert service.get("chat")["messages"][0]["text"] == "Newer"


def test_edit_rejects_assistant_messages_and_active_responses(tmp_path):
    service, record = saved_request(tmp_path)
    with pytest.raises(ConversationLifecycleError, match="no longer available"):
        service.edit_user_message("chat", "reply", "Overwrite")
    record["messages"][1]["streaming"] = True
    service.save("chat", record)
    with pytest.raises(ConversationLifecycleError, match="current response"):
        service.edit_user_message("chat", "request", "Overwrite")
    assert service.get("chat")["messages"][0]["text"] == "Original"
