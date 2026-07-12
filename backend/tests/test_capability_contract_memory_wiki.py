from agent.contracts.capabilities import public_capability_contract


def test_capabilities_expose_orchestrator_and_wiki_without_storage_details():
    features = public_capability_contract()["features"]

    assert features["memory_orchestrator"]["enabled"] is True
    assert features["memory_orchestrator"]["endpoints"]["summary"] == "/api/memory/summary"
    assert features["knowledge_wiki"]["enabled"] is True
    assert features["knowledge_wiki"]["endpoints"]["query"] == "/api/knowledge/query"
    assert not any(name in features for name in ("fts5", "honcho", "chroma", "sqlite"))
