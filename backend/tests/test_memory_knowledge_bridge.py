from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.tools.capabilities.memory_service import MemoryCapabilityService


class FakeKnowledgeWiki:
    def query(self, query: str, *, limit: int = 4):
        assert query == "How does Vellum memory work?"
        assert limit == 4
        return {
            "results": [
                {
                    "ref": "kw-memory",
                    "title": "Memory Orchestrator",
                    "type": "concept",
                    "description": "Canonical memory coordination.",
                    "updated": "2026-07-10",
                    "content": "This body must not be copied into the packet.",
                }
            ]
        }


def test_memory_packet_routes_to_knowledge_by_reference_only(tmp_path):
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(
            vault_root=tmp_path / "Vault",
            sessions_db=tmp_path / "cards.db",
        ),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory",
        knowledge_wiki=FakeKnowledgeWiki(),
    )

    packet = orchestrator.build_memory_packet(
        thread_id="thread-1",
        query="How does Vellum memory work?",
    )

    assert packet["knowledge_refs"] == [
        {
            "ref": "kw-memory",
            "title": "Memory Orchestrator",
            "type": "concept",
            "description": "Canonical memory coordination.",
            "updated": "2026-07-10",
        }
    ]
    assert "body must not be copied" not in str(packet)
