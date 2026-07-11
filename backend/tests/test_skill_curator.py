from datetime import datetime, timezone
import json
from pathlib import Path

from agent.skills import CuratorBackupStore, CuratorConfig, CuratorRuntime, SkillCurator, SkillManager, SkillUsageStore
import pytest


def skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: {name} skill\n---\n# {name}\n\n## Procedure\nRun it.\n"


def set_created(root: Path, name: str, value: str) -> None:
    path = root / ".usage.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[name]["created_at"] = value
    path.write_text(json.dumps(data), encoding="utf-8")


def test_backup_and_rollback_restore_skill_tree_and_keep_bounded_history(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("one"), confirm=True)
    backups = CuratorBackupStore(root, keep=2)

    first = backups.create("first")
    (manager.package("one").root / "SKILL.md").write_text(skill_md("one").replace("Run it", "Changed"), encoding="utf-8")
    backups.create("second")
    backups.create("third")

    assert len(backups.list()) == 2
    assert first["id"] not in {item["id"] for item in backups.list()}

    target = backups.list()[-1]["id"]
    backups.rollback(target)
    assert "Changed" in manager.package("one").skill_file.read_text(encoding="utf-8")
    assert any("pre-rollback" in item["reason"] for item in backups.list())


def test_curator_first_run_defers_then_transitions_only_eligible_skills(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("stale-agent"), origin="background_review", confirm=True)
    manager.create(skill_md("old-agent"), origin="background_review", confirm=True)
    manager.create(skill_md("foreground"), origin="foreground", confirm=True)
    manager.create(skill_md("pinned-agent"), origin="background_review", confirm=True)
    manager.usage.pin("pinned-agent")
    set_created(root, "stale-agent", "2026-05-20T00:00:00+00:00")
    set_created(root, "old-agent", "2026-01-01T00:00:00+00:00")
    set_created(root, "foreground", "2026-01-01T00:00:00+00:00")
    set_created(root, "pinned-agent", "2026-01-01T00:00:00+00:00")
    now = datetime(2026, 7, 3, tzinfo=timezone.utc)
    curator = SkillCurator(
        root,
        logs_root=tmp_path / "logs",
        config=CuratorConfig(stale_after_days=30, archive_after_days=90),
    )

    first = curator.run(now=now, idle_hours=10)
    second = curator.run(now=now, idle_hours=10, force=True)

    assert first["status"] == "deferred_first_run"
    assert second["stale"] == ["stale-agent"]
    assert second["archived"] == ["old-agent"]
    assert SkillUsageStore(root).get("stale-agent")["state"] == "stale"
    assert (root / ".archive" / "uncategorized" / "old-agent" / "SKILL.md").exists()
    assert manager.package("foreground")
    assert manager.package("pinned-agent")
    assert (tmp_path / "logs" / second["run_id"] / "run.json").exists()
    assert (tmp_path / "logs" / second["run_id"] / "REPORT.md").exists()


def test_curator_dry_run_pause_and_status_do_not_mutate(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("old-agent"), origin="background_review", confirm=True)
    set_created(root, "old-agent", "2026-01-01T00:00:00+00:00")
    curator = SkillCurator(root, logs_root=tmp_path / "logs")
    now = datetime(2026, 7, 3, tzinfo=timezone.utc)
    curator.run(now=now, idle_hours=10)

    preview = curator.run(now=now, idle_hours=10, force=True, dry_run=True)
    assert preview["archived"] == ["old-agent"]
    assert manager.package("old-agent")

    curator.pause()
    assert curator.status()["paused"] is True
    assert curator.run(now=now, idle_hours=10, force=True)["status"] == "paused"
    curator.resume()
    assert curator.status()["paused"] is False


def test_curator_pin_requires_agent_created_skill_and_consolidation_is_bounded(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("agent-skill"), origin="background_review", confirm=True)
    manager.create(skill_md("foreground"), origin="foreground", confirm=True)
    set_created(root, "agent-skill", "2026-06-20T00:00:00+00:00")
    calls = []

    def reviewer(candidates, max_iterations):
        calls.append((candidates, max_iterations))
        return ["agent-skill"]

    curator = SkillCurator(
        root,
        logs_root=tmp_path / "logs",
        config=CuratorConfig(consolidate=True),
        reviewer=reviewer,
    )
    curator.pin("agent-skill")
    assert SkillUsageStore(root).get("agent-skill")["pinned"] is True
    curator.unpin("agent-skill")
    with pytest.raises(ValueError, match="agent-created"):
        curator.pin("foreground")

    now = datetime(2026, 7, 3, tzinfo=timezone.utc)
    curator.run(now=now, idle_hours=10)
    result = curator.run(now=now, idle_hours=10, force=True)

    assert result["consolidated"] == ["agent-skill"]
    assert calls[0][1] == 8


def test_curator_defaults_protect_builtins_and_runtime_tracks_idle_time(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("bundled"), origin="background_review", confirm=True)
    (root / ".bundled_manifest").write_text(json.dumps({"bundled": {}}), encoding="utf-8")
    set_created(root, "bundled", "2026-01-01T00:00:00+00:00")
    now = datetime(2026, 7, 3, tzinfo=timezone.utc)
    curator = SkillCurator(root, logs_root=tmp_path / "logs")
    curator.run(now=now, idle_hours=10)

    result = curator.run(now=now, idle_hours=10, force=True)

    assert curator.config.prune_builtins is False
    assert "bundled" in result["kept"]
    assert manager.package("bundled")

    runtime = CuratorRuntime(root, logs_root=tmp_path / "runtime-logs")
    runtime.mark_activity(datetime(2026, 7, 3, tzinfo=timezone.utc))
    assert runtime.idle_hours(datetime(2026, 7, 3, 2, tzinfo=timezone.utc)) == 2
