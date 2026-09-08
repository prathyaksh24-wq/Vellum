from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.app_actions.runtime import (
    CONVERSATION_ARCHIVE_ACTION_ID,
    CONVERSATION_DELETE_ACTION_ID,
    CONVERSATION_FORK_ACTION_ID,
    CONVERSATION_NEW_ACTION_ID,
    CONVERSATION_OPEN_ACTION_ID,
    CONVERSATION_PIN_ACTION_ID,
    CONVERSATION_RENAME_ACTION_ID,
    CONVERSATION_RESTORE_ACTION_ID,
    CONVERSATION_SHARE_ACTION_ID,
    CONVERSATION_SPACE_ACTION_ID,
    CONVERSATION_UNPIN_ACTION_ID,
    CONVERSATION_WINDOW_OPEN_ACTION_ID,
    AppActionRuntime,
)
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.conversations.lifecycle import ConversationLifecycle
from agent.conversations.sharing import ConversationShareService


FIXED_NOW = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)


def test_catalog_exposes_conversation_lifecycle_actions() -> None:
    lifecycle = ConversationLifecycle(
        path=Path("unused-conversations.json"),
        clock=lambda: FIXED_NOW,
    )
    subject = AppActionRuntime(conversation_lifecycle=lifecycle)

    actions = {action.id: action for action in subject.catalog().actions}

    assert {
        CONVERSATION_NEW_ACTION_ID,
        CONVERSATION_OPEN_ACTION_ID,
        CONVERSATION_PIN_ACTION_ID,
        CONVERSATION_UNPIN_ACTION_ID,
        CONVERSATION_RENAME_ACTION_ID,
        CONVERSATION_SPACE_ACTION_ID,
        CONVERSATION_ARCHIVE_ACTION_ID,
        CONVERSATION_RESTORE_ACTION_ID,
        CONVERSATION_DELETE_ACTION_ID,
        CONVERSATION_FORK_ACTION_ID,
        CONVERSATION_WINDOW_OPEN_ACTION_ID,
        CONVERSATION_SHARE_ACTION_ID,
    }.issubset(actions)
    assert actions[CONVERSATION_DELETE_ACTION_ID].confirmation_rule == "operation_bound"
    assert actions[CONVERSATION_DELETE_ACTION_ID].access_class == "destructive"
    assert actions[CONVERSATION_DELETE_ACTION_ID].supports_undo is False
    assert actions[CONVERSATION_RENAME_ACTION_ID].supports_undo is True
    assert actions[CONVERSATION_SHARE_ACTION_ID].confirmation_rule == "operation_bound"
    assert actions[CONVERSATION_SHARE_ACTION_ID].access_class == "external_write"
    assert actions[CONVERSATION_WINDOW_OPEN_ACTION_ID].executor_location == "client"


def test_explicit_target_is_mutated_instead_of_the_invocation_chat(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {"id": "chat-1", "title": "Invocation chat", "messages": []})
    lifecycle.save("chat-2", {"id": "chat-2", "title": "Target chat", "messages": []})
    subject = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        clock=lambda: FIXED_NOW,
        receipt_id_factory=lambda: "receipt-pin",
        undo_token_factory=lambda: "undo-pin",
    )

    receipt = subject.dispatch(
        AppActionRequest(
            request_id="pin-target",
            action_id=CONVERSATION_PIN_ACTION_ID,
            arguments={"conversation_id": "chat-2", "target_revision": 0},
        ),
        AppActionContext(source="nlp", invocation_conversation_id="chat-1"),
    )

    assert receipt.status == "applied"
    assert receipt.target.model_dump() == {"kind": "conversation", "id": "chat-2", "revision": 1}
    assert receipt.result["conversation"]["pinned"] is True
    assert lifecycle.get("chat-1")["pinned"] is False
    assert ConversationLifecycle(path=lifecycle.path).get("chat-2")["pinned"] is True


