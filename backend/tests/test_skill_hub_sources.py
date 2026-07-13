from agent.skills import (
    BrowseShSource,
    ClawHubSource,
    GitHubSource,
    LobeHubSource,
    OfficialSkillSource,
    SkillsShSource,
    SkillsMpSource,
    UrlSkillSource,
    WellKnownSkillSource,
    create_skill_source_router,
    GuardedHttpClient,
)
import socket
import pytest


SKILL = "---\nname: remote\ndescription: Remote skill\n---\n# Remote\n"


class FakeHttp:
    def __init__(self):
        self.text = {}
        self.json = {}

    def get_text(self, url):
        return self.text[url]

    def get_json(self, url):
        return self.json[url]


def test_router_exposes_all_documented_source_ids() -> None:
    ids = {source.source_id for source in create_skill_source_router(FakeHttp())}

    assert {
        "official",
        "github",
        "url",
        "well-known",
        "skills-sh",
        "clawhub",
        "claude-marketplace",
        "lobehub",
        "browse-sh",
        "skillsmp",
    } <= ids


def test_direct_url_source_builds_single_file_bundle() -> None:
    http = FakeHttp()
    url = "https://example.com/SKILL.md"
    http.text[url] = SKILL

    bundle = UrlSkillSource(http).fetch(url)

    assert bundle.name == "remote"
    assert bundle.files == {"SKILL.md": SKILL}
    assert bundle.trust_level == "community"


def test_well_known_source_searches_index_and_fetches_files() -> None:
    http = FakeHttp()
    index = "https://example.com/.well-known/skills/index.json"
    http.json[index] = {
        "skills": [
            {
                "name": "remote",
                "description": "Remote workflow",
                "files": {"SKILL.md": "https://example.com/skills/remote/SKILL.md"},
            }
        ]
    }
    http.text["https://example.com/skills/remote/SKILL.md"] = SKILL
    source = WellKnownSkillSource(http)

    results = source.search("https://example.com", query="workflow")
    bundle = source.fetch("well-known:https://example.com/remote")

    assert results[0].name == "remote"
    assert bundle.files["SKILL.md"] == SKILL


def test_github_source_fetches_repository_tree_files() -> None:
    http = FakeHttp()
    api = "https://api.github.com/repos/acme/skills/contents/skills/remote"
    http.json[api] = [
        {"type": "file", "path": "skills/remote/SKILL.md", "download_url": "https://raw.example/SKILL.md"},
        {"type": "file", "path": "skills/remote/references/guide.md", "download_url": "https://raw.example/guide.md"},
    ]
    http.text["https://raw.example/SKILL.md"] = SKILL
    http.text["https://raw.example/guide.md"] = "Guide"

    bundle = GitHubSource(http).fetch("github/acme/skills/skills/remote")

    assert bundle.files == {"SKILL.md": SKILL, "references/guide.md": "Guide"}


def test_catalog_adapters_normalize_clawhub_lobehub_browsesh_and_official() -> None:
    http = FakeHttp()
    http.json["https://clawhub.ai/api/v1/skills/remote"] = {
        "name": "remote",
        "description": "Remote",
        "files": {"SKILL.md": SKILL},
    }
    http.json["https://chat-agents.lobehub.com/remote.json"] = {
        "identifier": "remote",
        "meta": {"title": "Remote agent", "description": "Remote agent workflow"},
        "config": {"systemRole": "Follow the verified workflow."},
    }
    http.json["https://browse.sh/api/skills/example.com/remote"] = {
        "name": "remote",
        "description": "Remote browser workflow",
        "skillMdUrl": "https://cdn.example/remote.md",
    }
    http.text["https://cdn.example/remote.md"] = SKILL

    assert ClawHubSource(http).fetch("clawhub/remote").name == "remote"
    assert "Follow the verified workflow" in LobeHubSource(http).fetch("lobehub/remote").files["SKILL.md"]
    assert BrowseShSource(http).fetch("browse-sh/example.com/remote").files["SKILL.md"] == SKILL
    assert OfficialSkillSource({"remote": {"SKILL.md": SKILL}}).fetch("official/remote").trust_level == "official"


def test_skills_sh_resolves_underlying_github_identifier() -> None:
    http = FakeHttp()
    detail = "https://skills.sh/acme/skills/remote"
    http.text[detail] = '<a href="https://github.com/acme/skills/tree/main/skills/remote">source</a>'
    api = "https://api.github.com/repos/acme/skills/contents/skills/remote"
    http.json[api] = [
        {"type": "file", "path": "skills/remote/SKILL.md", "download_url": "https://raw.example/SKILL.md"}
    ]
    http.text["https://raw.example/SKILL.md"] = SKILL

    bundle = SkillsShSource(http).fetch("skills-sh/acme/skills/remote")

    assert bundle.source == "skills-sh"
    assert bundle.identifier == "skills-sh/acme/skills/remote"


def test_skills_sh_and_clawhub_search_return_embedded_catalog_metadata() -> None:
    http = FakeHttp()
    http.json["https://skills.sh/api/search?q=frontend"] = {
        "skills": [{"id": "anthropics/skills/frontend-design", "name": "frontend-design", "source": "anthropics/skills", "installs": 10}]
    }
    http.json["https://clawhub.ai/api/v1/search?q=frontend"] = {
        "results": [{"slug": "frontend", "displayName": "Frontend Design", "summary": "Frontend UI design", "downloads": 20}]
    }

    skillssh = SkillsShSource(http).search("frontend")[0]
    clawhub = ClawHubSource(http).search("frontend")[0]

    assert skillssh.identifier == "skills-sh/anthropics/skills/frontend-design"
    assert skillssh.extra["category"] == "design"
    assert clawhub.identifier == "clawhub/frontend"
    assert clawhub.extra["downloads"] == 20


def test_skillsmp_search_resolves_repository_and_exposes_quota_and_provenance() -> None:
    http = FakeHttp()
    http.json["https://skillsmp.test/api/v1/skills/search?q=deploy&limit=10&page=1"] = {
        "success": True,
        "data": {"skills": [{"id": "remote", "name": "remote", "description": "Deploy", "githubUrl": "https://github.com/acme/skills/tree/main/skills/remote"}]},
        "rate_limit": {"remaining": 9},
    }
    http.json["https://api.github.com/repos/acme/skills/contents/skills/remote"] = [
        {"type": "file", "path": "skills/remote/SKILL.md", "download_url": "https://raw.example/SKILL.md"}
    ]
    http.text["https://raw.example/SKILL.md"] = SKILL
    source = SkillsMpSource(http, base_url="https://skillsmp.test/api/v1")

    result = source.search("deploy")[0]
    bundle = source.fetch(result.identifier)

    assert result.extra["rate_limit"]["remaining"] == 9
    assert bundle.metadata["repository_url"] == "https://github.com/acme/skills"
    assert bundle.metadata["source_ref"] == "main"


def test_guarded_http_rejects_ssrf_and_dns_rebinding(monkeypatch) -> None:
    with pytest.raises(ValueError, match="blocked"):
        GuardedHttpClient._validate("http://127.0.0.1/secret")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))])
    with pytest.raises(ValueError, match="blocked"):
        GuardedHttpClient._validate_dns("public.example")
