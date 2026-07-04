from pathlib import Path

from agent.profiles import AgentHomeManager, ProfileRegistry


def test_v1_profile_migrates_in_memory_without_rewriting_file(tmp_path: Path) -> None:
    path = tmp_path / "SportsAgent.yaml"
    original = "version: 1\nid: SportsAgent\nexecutor: deterministic\n"
    path.write_text(original, encoding="utf-8")

    profile = ProfileRegistry(profile_dir=tmp_path).get("SportsAgent")

    assert profile.version == 2
    assert profile.department == "sports"
    assert profile.isolation.backend == "subprocess"
    assert path.read_text(encoding="utf-8") == original


def test_agent_home_seeds_identity_without_overwrite(tmp_path: Path) -> None:
    manager = AgentHomeManager(tmp_path)
    home = manager.ensure("SportsAgent")

    assert (home / "SOUL.md").exists()
    assert (home / "AGENTS.md").exists()
    assert (home / "personalities" / "default.md").exists()
    (home / "SOUL.md").write_text("Custom identity", encoding="utf-8")

    manager.ensure("SportsAgent")

    assert (home / "SOUL.md").read_text(encoding="utf-8") == "Custom identity"
    assert {"memory", "sessions", "workspace", "audit", "skills"} <= {path.name for path in home.iterdir()}
