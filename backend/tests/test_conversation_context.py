from pathlib import Path

import pytest

from agent.obsidian.conversation_context import ConversationContextStore


def test_live_vault_context_tracks_note_changes_and_snapshot_does_not(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    note = vault / "Projects" / "Vellum.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Vellum\n\nInitial architecture.", encoding="utf-8")
    store = ConversationContextStore(tmp_path / "context.db")

    live = store.attach(
        conversation_id="chat-live",
        kind="vault_note",
        ref="Projects/Vellum.md",
        mode="live",
        vault_root=vault,
    )
    snapshot = store.attach(
        conversation_id="chat-snapshot",
        kind="vault_note",
        ref="Projects/Vellum.md",
        mode="snapshot",
        vault_root=vault,
    )
    note.write_text("# Vellum\n\nUpdated architecture.", encoding="utf-8")

    assert "Updated architecture" in store.resolve("chat-live", vault_root=vault)["context"]
    assert "Initial architecture" in store.resolve("chat-snapshot", vault_root=vault)["context"]
    assert live["content_hash"] == snapshot["content_hash"]


def test_vault_context_rejects_path_escape_and_can_be_removed(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_text("private", encoding="utf-8")
    store = ConversationContextStore(tmp_path / "context.db")

    with pytest.raises(ValueError, match="escapes"):
        store.attach(
            conversation_id="chat",
            kind="vault_note",
            ref="../secret.md",
            mode="live",
            vault_root=vault,
        )

    note = vault / "Note.md"
    note.write_text("# Note\n\nSafe context.", encoding="utf-8")
    attached = store.attach(conversation_id="chat", kind="vault_note", ref="Note.md", mode="live", vault_root=vault)
    assert store.remove("chat", attached["id"]) is True
    assert store.list("chat") == []


def test_sensitive_vault_note_cannot_be_attached(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "API KEYS.md").write_text("OPENROUTER_API_KEY=secret-value", encoding="utf-8")
    store = ConversationContextStore(tmp_path / "context.db")

    with pytest.raises(ValueError, match="Sensitive Vault notes"):
        store.attach(
            conversation_id="chat",
            kind="vault_note",
            ref="API KEYS.md",
            mode="live",
            vault_root=vault,
        )