def test_lifecycle_resolves_the_ui_id_and_backend_thread_id_to_one_record(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("ui-chat-1", {
        "thread_id": "backend-thread-1",
        "title": "Identity bridge",
        "messages": [],
    })

    assert lifecycle.get("ui-chat-1")["id"] == "ui-chat-1"
    assert lifecycle.get("backend-thread-1")["id"] == "ui-chat-1"
    assert lifecycle.resolve("backend-thread-1")["id"] == "ui-chat-1"


def test_rename_undo_restores_the_previous_title(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {"id": "chat-1", "title": "Original title", "messages": []})
    receipt_ids = iter(["receipt-rename", "receipt-undo"])
    subject = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        clock=lambda: FIXED_NOW,
        receipt_id_factory=lambda: next(receipt_ids),
        undo_token_factory=lambda: "undo-rename",
    )
    context = AppActionContext(source="ui", invocation_conversation_id="another-chat")

    renamed = subject.dispatch(
        AppActionRequest(
            action_id=CONVERSATION_RENAME_ACTION_ID,
            arguments={"conversation_id": "chat-1", "title": "Release plan", "target_revision": 0},
        ),
        context,
    )
    undone = subject.undo(renamed.undo.token, context)

    assert renamed.result["conversation"]["title"] == "Release plan"
    assert renamed.undo.action_id == CONVERSATION_RENAME_ACTION_ID
    assert undone.status == "undone"
    assert lifecycle.get("chat-1")["title"] == "Original title"
    assert lifecycle.get("chat-1")["revision"] == 2


def test_archive_restore_and_stale_revision_use_the_invocation_target(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {"id": "chat-1", "title": "Current chat", "messages": []})
    subject = AppActionRuntime(conversation_lifecycle=lifecycle, clock=lambda: FIXED_NOW)
    context = AppActionContext(source="nlp", invocation_conversation_id="chat-1")

    archived = subject.dispatch(
        AppActionRequest(
            action_id=CONVERSATION_ARCHIVE_ACTION_ID,
            arguments={"target_revision": 0},
        ),
        context,
    )
    stale_restore = subject.dispatch(
        AppActionRequest(
            action_id=CONVERSATION_RESTORE_ACTION_ID,
            arguments={"target_revision": 0},
        ),
        context,
    )
    restored = subject.dispatch(
        AppActionRequest(
            action_id=CONVERSATION_RESTORE_ACTION_ID,
            arguments={"target_revision": 1},
        ),
        context,
    )

    assert archived.result["conversation"]["archived"] is True
    assert stale_restore.status == "failed"
    assert stale_restore.error_code == "STALE_ACTION_TARGET"
    assert restored.result["conversation"]["archived"] is False
    assert restored.target.revision == 2


def test_change_space_and_undo_restore_the_previous_organization(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save(
        "chat-1",
        {
            "id": "chat-1",
            "title": "NBA schedule",
            "messages": [{"id": "u1", "role": "user", "text": "When is the next NBA game?"}],
        },
    )
    subject = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        clock=lambda: FIXED_NOW,
        undo_token_factory=lambda: "undo-space",
    )
    context = AppActionContext(source="ui", invocation_conversation_id="chat-1")

    moved = subject.dispatch(
        AppActionRequest(
            action_id=CONVERSATION_SPACE_ACTION_ID,
            arguments={"space_label": "Weekend", "target_revision": 0},
        ),
        context,
    )
    undone = subject.undo(moved.undo.token, context)

    assert moved.result["conversation"]["organization"]["space_id"] == "weekend"
    assert moved.result["conversation"]["organization"]["assignment"] == "manual"
    assert undone.status == "undone"
    assert lifecycle.get("chat-1")["organization"]["space_id"] == "sports"
    assert lifecycle.get("chat-1")["organization"]["assignment"] == "automatic"


