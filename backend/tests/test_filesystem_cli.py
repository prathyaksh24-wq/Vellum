"""Tests for the PowerShell-CLI filesystem tools (no MCP involved)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.tools import filesystem as fs


@pytest.fixture
def fs_settings(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        fs,
        "get_settings",
        lambda: SimpleNamespace(
            obsidian_vault_path=vault,
            browser_cache_dir=tmp_path / "cache",
        ),
    )
    return vault


def test_read_file_reads_vault_file(fs_settings):
    note = fs_settings / "Agent" / "test.md"
    note.parent.mkdir(parents=True)
    note.write_text("hello vault", encoding="utf-8")

    assert fs.read_file.invoke({"path": "Agent/test.md"}) == "hello vault"


def test_read_file_uses_cache_for_relative_path(fs_settings):
    cache = fs_settings.parent / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "page.txt").write_text("cached body", encoding="utf-8")

    assert fs.read_file.invoke({"path": "page.txt"}) == "cached body"


def test_read_file_rejects_paths_outside_vault_and_cache(fs_settings):
    outside = fs_settings.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = fs.read_file.invoke({"path": str(outside)})

    assert "inside the Obsidian vault" in result


def test_read_file_missing(fs_settings):
    assert fs.read_file.invoke({"path": "nope.md"}) == "File not found: nope.md"


def test_write_file_creates_with_parents(fs_settings):
    result = fs.write_file.invoke({"path": "Agent/deep/nested.md", "content": "body"})

    assert result == "Wrote Agent/deep/nested.md"
    assert (fs_settings / "Agent" / "deep" / "nested.md").read_text(encoding="utf-8") == "body"


def test_write_file_overwrites(fs_settings):
    target = fs_settings / "a.md"
    target.write_text("old", encoding="utf-8")

    fs.write_file.invoke({"path": "a.md", "content": "new"})

    assert target.read_text(encoding="utf-8") == "new"


def test_edit_file_replaces_first_occurrence(fs_settings):
    target = fs_settings / "a.md"
    target.write_text("one two one", encoding="utf-8")

    result = fs.edit_file.invoke({"path": "a.md", "old_text": "one", "new_text": "ONE"})

    assert result == "Edited a.md"
    assert target.read_text(encoding="utf-8") == "ONE two one"


def test_edit_file_pattern_not_found(fs_settings):
    target = fs_settings / "a.md"
    target.write_text("abc", encoding="utf-8")

    result = fs.edit_file.invoke({"path": "a.md", "old_text": "zzz", "new_text": "x"})

    assert "Pattern not found" in result
    assert target.read_text(encoding="utf-8") == "abc"


def test_delete_file_requires_confirmation(fs_settings):
    target = fs_settings / "a.md"
    target.write_text("body", encoding="utf-8")

    result = fs.delete_file.invoke({"path": "a.md", "confirm": False})

    assert "confirm=true" in result
    assert target.exists()


def test_delete_file_with_confirmation(fs_settings):
    target = fs_settings / "a.md"
    target.write_text("body", encoding="utf-8")

    result = fs.delete_file.invoke({"path": "a.md", "confirm": True})

    assert result == "Deleted a.md"
    assert not target.exists()


def test_create_directory_creates_nested(fs_settings):
    result = fs.create_directory.invoke({"path": "Folder/Sub"})

    assert result == "Created Folder/Sub"
    assert (fs_settings / "Folder" / "Sub").is_dir()


def test_list_files_returns_vault_relative_paths(fs_settings):
    (fs_settings / "a.md").write_text("a", encoding="utf-8")
    (fs_settings / "b.md").write_text("b", encoding="utf-8")

    result = fs.list_files.invoke({"directory": ""})

    assert "- a.md" in result
    assert "- b.md" in result


def test_ps_quote_escapes_single_quotes():
    assert fs._ps_quote("it's a test") == "'it''s a test'"
