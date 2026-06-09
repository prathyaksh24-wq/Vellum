import sys
from types import ModuleType, SimpleNamespace

from agent.rag.embedder import Embedder, VECTOR_SIZE
from agent.rag.store import VectorStore
from agent.tools import vault_search


class FakeSettings:
    min_retrieval_score = 0.65
    max_context_chunks = 5
    max_context_tokens = 3000
    agent_notes_folder = "Agent"
    obsidian_vault_path = None
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
    def __init__(self, name: str):
        self.name = name
        self.documents: list[str] = []
        self.metadatas: list[dict] = []
        self.embeddings: list[list[float]] = []
        self.ids: list[str] = []

    def upsert(self, ids, embeddings, documents, metadatas):
        self.ids.extend(ids)
        self.embeddings.extend(embeddings)
        self.documents.extend(documents)
        self.metadatas.extend(metadatas)

    def query(self, query_embeddings, n_results, where=None, include=None):
        rows = []
        for document, metadata, embedding in zip(self.documents, self.metadatas, self.embeddings):
            if where and any(metadata.get(key) != value for key, value in where.items()):
                continue
            distance = 0.0 if embedding == query_embeddings[0] else 1.0
            rows.append((distance, document, metadata))
        rows.sort(key=lambda row: row[0])
        rows = rows[:n_results]
        return {
            "documents": [[row[1] for row in rows]],
            "metadatas": [[row[2] for row in rows]],
            "distances": [[row[0] for row in rows]],
        }


class FakeChromaClient:
    def __init__(self, path=None, settings=None):
        self.path = path
        self.settings = settings
        self.collections: dict[str, FakeChromaCollection] = {}

    def get_or_create_collection(self, name, metadata=None):
        if name not in self.collections:
            self.collections[name] = FakeChromaCollection(name)
        return self.collections[name]

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


def test_vector_store_uses_embedded_chroma_path(monkeypatch, tmp_path):
    class FakeSettings:
        chroma_path = tmp_path / "chroma"

    fake_chromadb = ModuleType("chromadb")
    fake_chromadb.PersistentClient = FakeChromaClient
    fake_chromadb.EphemeralClient = FakeChromaClient
    fake_config = ModuleType("chromadb.config")
    fake_config.Settings = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)
    monkeypatch.setitem(sys.modules, "chromadb.config", fake_config)
    monkeypatch.setattr("agent.rag.store.get_settings", lambda: FakeSettings())

    store = VectorStore()

    assert FakeSettings.chroma_path.exists()
    assert {"obsidian_vault", "agent_queries"} <= set(store.collection_names())


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

    monkeypatch.setattr(vault_search, "get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(vault_search, "get_vector_store", lambda: FakeStore())
    monkeypatch.setattr(vault_search, "_settings", lambda: type("Settings", (FakeSettings,), {"enable_vector_search": True})())
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

    monkeypatch.setattr(vault_search, "get_embedder", lambda: BrokenEmbedder())
    monkeypatch.setattr(vault_search, "ObsidianVault", FakeVault)
    monkeypatch.setattr(vault_search, "_settings", lambda: type("Settings", (FakeSettings,), {"enable_vector_search": True})())
    monkeypatch.setattr(vault_search, "_store_query", lambda query: None)
    monkeypatch.setattr(vault_search, "_rerank", lambda query, results: [(item["score"], item) for item in results])

    result = vault_search.search_my_notes.func("NBA latest standings")

    assert "NBA fallback context" in result


def test_vault_search_blocks_red_queries():
    result = vault_search.search_my_notes.func("password=super-secret")

    assert "blocked for privacy" in result.casefold()


def test_vault_search_default_path_does_not_require_vector_backend(monkeypatch):
    class ExplodingEmbedder:
        def embed(self, text):
            raise AssertionError("vector embedding should not run by default")

    class FakeVault:
        def __init__(self, vault_path):
            self.vault_path = vault_path

        def search_notes(self, query, limit=12):
            return [
                {
                    "text": "Naval note about attention",
                    "score": 1.0,
                    "metadata": {"folder": "X/naval", "path": "X/naval/latest-50.md"},
                }
            ]

    monkeypatch.setattr(vault_search, "_settings", lambda: FakeSettings())
    monkeypatch.setattr(vault_search, "get_embedder", lambda: ExplodingEmbedder())
    monkeypatch.setattr(vault_search, "ObsidianVault", FakeVault)
    monkeypatch.setattr(vault_search, "_store_query", lambda query: None)

    result = vault_search.search_my_notes.func("naval attention")

    assert "Naval note about attention" in result
