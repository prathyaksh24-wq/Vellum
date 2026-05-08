"""Qdrant vector store wrapper."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from agent.config import get_settings
from agent.rag.embedder import VECTOR_SIZE

logger = logging.getLogger(__name__)

DEFAULT_COLLECTIONS = ("obsidian_vault", "agent_queries")


class VectorStore:
    def __init__(self, client: Any | None = None, *, ensure_collections: bool = True):
        self.client = client or self._create_client()
        if ensure_collections:
            self.ensure_collections()

    def _create_client(self):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "qdrant-client is required for vector storage. "
                "Install requirements.txt before using the RAG layer."
            ) from exc

        settings = get_settings()
        if settings.qdrant_local_path is not None:
            settings.qdrant_local_path.mkdir(parents=True, exist_ok=True)
            logger.info("Using embedded local Qdrant at %s", settings.qdrant_local_path)
            return QdrantClient(path=str(settings.qdrant_local_path))

        return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

    def ensure_collections(self, collection_names: tuple[str, ...] = DEFAULT_COLLECTIONS) -> None:
        from qdrant_client.models import Distance, VectorParams

        existing = {collection.name for collection in self.client.get_collections().collections}
        for name in collection_names:
            if name in existing:
                continue
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection: %s", name)

    def upsert(
        self,
        collection: str,
        text: str,
        embedding: list[float],
        metadata: dict,
        point_id: str | None = None,
    ) -> str:
        from qdrant_client.models import PointStruct

        point_id = point_id or str(uuid.uuid4())
        payload = {"text": text, **metadata}
        point = PointStruct(id=point_id, vector=embedding, payload=payload)
        self.client.upsert(collection_name=collection, points=[point])
        return point_id

    def delete_by_metadata(self, collection: str, key: str, value: Any) -> None:
        """Delete all points in a collection matching one payload field."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self.client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key=key, match=MatchValue(value=value))]
            ),
            wait=True,
        )

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 10,
        score_threshold: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        query_filter = self._build_filter(filters)
        results = self._query_points(
            collection=collection,
            embedding=embedding,
            top_k=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
        return [self._normalize_result(item) for item in results]

    def _query_points(self, *, collection: str, embedding: list[float], top_k: int, score_threshold: float, query_filter):
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=collection,
                query=embedding,
                query_filter=query_filter,
                limit=top_k,
                score_threshold=score_threshold,
            )
            return getattr(response, "points", response)

        return self.client.search(
            collection_name=collection,
            query_vector=embedding,
            query_filter=query_filter,
            limit=top_k,
            score_threshold=score_threshold,
        )

    def _build_filter(self, filters: dict[str, Any] | None):
        if not filters:
            return None

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        conditions = [
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in filters.items()
        ]
        return Filter(must=conditions)

    def _normalize_result(self, item) -> dict:
        payload = getattr(item, "payload", None) or {}
        score = float(getattr(item, "score", 0.0) or 0.0)
        metadata = dict(payload)
        text = str(metadata.pop("text", ""))
        return {"text": text, "score": score, "metadata": metadata}
