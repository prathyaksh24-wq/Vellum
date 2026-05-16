from pathlib import Path

import pytest

from agent.memory.project_context import (
    InvalidSlug,
    ProjectContext,
    ProjectNotFound,
    validate_slug,
)


def test_validate_slug_accepts_valid() -> None:
    validate_slug("fitness")
    validate_slug("naval-x")
    validate_slug("p2")


def test_validate_slug_rejects_invalid() -> None:
    for bad in ["", "A", "1bad", "with space", "x", "x" * 41, "trailing-", "--double"]:
        with pytest.raises(InvalidSlug):
            validate_slug(bad)


def test_read_meta_files_empty_when_missing(tmp_path: Path) -> None:
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    meta = ctx._read_meta()
    assert meta == ""


def test_read_meta_files_concatenates(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("PROFILE BODY")
    (meta / "goals.md").write_text("GOALS BODY")
    (meta / "principles.md").write_text("PRINCIPLES BODY")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    block = ctx._read_meta()
    assert "PROFILE BODY" in block
    assert "GOALS BODY" in block
    assert "PRINCIPLES BODY" in block
    # Ordered profile, goals, principles
    assert block.index("PROFILE BODY") < block.index("GOALS BODY") < block.index("PRINCIPLES BODY")


def test_read_project_missing_raises(tmp_path: Path) -> None:
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    with pytest.raises(ProjectNotFound):
        ctx._read_project("fitness")


def test_read_project_concatenates_charter_and_hot(tmp_path: Path) -> None:
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "hot.md").write_text("HOT")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    block = ctx._read_project("fitness")
    assert "CHARTER" in block and "HOT" in block
    assert block.index("CHARTER") < block.index("HOT")


def test_build_empty_when_no_meta(tmp_path: Path) -> None:
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    assert ctx.build("thread1") == ""


def test_build_meta_only_wraps_in_protected(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("Name: TestUser")
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    block = ctx.build("thread1")
    assert block.startswith("<PROTECTED>")
    assert block.rstrip().endswith("</PROTECTED>")


def test_build_active_project_included(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("PROFILE")

    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "hot.md").write_text("HOT")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx._state.set_active_project("thread1", "fitness")
    block = ctx.build("thread1")
    assert "PROFILE" in block
    assert "CHARTER" in block
    assert "HOT" in block


def test_build_clears_active_when_project_missing(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("PROFILE")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx._state.set_active_project("thread1", "ghost")
    block = ctx.build("thread1")
    assert "PROFILE" in block
    assert ctx._state.get_active_project("thread1") is None


def test_build_truncates_oversize_file(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    huge = "word " * 5000
    (meta / "profile.md").write_text(huge)

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    block = ctx.build("thread1")
    assert "[truncated]" in block


import time


def test_build_cache_hit_when_unchanged(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("FIRST")
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    first = ctx.build("thread1")
    second = ctx.build("thread1")
    assert first == second
    assert len(ctx._cache) >= 1


def test_build_cache_miss_when_file_changes(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    profile = meta / "profile.md"
    profile.write_text("FIRST")
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    first = ctx.build("thread1")
    time.sleep(0.05)
    profile.write_text("SECOND")
    second = ctx.build("thread1")
    assert "FIRST" not in second
    assert "SECOND" in second


def test_tick_appends_log_line(tmp_path: Path) -> None:
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "log.md").write_text("")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx._state.set_active_project("t1", "fitness")
    ctx.tick("t1", "wrote a thing", turn_ref="t1-1")

    log = (proj / "log.md").read_text()
    assert "[session]" in log
    assert "wrote a thing" in log
    assert "turn=t1-1" in log
    import re as _re
    assert _re.search(r"\b\d{2}/\d{2}/\d{4} \d{2}:\d{2}\b", log)


def test_tick_no_active_project_is_noop(tmp_path: Path) -> None:
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx.tick("t1", "anything")
    assert not (tmp_path / "Projects").exists()
