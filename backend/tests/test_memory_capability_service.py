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


def test_memory_service_exposes_proposals_but_not_direct_durable_writes(tmp_path):
    service = MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db")

    names = service.build_registry().names()

    assert "memory.propose_card" in names
    assert "memory.create_card" not in names


def test_memory_card_search_enforces_agent_scope_and_visibility(tmp_path):
    vault = tmp_path / "Vault"
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")
    memory_dir = vault / "Agent" / "Memories"
    fixtures = {
        "shared.md": (
            '---\nscope: "shared"\nvisible_to: []\n---\n\n'
            "# Shared preference\n\nUser prefers direct answers.\n"
        ),
        "x.md": (
            '---\nscope: "agent:xagent"\n'
            'visible_to: ["XAgent", "VellumAgent", "MemoryAgent"]\n---\n\n'
            "# X private context\n\nPrivate X drafting context.\n"
        ),
        "sports.md": (
            '---\nscope: "agent:sportsagent"\n'
            'visible_to: ["SportsAgent", "MemoryAgent"]\n---\n\n'
            "# Sports private context\n\nPrivate sports analysis context.\n"
        ),
    }
    memory_dir.mkdir(parents=True)
    for name, text in fixtures.items():
        (memory_dir / name).write_text(text, encoding="utf-8")

    x_cards = service.search_cards({"agent_name": "XAgent", "query": "context", "limit": 20})["cards"]
    vellum_cards = service.search_cards({"agent_name": "VellumAgent", "query": "context", "limit": 20})["cards"]

    assert any("X private context" in card["text"] for card in x_cards)
    assert not any("Sports private context" in card["text"] for card in x_cards)
    assert any("X private context" in card["text"] for card in vellum_cards)
    assert not any("Sports private context" in card["text"] for card in vellum_cards)