def test_submission_matcher_handles_complete_conversation_instructions() -> None:
    subject = AppActionRuntime()

    assert subject.match_submission("Start a new chat").action_id == CONVERSATION_NEW_ACTION_ID
    assert subject.match_submission("Pin this chat").model_dump(exclude={"request_id"}) == {
        "action_id": CONVERSATION_PIN_ACTION_ID,
        "action_version": "1",
        "arguments": {},
    }
    assert subject.match_submission('Open chat "Target chat"').arguments == {"reference": "Target chat"}
    assert subject.match_submission('Archive the chat called "Target chat"').arguments == {"reference": "Target chat"}
    assert subject.match_submission('Rename this chat to "Launch plan"').arguments == {"title": "Launch plan"}
    assert subject.match_submission('Rename the chat called "Target chat" to "Launch plan"').arguments == {
        "reference": "Target chat",
        "title": "Launch plan",
    }
    assert subject.match_submission("Move this chat to Weekend Space").arguments == {"space_label": "Weekend"}
    assert subject.match_submission('Move the chat called "Target chat" to Weekend Space').arguments == {
        "reference": "Target chat",
        "space_label": "Weekend",
    }
    assert subject.match_submission("Delete this chat").action_id == CONVERSATION_DELETE_ACTION_ID
    assert subject.match_submission("tell me how to archive a chat") is None


def test_open_by_title_and_new_chat_return_navigation_without_mutating_history(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {"id": "chat-1", "title": "Invocation chat", "messages": []})
    lifecycle.save("chat-2", {"id": "chat-2", "title": "Target chat", "messages": []})
    subject = AppActionRuntime(conversation_lifecycle=lifecycle, clock=lambda: FIXED_NOW)
    context = AppActionContext(source="nlp", invocation_conversation_id="chat-1")

    opened = subject.dispatch(subject.match_submission('Open chat "Target chat"'), context)
    fresh = subject.dispatch(subject.match_submission("Start a new chat"), context)

    assert opened.target.model_dump() == {"kind": "conversation", "id": "chat-2", "revision": 0}
    assert opened.result["navigation"] == {"view": "chat", "conversation_id": "chat-2"}
    assert fresh.target.kind == "conversation_navigation"
    assert fresh.result["navigation"] == {"view": "chat", "conversation_id": None}
    assert len(lifecycle.list()) == 2


def test_delete_requires_operation_bound_confirmation_and_rejects_tampering(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {"id": "chat-1", "title": "Keep until confirmed", "messages": []})
    subject = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        clock=lambda: FIXED_NOW,
        confirmation_token_factory=lambda: "confirm-delete",
    )
    context = AppActionContext(source="nlp", invocation_conversation_id="another-chat")
    request = AppActionRequest(
        request_id="delete-request",
        action_id=CONVERSATION_DELETE_ACTION_ID,
        arguments={"conversation_id": "chat-1", "target_revision": 0},
    )

    pending = subject.dispatch(request, context)
    tampered = subject.confirm(
        pending.confirmation.token,
        request.model_copy(update={"arguments": {"conversation_id": "another-chat", "target_revision": 0}}),
        context,
    )
    confirmed = subject.confirm(
        pending.confirmation.token,
        request,
        AppActionContext(source="ui", invocation_conversation_id="chat-1"),
    )

    assert pending.status == "confirmation_required"
    assert pending.authorization.confirmation_required is True
    assert pending.target.model_dump() == {"kind": "conversation", "id": "chat-1", "revision": 0}
    assert tampered.status == "failed"
    assert tampered.error_code == "CONFIRMATION_MISMATCH"
    assert confirmed.status == "applied"
    assert confirmed.result["deleted"] is True
    with pytest.raises(Exception, match="Conversation not found"):
        lifecycle.get("chat-1")


