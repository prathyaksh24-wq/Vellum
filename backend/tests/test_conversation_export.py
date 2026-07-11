import json
from pathlib import Path

from agent.obsidian.conversation_export import (
    archive_conversation_projection,
    archive_legacy_agent_logs,
    export_conversations,
)


def conversation(
    conversation_id: str,
    *,
    title: str = "Plan a trip",
    updated_at: str = "2026-04-01T10:00:00+00:00",
) -> dict:
    return {
        "id": conversation_id,
        "thread_id": f"thread-{conversation_id}",
        "title": title,
        "updated_at": updated_at,
        "created": updated_at,
        "pinned": False,
        "archived": False,
        "summary": "A useful planning conversation.",
        "decisions": ["Use the train."],
        "open_loops": ["Book the hotel."],
        "memory_links": ["[[Agent/Memories/travel-preferences]]"],
        "messages": [
            {"role": "user", "text": "How should I get there?"},
            {"role": "assistant", "text": "Take the train."},
        ],
    }


def test_export_is_readable_private_and_dry_run_by_default(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    record = conversation("chat-1")

    preview = export_conversations([record], vault_root=vault)

    assert preview["dry_run"] is True
    assert preview["counts"]["created"] == 1
    assert not vault.exists()

    applied = export_conversations([record], vault_root=vault, dry_run=False)
    assert applied["counts"]["created"] == 1
    note = vault / "Agent" / "Conversations" / "2026" / "04" / "plan-a-trip.md"
    assert note.exists()
    text = note.read_text(encoding="utf-8")
    assert 'privacy: "private"' in text
    assert 'conversation_id: "chat-1"' in text
    assert 'thread_id: "thread-chat-1"' in text
    assert "# Plan a trip" in text
    assert "## Summary" in text
    assert "## Conversation / Transcript" in text
    assert "## Decisions" in text
    assert "## Open Loops" in text
    assert "## Memory Links" in text
    assert "2026_" not in note.name


def test_deleted_conversation_projection_is_archived_not_deleted(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    record = conversation("chat-1")
    export_conversations([record], vault_root=vault, dry_run=False)

    preview = archive_conversation_projection(
        "chat-1",
        thread_id="thread-chat-1",
        vault_root=vault,
    )
    assert preview["found"] is True
    assert preview["archived"] is False

    result = archive_conversation_projection(
        "chat-1",
        thread_id="thread-chat-1",
        vault_root=vault,
        dry_run=False,
    )

    assert result["archived"] is True
    assert not (vault / "Agent" / "Conversations" / "2026" / "04" / "plan-a-trip.md").exists()
    assert (vault / result["path"]).exists()


def test_export_recovers_full_title_from_first_user_message(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    record = conversation("chat-title", title="what was our most recent con?")
    record["messages"][0]["text"] = "what was our most recent conversation about?"

    result = export_conversations([record], vault_root=vault, dry_run=False)

    assert result["entries"][0]["title"] == "what was our most recent conversation about?"
    assert result["entries"][0]["path"].endswith("what-was-our-most-recent-conversation-about.md")


def test_legacy_query_and_response_notes_move_to_reversible_archive(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    query = vault / "Agent" / "Queries" / "Query 20260517_070433.md"
    response = vault / "Agent" / "Responses" / "QA 20260517_070433.md"
    query.parent.mkdir(parents=True)
    response.parent.mkdir(parents=True)
    query.write_text("old query", encoding="utf-8")
    response.write_text("old response", encoding="utf-8")

    preview = archive_legacy_agent_logs(vault_root=vault)
    assert preview["counts"]["archived"] == 2
    assert query.exists() and response.exists()

    applied = archive_legacy_agent_logs(vault_root=vault, dry_run=False)
    assert applied["counts"]["archived"] == 2
    assert not query.exists() and not response.exists()
    assert (vault / "Archive" / "Legacy Agent Logs" / "Queries" / query.name).read_text(encoding="utf-8") == "old query"
    assert (vault / "Archive" / "Legacy Agent Logs" / "Responses" / response.name).read_text(encoding="utf-8") == "old response"
    assert (vault / "Archive" / "Legacy Agent Logs" / "README.md").exists()


def test_export_rerun_is_idempotent_and_title_date_changes_rename(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    original = conversation("chat-1")
    export_conversations([original], vault_root=vault, dry_run=False)

    rerun = export_conversations([original], vault_root=vault, dry_run=False)
    assert rerun["counts"]["unchanged"] == 1
    assert len(list((vault / "Agent" / "Conversations").rglob("*.md"))) == 1

    changed = conversation(
        "chat-1",
        title="Book the hotel",
        updated_at="2026-05-03T10:00:00+00:00",
    )
    renamed = export_conversations([changed], vault_root=vault, dry_run=False)
    assert renamed["counts"]["renamed"] == 1
    assert not (vault / "Agent" / "Conversations" / "2026" / "04" / "plan-a-trip.md").exists()
    assert (vault / "Agent" / "Conversations" / "2026" / "05" / "book-the-hotel.md").exists()
    assert len(list((vault / "Agent" / "Conversations").rglob("*.md"))) == 1


def test_same_title_collision_is_deterministic_and_does_not_duplicate(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    records = [conversation("b"), conversation("a")]

    first = export_conversations(records, vault_root=vault, dry_run=False)
    paths = sorted(path.relative_to(vault).as_posix() for path in (vault / "Agent" / "Conversations").rglob("*.md"))
    assert paths == [
        "Agent/Conversations/2026/04/plan-a-trip--b.md",
        "Agent/Conversations/2026/04/plan-a-trip.md",
    ]
    assert first["counts"]["created"] == 2

    second = export_conversations(records, vault_root=vault, dry_run=False)
    assert second["counts"]["unchanged"] == 2
    assert len(list((vault / "Agent" / "Conversations").rglob("*.md"))) == 2


def test_timestamp_qa_title_uses_human_message_title(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    record = conversation("chat-qa", title="QA 20260108_143022")

    export_conversations([record], vault_root=vault, dry_run=False)

    assert (vault / "Agent" / "Conversations" / "2026" / "04" / "how-should-i-get-there.md").exists()
    assert not list((vault / "Agent" / "Conversations").rglob("*20260108*"))


def test_export_never_manages_legacy_conversation_folders(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    legacy = vault / "Agent" / "Queries" / "QA 20260101_010101.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")

    export_conversations([conversation("chat-1")], vault_root=vault, dry_run=False)

    assert legacy.exists()
    assert json.loads(json.dumps(conversation("chat-1")))["id"] == "chat-1"
