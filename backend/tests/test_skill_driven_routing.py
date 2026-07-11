from pathlib import Path

import yaml

from agent.agents.skill_router import SkillRoute, SkillRouteResolver
from agent.memory.skills import SkillStore


def write_skill(root: Path, payload: dict):
    package = root / "packages" / "routing" / payload["id"]
    package.mkdir(parents=True)
    frontmatter = {
        "name": payload["id"],
        "description": payload["name"],
        "metadata": {"vellum": {
            "trigger": payload.get("trigger", []),
            "negative_trigger": payload.get("negative_trigger", []),
            "confidence_threshold": payload.get("confidence_threshold", 0.75),
            "route_to_agent": payload.get("route_to_agent"),
            "routing_critical": bool(payload.get("route_to_agent")),
        }},
    }
    (package / "SKILL.md").write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n# Route\n\n## Procedure\n{payload['instructions']}\n",
        encoding="utf-8",
    )


def test_skill_route_resolver_routes_matching_skill(tmp_path):
    write_skill(
        tmp_path,
        {
            "id": "skill-route-sports-agent-v1",
            "name": "Route sports questions to SportsAgent",
            "trigger": ["NBA", "Formula One", "Arsenal", "Champions League"],
            "confidence_threshold": 0.25,
            "route_to_agent": "SportsAgent",
            "instructions": "Consult SportsAgent before answering.",
        },
    )
    resolver = SkillRouteResolver(SkillStore(root=tmp_path))

    route = resolver.resolve("Give me Arsenal and Champions League updates")

    assert route == SkillRoute(agent_name="SportsAgent", skill_id="skill-route-sports-agent-v1")


def test_skill_store_default_root_is_repo_anchored():
    store = SkillStore()

    assert store.root.is_absolute()
    assert store.root.name == ".skills"


def test_skill_route_resolver_respects_negative_trigger(tmp_path):
    write_skill(
        tmp_path,
        {
            "id": "skill-route-sports-agent-v1",
            "name": "Route sports questions to SportsAgent",
            "trigger": ["sports", "UFC"],
            "negative_trigger": ["UFC"],
            "confidence_threshold": 0.25,
            "route_to_agent": "SportsAgent",
            "instructions": "Consult SportsAgent before answering.",
        },
    )
    resolver = SkillRouteResolver(SkillStore(root=tmp_path))

    assert resolver.resolve("Any UFC updates?") is None


def test_skill_route_resolver_routes_canonical_routing_skill(tmp_path):
    package = tmp_path / "packages" / "routing" / "sports-route"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        """---
name: sports-route
description: Route sports questions
metadata:
  vellum:
    trigger: [Arsenal, Champions League]
    confidence_threshold: 0.25
    route_to_agent: SportsAgent
    routing_critical: true
---
# Route sports

## Procedure
Consult SportsAgent before answering.
""",
        encoding="utf-8",
    )

    route = SkillRouteResolver(SkillStore(root=tmp_path)).resolve("Arsenal Champions League update")

    assert route == SkillRoute(agent_name="SportsAgent", skill_id="sports-route")
