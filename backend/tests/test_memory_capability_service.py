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
