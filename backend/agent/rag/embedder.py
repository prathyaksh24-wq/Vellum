"""Local BGE-M3 embedding wrapper."""

from __future__ import annotations

from functools import cached_property


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
VECTOR_SIZE = 1024


class Embedder:
    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL):
        self.model_name = model_name

    @cached_property
    def model(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for local embeddings. "
                "Install requirements.txt before using the RAG layer."
            ) from exc
        return SentenceTransformer(self.model_name)

    def embed(self, text: str) -> list[float]:
        vector = self.model.encode(text or "", normalize_embeddings=True)
        return _to_list(vector)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True, batch_size=32)
        return _to_list(vectors)


def _to_list(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, list):
        return [_to_list(item) for item in value]
    return value
