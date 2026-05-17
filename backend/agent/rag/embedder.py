"""Local BGE-M3 embedding wrapper.

Use `get_embedder()` to share one Embedder across the agent, watcher,
ingester, and tools. Each fresh Embedder() reloads the bge-m3 native model
into memory; doing that per chat turn was the cause of the silent SIGSEGV
crashes on Windows (native tokenizer/torch state accumulation)."""

from __future__ import annotations

import threading
from functools import cached_property


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
VECTOR_SIZE = 1024

_singleton: "Embedder | None" = None
_singleton_lock = threading.Lock()


def get_embedder() -> "Embedder":
    """Return the process-wide Embedder, constructing on first call.

    Loading bge-m3 weights is expensive (and on Windows + Python 3.14, doing
    it repeatedly seems to destabilize native libs into SIGSEGV). Sharing one
    instance avoids all of that."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = Embedder()
    return _singleton


def reset_embedder_for_tests() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


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
