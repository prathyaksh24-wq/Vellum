"""Tests for the read-only browser-cache file tools (PowerShell CLI, no MCP)."""

from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

from agent.tools import filesystem as fs

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="PowerShell-CLI filesystem tools are Windows-native",
)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fs, "get_settings", lambda: SimpleNamespace(browser_cache_dir=root))
    return root


def test_read_file_reads_relative_cache_path(cache):
    (cache / "page.txt").write_text("cached body", encoding="utf-8")

    assert fs.read_file.invoke({"path": "page.txt"}) == "cached body"


def test_read_file_reads_absolute_cache_path(cache):
    snapshot = cache / "snapshots" / "full.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("full snapshot", encoding="utf-8")

    assert fs.read_file.invoke({"path": str(snapshot)}) == "full snapshot"


def test_read_file_rejects_paths_outside_cache(cache):
    outside = cache.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = fs.read_file.invoke({"path": str(outside)})

    assert "inside the browser cache" in result


def test_read_file_rejects_parent_traversal(cache):
    (cache.parent / "outside.txt").write_text("secret", encoding="utf-8")

    result = fs.read_file.invoke({"path": "../outside.txt"})

    assert "inside the browser cache" in result


def test_read_file_missing(cache):
    assert fs.read_file.invoke({"path": "nope.md"}) == "File not found: nope.md"


def test_list_files_returns_cache_relative_paths(cache):
    (cache / "a.md").write_text("a", encoding="utf-8")
    (cache / "b.md").write_text("b", encoding="utf-8")

    result = fs.list_files.invoke({"directory": ""})

    assert "- a.md" in result
    assert "- b.md" in result


def test_file_tools_are_read_only():
    assert not hasattr(fs, "write_file")
    assert not hasattr(fs, "delete_file")
    assert not hasattr(fs, "edit_file")
    assert not hasattr(fs, "create_directory")


def test_ps_quote_escapes_single_quotes():
    assert fs._ps_quote("it's a test") == "'it''s a test'"
