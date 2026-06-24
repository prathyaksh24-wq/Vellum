from agent.memory.provider_extensions import MemoryProviderExtensionManager, build_default_memory_provider_extensions


def test_default_memory_provider_extensions_are_optional_until_configured(monkeypatch):
    monkeypatch.delenv("MEMORY_EXTENSION_PROVIDERS", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_KEY", raising=False)
    monkeypatch.delenv("SUPERMEMORY_API_KEY", raising=False)
    monkeypatch.delenv("HOLOGRAPHIC_MEMORY_ENABLED", raising=False)

    manager = build_default_memory_provider_extensions()

    statuses = {item["id"]: item for item in manager.statuses()}
    assert {"hindsight", "supermemory", "holographic"} <= set(statuses)
    assert statuses["hindsight"]["status"] == "disabled"
    assert statuses["supermemory"]["status"] == "disabled"
    assert statuses["holographic"]["status"] == "disabled"
    assert statuses["hindsight"]["optional"] is True


def test_memory_provider_extension_manager_reports_active_extensions():
    class FakeProvider:
        id = "fake"
        name = "Fake Provider"
        provider_type = "test"
        optional = True
        capabilities = ["memory.prefetch"]

        def is_enabled(self):
            return True

        def is_configured(self):
            return True

        def setup_notes(self):
            return ""

    manager = MemoryProviderExtensionManager([FakeProvider()])

    assert manager.active_provider_ids() == ["fake"]
    assert manager.statuses()[0]["status"] == "ready"
