"""ChromaDB vector store wrapper.

Embedded, on-disk Chroma (a `PersistentClient`) — no separate server or
Docker container. One client per process per path is shared via
`get_vector_store()` so the agent, watcher, ingester, and tools don't open
competing clients on the same storage path.

The public interface (get_vector_store / VectorStore.upsert / search /
delete_by_metadata / ensure_collections / collection_names) is unchanged from
the previous vector wrapper, so callers don't care which engine backs it.
We always pass our own embeddings (sentence-transformers, see embedder.py);
Chroma's built-in embedding function is never used.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from agent.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_COLLECTIONS = ("obsidian_vault", "agent_queries")

_singleton: "VectorStore | None" = None
_singleton_lock = threading.Lock()


def get_vector_store() -> "VectorStore":
    """Return the process-wide VectorStore, constructing on first call.

    Embedded Chroma keeps an exclusive lock on its storage path, so a singleton
    prevents the watcher / chat / ingester from opening competing clients."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = VectorStore()
    return _singleton


def reset_vector_store_for_tests() -> None:
    """Test-only: clear the singleton so each test gets a fresh instance."""
    global _singleton
    with _singleton_lock:
        _singleton = None


class VectorStore:
    def __init__(self, client: Any | None = None, *, ensure_collections: bool = True):
        self.client = client or self._create_client()
        self._collections: dict[str, Any] = {}
        if ensure_collections:
            self.ensure_collections()

    def _create_client(self):
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError as exc:
            raise RuntimeError(
                "chromadb is required for vector storage. "
                "Install requirements.txt before using the RAG layer."
            ) from exc

        settings = get_settings()
        path = settings.chroma_path
        if path is not None:
            path.mkdir(parents=True, exist_ok=True)
            logger.info("Using embedded Chroma at %s", path)
            return chromadb.PersistentClient(
                path=str(path),
                settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
            )
        logger.info("Using ephemeral (in-memory) Chroma")
        return chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False))

    def _collection(self, name: str):
        coll = self._collections.get(name)
        if coll is None:
            # cosine space for similarity (mirrors the prior cosine setup).
            coll = self.client.get_or_create_collection(
                name=name, metadata={"hnsw:space": "cosine"}
            )
            self._collections[name] = coll
        return coll

    def ensure_collections(self, collection_names: tuple[str, ...] = DEFAULT_COLLECTIONS) -> None:
        for name in collection_names:
            self._collection(name)

    def collection_names(self) -> list[str]:
        try:
            return [c.name for c in self.client.list_collections()]
        except Exception:
            return list(self._collections.keys())

    def upsert(
        self,
        collection: str,
        text: str,
        embedding: list[float],
        metadata: dict,
        point_id: str | None = None,
    ) -> str:
        point_id = point_id or str(uuid.uuid4())
        # Chroma metadata values must be scalars (str/int/float/bool); drop the rest.
        meta = {
            k: v
            for k, v in {"text": text, **(metadata or {})}.items()
            if isinstance(v, (str, int, float, bool))
        }
        self._collection(collection).upsert(
            ids=[point_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta or {"text": text}],
        )
        return point_id

    def delete_by_metadata(self, collection: str, key: str, value: Any) -> None:
        """Delete all points in a collection matching one metadata field."""
        self._collection(collection).delete(where={key: value})

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 10,
        score_threshold: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        result = self._collection(collection).query(
            query_embeddings=[embedding],
            n_results=max(1, top_k),
            where=self._build_where(filters),
            include=["documents", "metadatas", "distances"],
        )
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        out: list[dict] = []
        for i in range(len(docs)):
            distance = float(dists[i]) if i < len(dists) and dists[i] is not None else 1.0
            score = 1.0 - distance  # cosine space: distance = 1 - similarity
            if score < score_threshold:
                continue
            meta = dict(metas[i] or {}) if i < len(metas) else {}
            text = str(meta.pop("text", docs[i] or ""))
            out.append({"text": text, "score": score, "metadata": meta})
        return out

    def _build_where(self, filters: dict[str, Any] | None):
        if not filters:
            return None
        items = list(filters.items())
        if len(items) == 1:
            key, value = items[0]
            return {key: value}
        return {"$and": [{key: value} for key, value in items]}
