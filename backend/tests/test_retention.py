import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "apply_retention.py"


def load_retention():
    spec = importlib.util.spec_from_file_location("apply_retention", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeIngester:
    def __init__(self):
        self.deleted = []
        self.ingested = []

    def delete_file_records(self, path):
        self.deleted.append(str(path).replace("\\", "/"))

    def ingest_file(self, path):
        self.ingested.append(str(path).replace("\\", "/"))
        return 1


def write_conversation_note(path: Path, updated_at: str, *, conversation_id: str = "chat-1", extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''---
type: conversation
privacy: "private"
conversation_id: "{conversation_id}"
thread_id: "thread-{conversation_id}"
title: "A useful conversation"
updated_at: "{updated_at}"
{extra}---

# A useful conversation

## Summary

Remember the useful decision.

## Conversation / Transcript

### User

Keep this context.
''',
        encoding="utf-8",
        newline="\n",
    )


def test_archive_happens_before_delete(tmp_path: Path) -> None:
    retention = load_retention()
    vault = tmp_path / "Vault"
    source = vault / "Agent" / "Conversations" / "2026" / "01" / "a-useful-conversation.md"
    write_conversation_note(source, "2026-01-01T00:00:00+00:00")

    archived = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        archive_after_days=30,
        delete_after_days=90,
        dry_run=False,
    )
    target = vault / "Archive" / "Agent" / "Conversations" / "2026" / "01" / "a-useful-conversation.md"
    assert archived["archived"] == 1
    assert archived["deleted"] == 0
    assert not source.exists()
    assert target.exists()

    deleted = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        archive_after_days=30,
        delete_after_days=90,
        dry_run=False,
    )
    assert deleted["deleted"] == 1
    assert not target.exists()
    card = vault / "Agent" / "Memories" / "Conversations" / "2026" / "01" / "a-useful-conversation-memory.md"
    assert card.exists()
    assert retention.verify_card(card)


def test_existing_distilled_card_is_not_overwritten(tmp_path: Path) -> None:
    retention = load_retention()
    vault = tmp_path / "Vault"
    source = vault / "Archive" / "Agent" / "Conversations" / "2026" / "01" / "a-useful-conversation.md"
    write_conversation_note(source, "2026-01-01T00:00:00+00:00")
    card = vault / "Agent" / "Memories" / "Conversations" / "2026" / "01" / "a-useful-conversation-memory.md"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(
        '''---
type: conversation_memory
source_path: "Archive/Agent/Conversations/2026/01/a-useful-conversation.md"
---

# Hand distilled card

## Distilled Memory

This exact card must survive unchanged.
''',
        encoding="utf-8",
    )
    before = card.read_text(encoding="utf-8")

    result = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        delete_after_days=30,
        dry_run=False,
    )

    assert result["deleted"] == 1
    assert card.read_text(encoding="utf-8") == before


def test_invalid_or_missing_card_blocks_destructive_delete(tmp_path: Path) -> None:
    retention = load_retention()
    vault = tmp_path / "Vault"
    source = vault / "Archive" / "Agent" / "Conversations" / "2026" / "01" / "unsafe.md"
    write_conversation_note(source, "2026-01-01T00:00:00+00:00", conversation_id="unsafe")
    card = vault / "Agent" / "Memories" / "Conversations" / "2026" / "01" / "unsafe-memory.md"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text("---\ntype: note\n---\n\nNot a distilled card.\n", encoding="utf-8")

    result = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        delete_after_days=30,
        dry_run=False,
    )

    assert result["deleted"] == 0
    assert result["blocked"] == 1
    assert source.exists()


def test_pinned_keep_legacy_and_other_roots_are_untouched(tmp_path: Path) -> None:
    retention = load_retention()
    vault = tmp_path / "Vault"
    pinned = vault / "Agent" / "Conversations" / "2026" / "01" / "pinned.md"
    kept = vault / "Agent" / "Conversations" / "2026" / "01" / "kept.md"
    write_conversation_note(pinned, "2026-01-01T00:00:00+00:00", extra="pinned: true\n")
    write_conversation_note(kept, "2026-01-01T00:00:00+00:00", conversation_id="kept", extra="retention: keep\n")
    legacy = vault / "Agent" / "Queries" / "old.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("legacy", encoding="utf-8")
    other = vault / "Library" / "source.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("not a retention source", encoding="utf-8")

    result = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        archive_after_days=30,
        delete_after_days=30,
        dry_run=False,
    )

    assert result["archived"] == 0
    assert result["deleted"] == 0
    assert pinned.exists() and kept.exists() and legacy.exists() and other.exists()


def test_dry_run_has_no_filesystem_effect(tmp_path: Path) -> None:
    retention = load_retention()
    vault = tmp_path / "Vault"
    source = vault / "Agent" / "Conversations" / "2026" / "01" / "preview.md"
    write_conversation_note(source, "2026-01-01T00:00:00+00:00")

    result = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        archive_after_days=30,
        dry_run=True,
    )

    assert result["would_archive"] == 1
    assert source.exists()
    assert not (vault / "Archive").exists()
