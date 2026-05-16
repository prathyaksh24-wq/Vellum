from pathlib import Path

import pytest

from scripts.migrate_vault_v2 import (
    MigrationAborted,
    Migrator,
    plan_actions,
)


def test_plan_actions_dry_run(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    (vault / "X").mkdir(parents=True)
    (vault / "Youtube").mkdir()
    (vault / "Agent").mkdir()
    plan = plan_actions(vault)
    move_targets = [a for a in plan if a.kind == "move"]
    move_srcs = {Path(a.args["src"]).name for a in move_targets}
    assert "X" in move_srcs
    assert "Youtube" in move_srcs
    assert "Agent" not in move_srcs  # Agent stays put


def test_lock_file_blocks_concurrent(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    m1 = Migrator(vault_root=vault, data_root=data)
    with m1.lock():
        m2 = Migrator(vault_root=vault, data_root=data)
        with pytest.raises(MigrationAborted, match="in progress"):
            with m2.lock():
                pass


def test_idempotent_replan(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    (vault / "Library" / "X").mkdir(parents=True)  # already migrated
    (vault / "Meta").mkdir()
    (vault / "Projects").mkdir()
    (vault / "Agent").mkdir()
    plan = plan_actions(vault)
    assert not any(a.kind == "move" for a in plan)


from scripts.migrate_vault_v2 import rewrite_wikilinks, rewrite_text


def test_rewrite_text_plain_links() -> None:
    text = "see [[X/foo]] and [[Youtube/bar|alias]]"
    out = rewrite_text(text)
    assert "[[Library/X/foo]]" in out
    assert "[[Library/Youtube/bar|alias]]" in out


def test_rewrite_text_embed_and_heading() -> None:
    text = "embed ![[X/foo#section]] and header [[Youtube/bar#sec|Section]]"
    out = rewrite_text(text)
    assert "![[Library/X/foo#section]]" in out
    assert "[[Library/Youtube/bar#sec|Section]]" in out


def test_rewrite_skips_fenced_code() -> None:
    text = "```\nsee [[X/foo]]\n```\nlive [[X/foo]]"
    out = rewrite_text(text)
    assert out.count("[[X/foo]]") == 1
    assert out.count("[[Library/X/foo]]") == 1


def test_rewrite_skips_inline_code() -> None:
    text = "inline `[[X/foo]]` versus live [[X/foo]]"
    out = rewrite_text(text)
    assert "`[[X/foo]]`" in out
    assert "[[Library/X/foo]]" in out


def test_rewrite_wikilinks_writes_files(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("[[X/foo]]")
    rewrite_wikilinks(tmp_path)
    assert "[[Library/X/foo]]" in f.read_text()


def test_rewrite_leaves_non_moved_paths_alone() -> None:
    text = "[[Agent/Memories/x]] and [[Meta/profile]]"
    out = rewrite_text(text)
    assert "[[Agent/Memories/x]]" in out
    assert "[[Meta/profile]]" in out
    # Should NOT be wrapped under Library/
    assert "Library/Agent" not in out
    assert "Library/Meta" not in out