def test_lifecycle_runs_canonical_projection_index_and_cleanup_hooks(tmp_path) -> None:
    calls: list[tuple[str, str]] = []
    lifecycle = ConversationLifecycle(
        path=tmp_path / "conversations.json",
        clock=lambda: FIXED_NOW,
        indexer=lambda conversation: calls.append(("index", conversation["id"])) or {"indexed_turns": 1},
        projector=lambda conversation: calls.append(("project", conversation["id"])) or {"ok": True},
        archiver=lambda conversation: calls.append(("archive", conversation["id"])) or {"ok": True},
        delete_fts=lambda thread_id: calls.append(("fts", thread_id)) or 2,
        clear_context=lambda thread_id: calls.append(("context", thread_id)) or 1,
        delete_session=lambda thread_id: calls.append(("session", thread_id)),
        rename_session=lambda thread_id, title: calls.append(("title", f"{thread_id}:{title}")),
    )

    lifecycle.save("chat-1", {"id": "chat-1", "thread_id": "thread-1", "title": "First", "messages": []})
    calls.clear()
    updated = lifecycle.patch("chat-1", {"title": "Renamed"}, expected_revision=0)
    deleted = lifecycle.delete("chat-1", expected_revision=1)

    assert updated["memory_index"] == {"indexed_turns": 1}
    assert updated["obsidian_projection"] == {"ok": True}
    assert deleted["deleted_fts_rows"] == 2
    assert deleted["deleted_context_refs"] == 1
    assert calls == [
        ("title", "thread-1:Renamed"),
        ("index", "chat-1"),
        ("project", "chat-1"),
        ("archive", "chat-1"),
        ("fts", "thread-1"),
        ("context", "thread-1"),
        ("session", "thread-1"),
    ]


def test_fork_copies_messages_through_selected_boundary_and_context(tmp_path) -> None:
    copied: list[tuple[str, str]] = []
    lifecycle = ConversationLifecycle(
        path=tmp_path / "conversations.json",
        clock=lambda: FIXED_NOW,
        conversation_id_factory=lambda: "chat-fork",
        copy_context=lambda source, destination: copied.append((source, destination)) or 2,
    )
    lifecycle.save("chat-source", {
        "thread_id": "thread-source",
        "title": "Research",
        "messages": [
            {"id": "u1", "role": "user", "text": "Question", "attachments": [{"name": "brief.pdf"}]},
            {"id": "a1", "role": "assistant", "text": "Answer"},
            {"id": "u2", "role": "user", "text": "Later"},
        ],
    })
    subject = AppActionRuntime(conversation_lifecycle=lifecycle, clock=lambda: FIXED_NOW)

    receipt = subject.dispatch(
        AppActionRequest(
            action_id=CONVERSATION_FORK_ACTION_ID,
            arguments={"conversation_id": "chat-source", "through_message_id": "a1"},
        ),
        AppActionContext(source="ui", invocation_conversation_id="chat-source"),
    )

    assert receipt.status == "applied"
    assert [message["id"] for message in receipt.result["conversation"]["messages"]] == ["u1", "a1"]
    assert receipt.result["conversation"]["messages"][0]["attachments"] == [{"name": "brief.pdf"}]
    assert receipt.result["conversation"]["fork"]["source_conversation_id"] == "chat-source"
    assert receipt.result["conversation"]["fork"]["message_count"] == 2
    assert receipt.result["copied_context_refs"] == 2
    assert receipt.result["navigation"]["conversation_id"] == "chat-fork"
    assert copied == [("thread-source", "chat-fork")]
    assert len(lifecycle.get("chat-source")["messages"]) == 3


def test_fork_rejects_a_boundary_outside_the_source_conversation(tmp_path) -> None:
    lifecycle = ConversationLifecycle(
        path=tmp_path / "conversations.json",
        clock=lambda: FIXED_NOW,
        conversation_id_factory=lambda: "chat-fork",
    )
    lifecycle.save("chat-source", {"title": "Research", "messages": [{"id": "u1", "role": "user"}]})
    subject = AppActionRuntime(conversation_lifecycle=lifecycle, clock=lambda: FIXED_NOW)

    receipt = subject.dispatch(
        AppActionRequest(action_id=CONVERSATION_FORK_ACTION_ID, arguments={"through_message_id": "missing"}),
        AppActionContext(source="nlp", invocation_conversation_id="chat-source"),
    )

    assert receipt.status == "failed"
    assert receipt.error_code == "FORK_BOUNDARY_NOT_FOUND"
    assert [item["id"] for item in lifecycle.list()] == ["chat-source"]


