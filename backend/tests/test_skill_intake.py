from agent.skills.intake import resolve_skill_intake
from fastapi.testclient import TestClient

from agent import api
from agent.skills import HubSkillBundle, SkillHub, SkillSurfaceService
import agent.tools.skill_hub as skill_hub_tools


SAFE_SKILL = """---
name: remote-skill
description: Remote skill
---
# Remote

## Procedure
Use verified inputs.
"""


class FakeMarketplaceSource:
    source_id = "skills-sh"

    @staticmethod
    def matches(identifier: str) -> bool:
        return identifier.startswith("skills-sh/")

    @staticmethod
    def fetch(identifier: str) -> HubSkillBundle:
        return HubSkillBundle("remote-skill", "Remote skill", "skills-sh", identifier, "trusted", {"SKILL.md": SAFE_SKILL})


def test_skills_sh_url_routes_to_marketplace_install() -> None:
    target = resolve_skill_intake("https://www.skills.sh/anthropics/skills/frontend-design")

    assert target.kind == "marketplace"
    assert target.source == "skills-sh"
    assert target.value == "skills-sh/anthropics/skills/frontend-design"


def test_document_url_and_conversation_route_to_authoring() -> None:
    assert resolve_skill_intake("https://example.com/procedure").kind == "author"
    assert resolve_skill_intake("https://github.com/acme/skills/tree/main/skills/remote").kind == "author"
    assert resolve_skill_intake("github/acme/skills/skills/remote").kind == "author"
    assert resolve_skill_intake("learn this workflow from our conversation").kind == "author"


def test_marketplace_intake_returns_only_after_pending_is_visible(monkeypatch, tmp_path) -> None:
    root = tmp_path / ".skills"
    source = FakeMarketplaceSource()
    surface = SkillSurfaceService(root, logs_root=tmp_path / "logs", sources=[source])
    monkeypatch.setattr(api, "_skill_surface_singleton", surface)
    monkeypatch.setattr(skill_hub_tools, "_HUB", SkillHub(root, sources=[source]))
    monkeypatch.setattr(skill_hub_tools, "_MUTATIONS", None)

    with TestClient(api.app) as client:
        response = client.post("/api/skills/learn", json={"source": "skills-sh/acme/skills/remote"})
        pending = client.get("/api/skills/v2/catalog", params={"view": "pending"})

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["mutation"]["id"] == pending.json()["items"][0]["id"]
