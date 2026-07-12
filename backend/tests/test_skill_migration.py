import json
from pathlib import Path

from agent.skills import JsonSkillMigrator, SkillPackageParser


def write_json_skill(root: Path) -> Path:
    active = root / "active"
    active.mkdir(parents=True)
    path = active / "skill-route-sports-agent-v1.json"
    path.write_text(
        json.dumps(
            {
                "id": "skill-route-sports-agent-v1",
                "name": "Route sports questions to SportsAgent",
                "trigger": ["NBA", "Arsenal"],
                "negative_trigger": ["write sports tests"],
                "confidence_threshold": 0.25,
                "route_to_agent": "SportsAgent",
                "instructions": "Consult SportsAgent before answering.",
                "when_not_to_use": "Do not use for test authoring.",
                "citation_style": "Cite public sources.",
                "output_format": "Concise prose.",
                "created": "2026-05-27",
                "approved": "2026-05-27",
                "use_count": 4,
                "last_used": "2026-07-01T10:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_migrator_converts_json_to_valid_package_and_usage(tmp_path: Path) -> None:
    write_json_skill(tmp_path)

    report = JsonSkillMigrator(tmp_path).migrate()

    package_root = tmp_path / "packages" / "uncategorized" / "skill-route-sports-agent-v1"
    package = SkillPackageParser().parse(package_root)
    vellum = package.metadata.metadata.vellum
    assert report.created == ["skill-route-sports-agent-v1"]
    assert vellum.trigger == ["NBA", "Arsenal"]
    assert vellum.route_to_agent == "SportsAgent"
    assert vellum.routing_critical is True
    assert "Consult SportsAgent" in package.body
    usage = json.loads((tmp_path / ".usage.json").read_text(encoding="utf-8"))
    assert usage["skill-route-sports-agent-v1"]["use_count"] == 4
    assert not (tmp_path / "active" / "skill-route-sports-agent-v1.json").exists()
    assert report.applied is True
    assert report.rollback_snapshot


def test_migrator_is_idempotent_and_preserves_modified_package(tmp_path: Path) -> None:
    write_json_skill(tmp_path)
    migrator = JsonSkillMigrator(tmp_path)
    migrator.migrate()
    skill_file = tmp_path / "packages" / "uncategorized" / "skill-route-sports-agent-v1" / "SKILL.md"
    skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\nUser modification.\n", encoding="utf-8")

    report = migrator.migrate()

    assert report.created == []
    assert report.applied is True
    assert "User modification" in skill_file.read_text(encoding="utf-8")


def test_migrator_does_not_publish_any_package_when_staging_validation_fails(tmp_path: Path, monkeypatch) -> None:
    write_json_skill(tmp_path)

    def fail_parse(*args, **kwargs):
        raise ValueError("validation failed")

    monkeypatch.setattr("agent.skills.migration.SkillPackageParser.parse", fail_parse)

    try:
        JsonSkillMigrator(tmp_path).migrate()
    except ValueError as exc:
        assert "validation failed" in str(exc)

    assert not (tmp_path / "packages").exists()


def test_migration_rollback_and_interrupted_recovery_restore_legacy_source(tmp_path: Path) -> None:
    source = write_json_skill(tmp_path)
    migrator = JsonSkillMigrator(tmp_path)
    report = migrator.apply()
    snapshot_id = Path(report.rollback_snapshot).name

    restored = migrator.rollback(snapshot_id)

    assert restored["ok"] is True
    assert source.is_file()
    assert not (tmp_path / "packages").exists()

    report = migrator.apply()
    snapshot_id = Path(report.rollback_snapshot).name
    migrator.state_path.write_text(json.dumps({"status": "applying", "snapshot": snapshot_id}), encoding="utf-8")

    recovered = migrator.recover_interrupted()

    assert recovered["restored"] == snapshot_id
    assert source.is_file()
