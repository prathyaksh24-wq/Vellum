import asyncio

from rich.console import Console

from agent import cli
from agent.skills import SkillManager, SkillSurfaceService


def test_cli_handles_skills_locally_and_expands_learn_and_direct_skill(tmp_path, monkeypatch) -> None:
    root = tmp_path / ".skills"
    SkillManager(root).create(
        "---\nname: cli-skill\ndescription: CLI skill\n---\n# CLI Skill\n",
        confirm=True,
    )
    service = SkillSurfaceService(root, logs_root=tmp_path / "logs", sources=[])
    monkeypatch.setattr(cli, "_skill_surface_singleton", service)
    console = Console(record=True)

    handled, _ = asyncio.run(cli.handle_command("/skills", console))

    assert handled is True
    assert "cli-skill" in console.export_text()
    assert 'skill_manage(action="create"' in cli.expand_skill_input("/learn this conversation")
    assert cli.expand_skill_input("/cli-skill do it") == (
        "Load cli-skill with skill_view, then follow it for this request: do it"
    )
