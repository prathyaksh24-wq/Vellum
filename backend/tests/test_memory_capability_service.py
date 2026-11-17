from agent.agents.base import MemoryProposal
from agent.profiles.execution import ProfileExecution, profile_execution
from agent.tools.capabilities.memory_service import MemoryCapabilityService


def _execution(memories, *, settings=None):
    packet = {'saved_memories': memories}
    if settings is not None:
        packet['settings'] = settings
    return ProfileExecution('MemoryAgent', None, None, '', '', packet, '', 'current')


def test_memory_service_builds_context_pack_from_canonical_memories(tmp_path):
    service = MemoryCapabilityService(sessions_db=tmp_path / "sessions.db")
    memories = [{'id': 3, 'text': 'User prefers concise answers.', 'scope': 'shared'}]

    with profile_execution(_execution(memories)):
        pack = service.build_context_pack({"query": "How should I answer?", "thread_id": "t1", "agent_name": "XAgent"})

    assert pack["action"] == "memory.build_context_pack"
    assert pack["cards"][0]["text"] == "User prefers concise answers."
    assert pack["cards"][0]["path"] == "memory:3"
    assert pack["agent_name"] == "XAgent"


def test_memory_service_has_no_cards_without_a_runtime_packet(tmp_path):
    service = MemoryCapabilityService(sessions_db=tmp_path / "sessions.db")

    assert service.build_context_pack({"query": "anything"})["cards"] == []
    assert service.search_cards({"query": "anything"})["cards"] == []


def test_memory_service_respects_disabled_memory(tmp_path):
    service = MemoryCapabilityService(sessions_db=tmp_path / "sessions.db")
    memories = [{'id': 1, 'text': 'Hidden preference.', 'scope': 'shared'}]

    with profile_execution(_execution(memories, settings={'memory_enabled': False})):
        pack = service.build_context_pack({"query": "preference"})
        search = service.search_cards({"query": "preference"})

    assert pack["disabled"] is True and pack["cards"] == []
    assert search["cards"] == []


def test_memory_service_reviews_proposals_and_detects_conflicts(tmp_path):
    service = MemoryCapabilityService(sessions_db=tmp_path / "sessions.db")
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
    service = MemoryCapabilityService(sessions_db=tmp_path / "sessions.db")

    names = service.build_registry().names()

    assert "memory.propose_card" in names
    assert "memory.create_card" not in names


def test_memory_card_search_enforces_agent_scope(tmp_path):
    service = MemoryCapabilityService(sessions_db=tmp_path / "sessions.db")
    memories = [
        {'id': 1, 'text': 'Shared context: user prefers direct answers.', 'scope': 'shared'},
        {'id': 2, 'text': 'X private context for drafting.', 'scope': 'agent:XAgent'},
        {'id': 3, 'text': 'Sports private context for analysis.', 'scope': 'agent:SportsAgent'},
    ]

    with profile_execution(_execution(memories)):
        x_cards = service.search_cards({"agent_name": "XAgent", "query": "context", "limit": 20})["cards"]
        vellum_cards = service.search_cards({"agent_name": "VellumAgent", "query": "context", "limit": 20})["cards"]

    x_texts = [card["text"] for card in x_cards]
    vellum_texts = [card["text"] for card in vellum_cards]
    assert "X private context for drafting." in x_texts
    assert "Shared context: user prefers direct answers." in x_texts
    assert not any("Sports" in text for text in x_texts)
    assert not any("private context" in text for text in vellum_texts)


def test_profile_memory_lookup_uses_approved_sqlite_packet(tmp_path):
    from agent.agents.memory_agent import MemoryAgent
    service = MemoryCapabilityService(sessions_db=tmp_path / 'sessions.db')
    memories = [{'id': 7, 'text': 'The user prefers terse writing with no emojis.', 'scope': 'global'}]
    with profile_execution(_execution(memories)):
        result = MemoryAgent(memory_service=service).answer('What do you remember about my writing style?')
    assert result.status == 'answered'
    assert result.summary == 'You prefer terse writing with no emojis.'
    assert result.sources[0].path_or_url == 'memory:7'


def test_empty_profile_packet_returns_no_cards(tmp_path):
    service = MemoryCapabilityService(sessions_db=tmp_path / 'sessions.db')
    with profile_execution(_execution([])):
        assert service.build_context_pack({'query': 'answers'})['cards'] == []
