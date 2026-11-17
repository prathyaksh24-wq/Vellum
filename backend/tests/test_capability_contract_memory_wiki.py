from agent.contracts.capabilities import public_capability_contract


def test_capabilities_expose_orchestrator_without_storage_details():
    features = public_capability_contract()["features"]

    assert features["memory_orchestrator"]["enabled"] is True
    assert features["memory_orchestrator"]["endpoints"]["summary"] == "/api/memory/summary"
    assert "knowledge_wiki" not in features
    assert not any(name in features for name in ("fts5", "honcho", "chroma", "sqlite"))
