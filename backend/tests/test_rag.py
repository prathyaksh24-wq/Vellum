import sys
from types import ModuleType, SimpleNamespace

from agent.rag.embedder import Embedder, VECTOR_SIZE
from agent.rag.store import VectorStore


class FakeSettings:
    min_retrieval_score = 0.65
    max_context_chunks = 5
    max_context_tokens = 3000
    enable_vector_search = False
    enable_cross_encoder_rerank = False
    enable_query_vector_storage = False


class FakeSentenceTransformer:
    def __init__(self, model_name):
        self.model_name = model_name

    def encode(self, text, normalize_embeddings=True, batch_size=None):
        if isinstance(text, list):
            return [SimpleNamespace(tolist=lambda value=item: [float(len(value))]) for item in text]
        return SimpleNamespace(tolist=lambda: [float(len(text))])


class FakeChromaCollection:
    def __init__(self, name):
        self.name = name
        self.rows = []

    def upsert(self, ids, embeddings, documents, metadatas):
        self.rows.append(
            {
                "id": ids[0],
                "embedding": embeddings[0],
                "document": documents[0],
                "metadata": metadatas[0],
            }
        )

    def query(self, query_embeddings, n_results, where=None, include=None):
        rows = self.rows
        if where:
            rows = [row for row in rows if all(row["metadata"].get(key) == value for key, value in where.items())]
        rows = rows[:n_results]
        return {
            "documents": [[row["document"] for row in rows]],
            "metadatas": [[row["metadata"] for row in rows]],
            "distances": [[0.0 for _ in rows]],
        }

    def delete(self, where):
        self.rows = [row for row in self.rows if not all(row["metadata"].get(key) == value for key, value in where.items())]


class FakeChromaClient:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, name, metadata=None):
        collection = self.collections.get(name)
        if collection is None:
            collection = FakeChromaCollection(name)
            self.collections[name] = collection
        return collection

    def list_collections(self):
        return list(self.collections.values())


def test_embedder_lazy_loads_sentence_transformer(monkeypatch):
    fake_module = ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    embedder = Embedder("fake/model")

    assert embedder.embed("abc") == [3.0]
    assert embedder.embed_batch(["a", "abcd"]) == [[1.0], [4.0]]
    assert embedder.model.model_name == "fake/model"


def test_vector_store_creates_collections_and_searches_in_memory():
    client = FakeChromaClient()
    store = VectorStore(client=client)
    vector = [0.0] * VECTOR_SIZE
    vector[0] = 1.0

    point_id = store.upsert(
        collection="agent_queries",
        text="NBA context",
        embedding=vector,
        metadata={"folder": "Sports/NBA", "path": "Sports/NBA/latest.md"},
    )
    results = store.search("agent_queries", vector, top_k=1, score_threshold=0.0)

    assert point_id
    assert results[0]["text"] == "NBA context"
    assert results[0]["metadata"]["folder"] == "Sports/NBA"
    assert results[0]["score"] > 0


def test_vector_store_uses_local_chroma_path(monkeypatch, tmp_path):
    created_paths = []

    class FakeChromaSettings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeChromaModule(ModuleType):
        def PersistentClient(self, path, settings):
            created_paths.append(path)
            return FakeChromaClient()

        def EphemeralClient(self, settings):
            return FakeChromaClient()

    fake_chroma = FakeChromaModule("chromadb")
    fake_chroma_config = ModuleType("chromadb.config")
    fake_chroma_config.Settings = FakeChromaSettings
    monkeypatch.setitem(sys.modules, "chromadb", fake_chroma)
    monkeypatch.setitem(sys.modules, "chromadb.config", fake_chroma_config)

    class FakeSettings:
        chroma_path = tmp_path / "chroma"

    monkeypatch.setattr("agent.rag.store.get_settings", lambda: FakeSettings())

    store = VectorStore()

    assert FakeSettings.chroma_path.exists()
    assert created_paths == [str(FakeSettings.chroma_path)]
    assert {"agent_queries"} <= {
        collection.name for collection in store.client.list_collections()
    }
