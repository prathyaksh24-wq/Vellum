from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.skills import CredentialRequirement, SkillMetadata, VellumMetadata


def test_skill_metadata_accepts_hermes_fields() -> None:
    metadata = SkillMetadata.model_validate(
        {
            "name": "sports-brief",
            "description": "Prepare a source-backed sports brief",
            "version": "1.0.0",
            "platforms": ["windows", "linux"],
            "metadata": {
                "hermes": {
                    "tags": ["sports"],
                    "category": "research",
                    "requires_toolsets": ["web"],
                    "fallback_for_tools": ["sports_snapshot"],
                },
                "vellum": {
                    "trigger": ["sports", "standings"],
                    "negative_trigger": ["write sports tests"],
                    "confidence_threshold": 0.25,
                    "route_to_agent": "SportsAgent",
                    "routing_critical": True,
                },
            },
        }
    )

    assert metadata.metadata.hermes.category == "research"
    assert metadata.metadata.vellum == VellumMetadata(
        trigger=["sports", "standings"],
        negative_trigger=["write sports tests"],
        confidence_threshold=0.25,
        route_to_agent="SportsAgent",
        routing_critical=True,
    )


@pytest.mark.parametrize("name", ["Sports Brief", "../sports", "_hidden", "sports/brief"])
def test_skill_metadata_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        SkillMetadata(name=name, description="Valid description")


def test_vellum_threshold_must_be_a_probability() -> None:
    with pytest.raises(ValidationError):
        VellumMetadata(confidence_threshold=1.1)


@pytest.mark.parametrize("path", ["../secret.json", "/etc/secret.json", "C:\\secret.json"])
def test_credential_requirement_rejects_machine_or_traversing_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        CredentialRequirement(path=path)


from agent.skills import SkillPackageError, SkillPackageParser


def write_skill(root: Path, frontmatter: str, body: str = "# Sports Brief\n\n## Procedure\nAnswer carefully.") -> Path:
    root.mkdir(parents=True)
    path = root / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")
    return path


def test_parser_reads_hermes_frontmatter_and_body(tmp_path: Path) -> None:
    root = tmp_path / "sports-brief"
    write_skill(
        root,
        """name: sports-brief
description: Prepare a source-backed sports brief
metadata:
  hermes:
    category: research
  vellum:
    trigger: [sports, standings]
    routing_critical: true""",
    )

    package = SkillPackageParser().parse(root)

    assert package.metadata.name == "sports-brief"
    assert package.metadata.metadata.hermes.category == "research"
    assert package.metadata.metadata.vellum.routing_critical is True
    assert package.body.startswith("# Sports Brief")


def test_parser_rejects_missing_or_unclosed_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "broken"
    root.mkdir()
    (root / "SKILL.md").write_text("# No frontmatter", encoding="utf-8")

    with pytest.raises(SkillPackageError, match="frontmatter"):
        SkillPackageParser().parse(root)


def test_parser_rejects_oversized_skill_file(tmp_path: Path) -> None:
    root = tmp_path / "large"
    write_skill(root, "name: large\ndescription: Large skill", body="x" * 256)

    with pytest.raises(SkillPackageError, match="size limit"):
        SkillPackageParser(max_file_bytes=128).parse(root)


def test_support_file_read_stays_inside_package(tmp_path: Path) -> None:
    root = tmp_path / "safe"
    write_skill(root, "name: safe\ndescription: Safe skill")
    references = root / "references"
    references.mkdir()
    (references / "guide.md").write_text("safe guide", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    parser = SkillPackageParser()

    assert parser.read_support_file(root, "references/guide.md") == "safe guide"
    with pytest.raises(SkillPackageError, match="inside the skill package"):
        parser.read_support_file(root, "../secret.txt")
