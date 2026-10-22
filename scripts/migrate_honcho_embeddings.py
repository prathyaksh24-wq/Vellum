"""Run offline inside the pinned Honcho image after a verified pg_dump backup.

The host must stop the Honcho API and deriver, then run this script in a
one-off honcho-configure container with the replacement embedding model.
One transaction replaces both vector columns; no canonical text or IDs change.
This script deliberately uses Honcho's unprefixed embedding contract, distinct
from Vellum RAG's asymmetric retrieval prefixes.
"""
import argparse
import asyncio
import json
import math
import os
import sys

# The maintenance script is mounted under /tmp, outside Honcho's source tree.
sys.path.insert(0, '/app')

EXPECTED_MODEL = 'embeddinggemma-2:270m-q8_0-text'
EXPECTED_DIGEST = 'c21dd30c1e38444d3b4faa091407b6fa97221447b4965d74931d43d7f09bbbfd'


async def migrate():
    import httpx
    from sqlalchemy import select, text, update
    from src.config import settings
    from src.db import SessionLocal, engine
    from src.embedding_client import embedding_client
    from src.models import Document, MessageEmbedding
    if settings.VECTOR_STORE.TYPE != 'pgvector':
        raise RuntimeError('This migration supports the local pgvector deployment only; external replicas need a separate migration.')
    if os.environ.get('EMBEDDING_MODEL_CONFIG__MODEL') != EXPECTED_MODEL:
        raise RuntimeError('Run the migration with the explicit Google embedding model configured.')
    if embedding_client.vector_dimensions != 768:
        raise RuntimeError('Honcho must retain 768 vector dimensions for this migration.')
    # Only the Docker host bridge is allowed; never send private memory to a
    # model registry or arbitrary URL supplied through environment configuration.
    expected_url = 'http://host.docker.internal:11434/v1'
    if os.environ.get('EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL') != expected_url:
        raise RuntimeError('Honcho migration requires the local Docker-to-Ollama bridge.')
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        response = await client.get(expected_url.removesuffix('/v1') + '/api/tags')
        response.raise_for_status()
        installed = next((m for m in response.json().get('models', []) if m.get('name') == EXPECTED_MODEL), {})
        if installed.get('digest') != EXPECTED_DIGEST:
            raise RuntimeError('The installed Google model fingerprint does not match this migration.')
    counts = {}
    try:
        async with SessionLocal() as db:
            async with db.begin():
                # Prevent a forgotten reader/writer from observing a mixed
                # generation while both tables are being rebuilt.
                await db.execute(text('LOCK TABLE documents, message_embeddings IN ACCESS EXCLUSIVE MODE'))
                for model in (Document, MessageEmbedding):
                    rows = (await db.execute(select(model.id, model.content).order_by(model.id))).all()
                    counts[model.__tablename__] = 0
                    for start in range(0, len(rows), 8):
                        batch = rows[start:start+8]
                        inputs = [row.content for row in batch]
                        # A conservative bound avoids silent truncation from
                        # the OpenAI transport's non-Google token estimator.
                        if any(len(value.encode('utf-8')) > 8000 for value in inputs):
                            raise RuntimeError('A Honcho vector source exceeds the conservative migration input bound; no vectors were committed.')
                        vectors = await embedding_client.simple_batch_embed(inputs)
                        if len(vectors) != len(batch):
                            raise RuntimeError('Incomplete embedding response; no vectors were committed.')
                        for row, vector in zip(batch, vectors, strict=True):
                            if len(vector) != 768 or not all(math.isfinite(value) for value in vector) or sum(v*v for v in vector) <= 0:
                                raise RuntimeError('Invalid Google vector; no vectors were committed.')
                            await db.execute(update(model).where(model.id == row.id).values(embedding=vector))
                            counts[model.__tablename__] += 1
                        print(json.dumps({'progress': counts}), flush=True)
        print(json.dumps({'status':'complete', 'model':EXPECTED_MODEL, 'digest':EXPECTED_DIGEST,
                          'dimensions':768, 'prompt_profile':'honcho-unprefixed', 'rows':counts}), flush=True)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        parser.exit(message='Back up PostgreSQL and stop Honcho readers/writers, then pass --apply.\n')
    asyncio.run(migrate())
