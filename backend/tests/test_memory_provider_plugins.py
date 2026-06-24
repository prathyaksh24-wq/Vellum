from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.plugins.memory_orchestrator import memory_orchestrator_plugin_status
from agent.tools.capabilities.memory_service import MemoryCapabilityService


def test_memory_orchestrator_plugin_reports_builtin_provider_health(tmp_path):
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory-files",
    )

    status = memory_orchestrator_plugin_status(orchestrator).model_dump()

    providers = {provider["id"]: provider for provider in status["metadata"]["providers"]}
    assert providers["sqlite"]["status"] == "ready"
    assert providers["fts5"]["status"] == "ready"
    assert providers["chroma"]["type"] == "semantic"
    assert providers["honcho"]["status"] in {"ready", "degraded"}
    assert providers["obsidian"]["status"] == "ready"
