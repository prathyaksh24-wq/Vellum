from agent.skills import (
    BrowseShSource,
    ClawHubSource,
    GitHubSource,
    LobeHubSource,
    OfficialSkillSource,
    SkillsShSource,
    UrlSkillSource,
    WellKnownSkillSource,
    create_skill_source_router,
)


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
