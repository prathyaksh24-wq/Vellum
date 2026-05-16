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
