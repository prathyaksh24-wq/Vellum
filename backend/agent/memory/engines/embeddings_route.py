"""OpenAI-compatible ``/v1/embeddings`` on Vellum's own server (loopback only).

Honcho and Hindsight both speak the OpenAI embeddings API. Pointing them here
means every engine uses Vellum's single embedding model (embeddinggemma via
Ollama, or the bundled sentence-transformers backend), so cloud-only users
need no extra embedding provider and nothing personal leaves the machine
for embedding.

The served model must not change under an engine's existing index: the
response carries the embedder's fingerprint so the supervisor can detect a
change and re-index instead of mixing vectors.
"""
from __future__ import annotations

import asyncio
import base64
import struct
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
MAX_INPUTS = 256

router = APIRouter()


class EmbeddingsRequest(BaseModel):
    input: str | list[str]
    model: str = ""
    encoding_format: str = Field(default="float")
    dimensions: int | None = None


def _encode_base64(vector: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")


def build_response(vectors: list[list[float]], *, model: str, encoding_format: str) -> dict[str, Any]:
    data = [
        {
            "object": "embedding",
            "index": index,
            "embedding": _encode_base64(vector) if encoding_format == "base64" else vector,
        }
        for index, vector in enumerate(vectors)
    ]
    return {"object": "list", "data": data, "model": model,
            "usage": {"prompt_tokens": 0, "total_tokens": 0}}


@router.post("/v1/embeddings")
async def create_embeddings(body: EmbeddingsRequest, request: Request, response: Response) -> dict[str, Any]:
    host = request.client.host if request.client else ""
    if host not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="Embeddings are only served to this computer.")
    texts = [body.input] if isinstance(body.input, str) else list(body.input)
    if not texts or len(texts) > MAX_INPUTS or not all(isinstance(text, str) for text in texts):
        raise HTTPException(status_code=400, detail=f"input must be 1 to {MAX_INPUTS} strings")
    if body.encoding_format not in {"float", "base64"}:
        raise HTTPException(status_code=400, detail="encoding_format must be float or base64")

    from agent.rag.embedder import get_embedder

    embedder = get_embedder()
    if body.dimensions is not None and body.dimensions != embedder.dimensions:
        raise HTTPException(status_code=400,
                            detail=f"this model returns {embedder.dimensions} dimensions, not {body.dimensions}")
    try:
        vectors = await asyncio.to_thread(embedder.embed_batch, texts)
    except Exception as exc:  # noqa: BLE001 - surface as a provider error to the engine
        raise HTTPException(status_code=503, detail=f"embedding model unavailable: {exc}") from exc
    response.headers["X-Vellum-Embedding-Fingerprint"] = str(embedder.fingerprint)
    return build_response(vectors, model=embedder.model_name, encoding_format=body.encoding_format)
