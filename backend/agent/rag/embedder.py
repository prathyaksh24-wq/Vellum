"""Shared local embedding owner for vault, memory projections and Books.

Google EmbeddingGemma 2 uses the existing loopback Ollama service. Explicit
SentenceTransformer instances remain available for legacy rollback. No cloud
fallback or automatic model download occurs on the request path.
"""

from __future__ import annotations

import threading
from functools import cached_property
from hashlib import sha256
import ipaddress
import json
import math
from urllib.parse import urlsplit


DEFAULT_EMBEDDING_MODEL = "embeddinggemma-2:270m-q8_0-text"
DEFAULT_MODEL_REVISION = "c21dd30c1e38444d3b4faa091407b6fa97221447b4965d74931d43d7f09bbbfd"
VECTOR_SIZE = 768
QUERY_PREFIX = "task: search result | query: "
DOCUMENT_PREFIX = "title: none | text: "

_singleton: "Embedder | None" = None
_singleton_lock = threading.Lock()


def get_embedder() -> "Embedder":
    """Return the process-wide Embedder, constructing on first call.

    Legacy native models and the local HTTP client are shared across callers.
    Embedding calls are serialized to bound device load."""
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
    def __init__(self, model_name: str | None = None):
        from agent.config import get_settings
        settings = get_settings()
        self.model_name = model_name or settings.embedding_model
        self.backend = settings.embedding_backend if model_name is None else (
            'ollama' if model_name.startswith('embeddinggemma-2:') else 'sentence_transformers')
        self.dimensions = settings.embedding_dimensions if model_name is None or self.backend == 'ollama' else 1024
        self.model_revision = settings.embedding_model_revision if model_name is None or self.backend == 'ollama' else 'default'
        self.batch_size = settings.embedding_batch_size
        self.timeout = settings.embedding_timeout_seconds
        self.base_url = settings.ollama_base_url.rstrip('/').removesuffix('/v1')
        self._lock = threading.RLock()

    @property
    def revision(self) -> str:
        return self.model_revision + (':retrieval-prefix-v1' if self.backend == 'ollama' else '')

    @property
    def fingerprint(self) -> str:
        value = [self.backend, self.model_name, self.revision, self.dimensions]
        return sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()

    @cached_property
    def model(self):
        if self.backend != 'sentence_transformers':
            raise RuntimeError('Ollama owns this embedding model; no in-process model is loaded.')
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for local embeddings. "
                "Install requirements.txt before using the RAG layer."
            ) from exc
        return SentenceTransformer(self.model_name)

    @cached_property
    def client(self):
        # Private sources must not reach an arbitrary configured HTTP endpoint.
        parsed = urlsplit(self.base_url)
        host = parsed.hostname or ''
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host.casefold() == 'localhost'
        if not local or parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password:
            raise ValueError('Local embeddings require a loopback Ollama URL.')
        import httpx
        return httpx.Client(base_url=self.base_url, timeout=self.timeout, trust_env=False, follow_redirects=False)

    def _check_model(self):
        # Recheck each operation: an Ollama tag can be replaced while Vellum is
        # running, and equal-width vectors must never hide a model change.
        response = self.client.get('/api/tags')
        response.raise_for_status()
        model = next((item for item in response.json().get('models', []) if item.get('name') == self.model_name), None)
        if model is None:
            raise RuntimeError(f'Local embedding model is missing. Run ollama pull {self.model_name} before reindexing.')
        if self.model_revision and model.get('digest') != self.model_revision:
            raise RuntimeError('Embedding model digest changed. Rebuild a fresh index before accepting this model revision.')

    def _encode(self, texts: list[str], *, query: bool) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            if self.backend == 'sentence_transformers':
                return _to_list(self.model.encode(texts, normalize_embeddings=True, batch_size=self.batch_size))
            self._check_model()
            prefix = QUERY_PREFIX if query else DOCUMENT_PREFIX
            vectors = []
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start:start + self.batch_size]
                response = self.client.post('/api/embed', json={
                    'model': self.model_name, 'input': [prefix + (text or '') for text in batch],
                    'dimensions': self.dimensions, 'truncate': False,
                    'options': {'num_ctx': 8192}, 'keep_alive': '2m',
                })
                response.raise_for_status()
                values = response.json().get('embeddings') or []
                if len(values) != len(batch):
                    raise ValueError('Embedding response count does not match input count.')
                for vector in values:
                    if len(vector) != self.dimensions or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
                        raise ValueError('Embedding response has invalid dimensions or non-finite values.')
                    norm = math.sqrt(sum(v*v for v in vector))
                    if norm <= 0:
                        raise ValueError('Embedding response contains a zero vector.')
                    vectors.append([float(v)/norm for v in vector])
            return vectors

    def embed(self, text: str) -> list[float]:
        """Legacy document API; query callers use embed_query instead."""
        if self.backend == 'sentence_transformers':
            with self._lock:
                return _to_list(self.model.encode(text or '', normalize_embeddings=True))
        return self._encode([text], query=False)[0]

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], query=True)[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, query=False)


def _to_list(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, list):
        return [_to_list(item) for item in value]
    return value