def test_failed_context_copy_clears_partial_fork_state(tmp_path) -> None:
    cleared: list[str] = []

    def fail_copy(_source: str, _destination: str) -> int:
        raise RuntimeError("copy failed")

    lifecycle = ConversationLifecycle(
        path=tmp_path / "conversations.json",
        conversation_id_factory=lambda: "chat-fork",
        copy_context=fail_copy,
        clear_context=lambda destination: cleared.append(destination) or 1,
    )
    lifecycle.save("chat-source", {"title": "Research", "messages": []})

    with pytest.raises(RuntimeError, match="copy failed"):
        lifecycle.fork("chat-source")

    assert cleared == ["chat-fork"]
    assert [item["id"] for item in lifecycle.list()] == ["chat-source"]


def test_fork_from_here_uses_the_latest_existing_message(tmp_path) -> None:
    lifecycle = ConversationLifecycle(
        path=tmp_path / "conversations.json",
        clock=lambda: FIXED_NOW,
        conversation_id_factory=lambda: "chat-fork",
    )
    lifecycle.save("chat-source", {
        "title": "Research",
        "messages": [
            {"id": "u1", "role": "user", "text": "Question"},
            {"id": "a1", "role": "assistant", "text": "Answer"},
        ],
    })
    subject = AppActionRuntime(conversation_lifecycle=lifecycle, clock=lambda: FIXED_NOW)

    receipt = subject.dispatch(
        subject.match_submission("Fork this chat from here"),
        AppActionContext(source="nlp", invocation_conversation_id="chat-source"),
    )

    assert receipt.status == "applied"
    assert receipt.result["fork_boundary"] == "a1"
    assert [message["id"] for message in receipt.result["conversation"]["messages"]] == ["u1", "a1"]


def test_window_action_targets_the_canonical_conversation_without_creating_a_copy(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {"thread_id": "thread-1", "title": "Window target", "messages": []})
    subject = AppActionRuntime(conversation_lifecycle=lifecycle, clock=lambda: FIXED_NOW)

    receipt = subject.dispatch(
        subject.match_submission("Open this chat in a new window"),
        AppActionContext(source="nlp", invocation_conversation_id="thread-1"),
    )

    assert receipt.status == "applied"
    assert receipt.result["native_window"] == {"conversation_id": "chat-1"}
    assert len(lifecycle.list()) == 1


def test_share_requires_review_and_cancel_prevents_local_export(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {
        "title": "Private draft",
        "messages": [{"id": "u1", "role": "user", "text": "Keep local", "attachments": [{"name": "a.png"}]}],
    })
    sharing = ConversationShareService(export_dir=tmp_path / "exports", clock=lambda: FIXED_NOW)
    subject = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        conversation_sharing=sharing,
        clock=lambda: FIXED_NOW,
        confirmation_token_factory=lambda: "confirm-share",
    )
    context = AppActionContext(source="nlp", invocation_conversation_id="chat-1")
    request = AppActionRequest(action_id=CONVERSATION_SHARE_ACTION_ID)

    pending = subject.dispatch(request, context)
    cancelled = subject.cancel(pending.confirmation.token, context)
    after_cancel = subject.confirm(pending.confirmation.token, request, context)

    assert pending.status == "confirmation_required"
    assert pending.result["share_review"] == {
        "destination": "local_export",
        "external_disclosure": False,
        "format": "json",
        "title": "Private draft",
        "message_count": 1,
        "attachment_count": 1,
        "conversation_revision": 0,
    }
    assert not (tmp_path / "exports").exists()
    assert cancelled.status == "cancelled"
    assert after_cancel.error_code == "CONFIRMATION_UNAVAILABLE"


