import sys
from types import ModuleType, SimpleNamespace

from qdrant_client import QdrantClient

from agent.rag.embedder import Embedder, VECTOR_SIZE
from agent.rag.store import VectorStore
from agent.tools import vault_search


class FakeSentenceTransformer:
    def __init__(self, model_name):
        self.model_name = model_name

    def encode(self, text, normalize_embeddings=True, batch_size=None):
        if isinstance(text, list):
            return [SimpleNamespace(tolist=lambda value=item: [float(len(value))]) for item in text]
        return SimpleNamespace(tolist=lambda: [float(len(text))])


def test_embedder_lazy_loads_sentence_transformer(monkeypatch):
    fake_module = ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    embedder = Embedder("fake/model")

    assert embedder.embed("abc") == [3.0]
    assert embedder.embed_batch(["a", "abcd"]) == [[1.0], [4.0]]
    assert embedder.model.model_name == "fake/model"


def test_vector_store_creates_collections_and_searches_in_memory():
    client = QdrantClient(":memory:")
    store = VectorStore(client=client)
    vector = [0.0] * VECTOR_SIZE
    vector[0] = 1.0

    point_id = store.upsert(
        collection="obsidian_vault",
        text="NBA context",
        embedding=vector,
        metadata={"folder": "Sports/NBA", "path": "Sports/NBA/latest.md"},
    )
    results = store.search("obsidian_vault", vector, top_k=1, score_threshold=0.0)

    assert point_id
    assert results[0]["text"] == "NBA context"
    assert results[0]["metadata"]["folder"] == "Sports/NBA"
    assert results[0]["score"] > 0


def test_vector_store_uses_local_qdrant_path(monkeypatch, tmp_path):
    class FakeSettings:
        qdrant_local_path = tmp_path / "qdrant-local"
        qdrant_host = "localhost"
        qdrant_port = 6333

    monkeypatch.setattr("agent.rag.store.get_settings", lambda: FakeSettings())

    store = VectorStore()

    assert FakeSettings.qdrant_local_path.exists()
    assert {"obsidian_vault", "agent_queries"} <= {
        collection.name for collection in store.client.get_collections().collections
    }
    store.client.close()


def test_vault_search_uses_vector_backend_and_filters_private_chunks(monkeypatch):
    class FakeEmbedder:
        def embed(self, text):
            return [1.0]

    class FakeStore:
        def search(self, collection, embedding, top_k=10, score_threshold=0.0):
            return [
                {
                    "text": "NBA vector context",
                    "score": 0.91,
                    "metadata": {"folder": "Sports/NBA", "path": "Sports/NBA/latest.md"},
                },
                {
                    "text": "NBA private book note",
                    "score": 0.95,
                    "metadata": {"folder": "Books", "path": "Books/private.md"},
                },
            ]

    class FakeMemory:
        def log_query(self, query, source, confidence):
            return 1

    monkeypatch.setattr(vault_search, "Embedder", FakeEmbedder)
    monkeypatch.setattr(vault_search, "VectorStore", FakeStore)
    monkeypatch.setattr(vault_search, "LongTermMemory", FakeMemory)
    monkeypatch.setattr(vault_search, "_store_query", lambda query: None)
    monkeypatch.setattr(
        vault_search,
        "_rerank",
        lambda query, results: sorted(
            [(item["score"], item) for item in results],
            key=lambda item: item[0],
            reverse=True,
        ),
    )

    result = vault_search.search_my_notes.func("nba")

    assert "NBA vector context" in result
    assert "private book note" not in result


def test_vault_search_falls_back_to_vault_when_vector_backend_unavailable(monkeypatch):
    class BrokenEmbedder:
        def embed(self, text):
            raise RuntimeError("model unavailable")

    class FakeVault:
        def __init__(self, vault_path):
            self.vault_path = vault_path

        def search_notes(self, query, limit=12):
            return [
                {
                    "text": "NBA fallback context",
                    "score": 1.0,
                    "metadata": {"folder": "Sports/NBA", "path": "Sports/NBA/latest.md"},
                }
            ]

    class FakeMemory:
        def log_query(self, query, source, confidence):
            return 1

    monkeypatch.setattr(vault_search, "Embedder", BrokenEmbedder)
    monkeypatch.setattr(vault_search, "ObsidianVault", FakeVault)
    monkeypatch.setattr(vault_search, "LongTermMemory", FakeMemory)
    monkeypatch.setattr(vault_search, "_store_query", lambda query: None)
    monkeypatch.setattr(vault_search, "_rerank", lambda query, results: [(item["score"], item) for item in results])

    result = vault_search.search_my_notes.func("NBA latest standings")

    assert "NBA fallback context" in result


def test_vault_search_blocks_red_queries():
    result = vault_search.search_my_notes.func("password=super-secret")

    assert "blocked for privacy" in result.casefold()
