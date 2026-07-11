from agent.agents.base import MemoryProposal
from agent.tools.capabilities.memory_service import MemoryCapabilityService


def test_memory_service_builds_context_pack_from_project_context_and_cards(tmp_path):
    vault = tmp_path / "Vault"
    memory_dir = vault / "Agent" / "Memories" / "Shared"
    memory_dir.mkdir(parents=True)
    (memory_dir / "style.md").write_text(
        "---\nscope: shared\nconfidence: 0.9\n---\n\nUser prefers concise answers.\n",
        encoding="utf-8",
    )
    (vault / "Meta").mkdir()
    (vault / "Meta" / "profile.md").write_text("User is building Vellum.", encoding="utf-8")
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")

    pack = service.build_context_pack({"query": "How should I answer?", "thread_id": "t1", "agent_name": "XAgent"})

    assert pack["action"] == "memory.build_context_pack"
    assert "concise answers" in pack["cards"][0]["text"]
    assert pack["agent_name"] == "XAgent"


def test_memory_service_reviews_proposals_and_detects_conflicts(tmp_path):
    service = MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db")
    proposals = [
        MemoryProposal(scope="memory", claim="User likes long answers.", evidence="one vague turn", confidence=0.4),
        MemoryProposal(scope="memory", claim="User likes concise answers.", evidence="three explicit corrections", confidence=0.9),
    ]

    reviewed = service.review_proposals({"proposals": proposals})
    conflicts = service.detect_conflicts({"claims": ["User likes concise answers.", "User dislikes concise answers."]})

    assert [item["claim"] for item in reviewed["accepted"]] == ["User likes concise answers."]
    assert reviewed["rejected"][0]["claim"] == "User likes long answers."
    assert conflicts["conflicts"]


def test_memory_service_create_card_writes_durable_memory(tmp_path):
    vault = tmp_path / "Vault"
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")

    result = service.create_card(
        {
            "scope": "shared",
            "title": "Answer style",
            "summary": "User prefers concise answers.",
            "evidence": "Repeated corrections.",
            "visible_to": ["VellumAgent", "MemoryAgent"],
        }
    )

    path = vault / result["path"]
    assert path.exists()
    assert "User prefers concise answers." in path.read_text(encoding="utf-8")


def test_memory_service_create_card_sanitizes_traversal_scope(tmp_path):
    vault = tmp_path / "Vault"
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")

    result = service.create_card(
        {
            "scope": "../../../Outside",
            "title": "Traversal",
            "summary": "Should stay in memories.",
        }
    )

    memory_root = (vault / "Agent" / "Memories").resolve()
    path = (vault / result["path"]).resolve()
    assert path.is_relative_to(memory_root)
    assert ".." not in result["path"].split("/")
    assert path.exists()


def test_memory_service_create_card_does_not_overwrite_rapid_duplicates(tmp_path):
    vault = tmp_path / "Vault"
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")

    first = service.create_card({"scope": "shared", "title": "Duplicate", "summary": "First"})
    second = service.create_card({"scope": "shared", "title": "Duplicate", "summary": "Second"})

    first_path = vault / first["path"]
    second_path = vault / second["path"]
    assert first_path != second_path
    assert first_path.exists()
    assert second_path.exists()
    assert "First" in first_path.read_text(encoding="utf-8")
    assert "Second" in second_path.read_text(encoding="utf-8")


def test_memory_service_create_card_writes_safe_frontmatter(tmp_path):
    vault = tmp_path / "Vault"
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")

    result = service.create_card(
        {
            "scope": 'shared"\nattacker: true',
            "title": "Injected\nattacker: true",
            "summary": "Summary",
            "visible_to": ['VellumAgent"\nattacker: true', "MemoryAgent"],
        }
    )

    text = (vault / result["path"]).read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    assert 'scope: "shared-attacker-true"' in frontmatter
    assert 'visible_to: ["VellumAgent\\"\\nattacker: true", "MemoryAgent"]' in frontmatter
    assert "\nattacker: true\n" not in frontmatter


def test_memory_card_search_enforces_agent_scope_and_visibility(tmp_path):
    vault = tmp_path / "Vault"
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")
    service.create_card(
        {
            "scope": "shared",
            "title": "Shared preference",
            "summary": "User prefers direct answers.",
        }
    )
    service.create_card(
        {
            "scope": "agent:XAgent",
            "title": "X private context",
            "summary": "Private X drafting context.",
            "visible_to": ["XAgent", "VellumAgent", "MemoryAgent"],
        }
    )
    service.create_card(
        {
            "scope": "agent:SportsAgent",
            "title": "Sports private context",
            "summary": "Private sports analysis context.",
            "visible_to": ["SportsAgent", "MemoryAgent"],
        }
    )

    x_cards = service.search_cards({"agent_name": "XAgent", "query": "context", "limit": 20})["cards"]
    vellum_cards = service.search_cards({"agent_name": "VellumAgent", "query": "context", "limit": 20})["cards"]

    assert any("X private context" in card["text"] for card in x_cards)
    assert not any("Sports private context" in card["text"] for card in x_cards)
    assert any("X private context" in card["text"] for card in vellum_cards)
    assert not any("Sports private context" in card["text"] for card in vellum_cards)