def test_confirmed_share_creates_local_export_without_a_fake_public_link(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {"title": "Export me", "messages": [{"id": "u1", "role": "user", "text": "Hello"}]})
    sharing = ConversationShareService(export_dir=tmp_path / "exports", clock=lambda: FIXED_NOW)
    subject = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        conversation_sharing=sharing,
        clock=lambda: FIXED_NOW,
        confirmation_token_factory=lambda: "confirm-share",
    )
    context = AppActionContext(source="ui", invocation_conversation_id="chat-1")
    request = AppActionRequest(action_id=CONVERSATION_SHARE_ACTION_ID)

    pending = subject.dispatch(request, context)
    confirmed = subject.confirm(pending.confirmation.token, request, context)

    target = Path(confirmed.result["share"]["export_path"])
    assert confirmed.status == "applied"
    assert target.is_file()
    assert confirmed.result["share"]["provider_id"] == "local_export"
    assert confirmed.result["share"]["public_url"] is None
    assert "Hello" in target.read_text(encoding="utf-8")


def test_confirmation_remains_bound_to_the_reviewed_chat_after_navigation(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-reviewed", {"title": "Reviewed", "messages": [{"id": "u1", "text": "Reviewed body"}]})
    lifecycle.save("chat-later", {"title": "Later", "messages": [{"id": "u2", "text": "Other body"}]})
    sharing = ConversationShareService(export_dir=tmp_path / "exports", clock=lambda: FIXED_NOW)
    subject = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        conversation_sharing=sharing,
        clock=lambda: FIXED_NOW,
        confirmation_token_factory=lambda: "confirm-share",
    )
    request = AppActionRequest(action_id=CONVERSATION_SHARE_ACTION_ID)
    pending = subject.dispatch(
        request,
        AppActionContext(source="nlp", invocation_conversation_id="chat-reviewed"),
    )

    confirmed = subject.confirm(
        pending.confirmation.token,
        request,
        AppActionContext(source="ui", invocation_conversation_id="chat-later"),
    )

    exported = Path(confirmed.result["share"]["export_path"]).read_text(encoding="utf-8")
    assert confirmed.target.id == "chat-reviewed"
    assert "Reviewed body" in exported
    assert "Other body" not in exported


def test_unavailable_share_provider_is_reported_without_disclosing_or_exporting(tmp_path) -> None:
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json", clock=lambda: FIXED_NOW)
    lifecycle.save("chat-1", {"title": "Provider share", "messages": []})
    sharing = ConversationShareService(export_dir=tmp_path / "exports")
    subject = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        conversation_sharing=sharing,
        clock=lambda: FIXED_NOW,
        confirmation_token_factory=lambda: "confirm-provider",
    )
    context = AppActionContext(source="ui", invocation_conversation_id="chat-1")
    request = AppActionRequest(action_id=CONVERSATION_SHARE_ACTION_ID, arguments={"provider_id": "not-enabled"})

    receipt = subject.dispatch(request, context)

    assert receipt.status == "failed"
    assert receipt.error_code == "SHARE_PROVIDER_UNAVAILABLE"
    assert receipt.result == {"provider_id": "not-enabled", "fallback": "local_export"}
    assert not (tmp_path / "exports").exists()
    assert "public_url" not in receipt.result


def test_submission_matcher_recognizes_fork_window_and_share_commands() -> None:
    subject = AppActionRuntime()

    assert subject.match_submission("Fork this chat").action_id == CONVERSATION_FORK_ACTION_ID
    assert subject.match_submission("Fork this chat through message a1").arguments == {"through_message_id": "a1"}
    assert subject.match_submission("Fork this chat from here").arguments == {"from_selected": True}
    assert subject.match_submission("Open this chat in a new window").action_id == CONVERSATION_WINDOW_OPEN_ACTION_ID
    assert subject.match_submission("Share this chat").action_id == CONVERSATION_SHARE_ACTION_ID
    assert subject.match_submission('Fork the chat called "Release plan"').arguments == {"reference": "Release plan"}
    assert subject.match_submission('Open chat named "Release plan" in a new window').arguments == {"reference": "Release plan"}
    assert subject.match_submission('Share the chat called "Release plan"').arguments == {"reference": "Release plan"}
    assert subject.match_submission("tell me about sharing chats") is None
