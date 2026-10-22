"""Offline embedding generation migration through existing Vellum owners.

Run with --apply after stopping the API. Source files, old Chroma, and old model
weights remain available. Only already-indexed vault notes are rebuilt; this
does not enable vector search or expand the set of indexed private sources.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def migrate(source: Path, target: Path) -> dict:
    try:
        with socket.create_connection(('127.0.0.1', 8000), timeout=1):
            raise RuntimeError('Stop the Vellum API before migrating embeddings.')
    except OSError:
        pass
    if not source.is_dir() or source.resolve() == target.resolve():
        raise ValueError('Use the existing source index and a separate target directory.')
    if source.resolve().is_relative_to(target.resolve()) or target.resolve().is_relative_to(source.resolve()):
        raise ValueError('Source and target index directories must not overlap.')
    if target.exists() and any(target.iterdir()):
        raise ValueError('Target index is not empty. Choose a fresh generation instead of overwriting it.')
    os.environ['CHROMA_PATH'] = str(target)
    os.environ['EMBEDDING_BACKEND'] = 'ollama'
    os.environ['EMBEDDING_MODEL'] = 'embeddinggemma-2:270m-q8_0-text'
    os.environ['EMBEDDING_MODEL_REVISION'] = 'c21dd30c1e38444d3b4faa091407b6fa97221447b4965d74931d43d7f09bbbfd'
    os.environ['EMBEDDING_DIMENSIONS'] = '768'
    from agent.config import get_settings
    from agent.rag.embedder import get_embedder
    from agent.rag.store import get_vector_store
    from agent.obsidian.ingester import VaultIngester
    from agent.knowledge.runtime import get_knowledge_core
    from agent.knowledge.models import BookMaterializationRequest
    settings = get_settings()
    embedder = get_embedder()
    # Check the installed digest before creating or publishing any projection.
    embedder._check_model()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT / 'data/embeddings' / ('migration-' + stamp)
    backup.mkdir(parents=True)
    shutil.copytree(source, backup / 'source-index')
    env_path = ROOT / '.env'
    if env_path.exists():
        shutil.copy2(env_path, backup / 'settings.env')
    with sqlite3.connect(settings.knowledge_core_db_path) as conn, sqlite3.connect(backup / 'knowledge.sqlite3') as snapshot:
        conn.backup(snapshot)
        conn.row_factory = sqlite3.Row
        active = [dict(row) for row in conn.execute('SELECT * FROM active_book_materializations')]
        books = [dict(row) for row in conn.execute(
            'SELECT DISTINCT m.user_id, m.document_id, r.id AS run_id, i.id AS import_id '
            'FROM book_materializations m '
            'JOIN active_book_materializations a ON a.materialization_id=m.id '
            'JOIN book_documents d ON d.id=m.document_id AND d.user_id=m.user_id '
            'JOIN book_ingestion_runs r ON r.id=d.run_id AND r.user_id=d.user_id '
            'JOIN user_book_imports i ON i.asset_id=r.asset_id AND i.user_id=d.user_id')]
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    old = chromadb.PersistentClient(path=str(backup / 'source-index'), settings=ChromaSettings(anonymized_telemetry=False))
    store = get_vector_store()
    report = {'model': embedder.model_name, 'revision': embedder.revision, 'dimensions': embedder.dimensions,
              'source_index': str(source), 'target_index': str(target), 'backup': str(backup),
              'vault_chunks': 0, 'query_vectors': 0, 'book_materializations': 0,
              'vector_search_enabled': settings.enable_vector_search, 'status': 'running'}
    try:
        names = {item.name for item in old.list_collections()}
        if names - {'obsidian_vault', 'agent_queries', 'books'}:
            raise ValueError('Unknown source collection: extend the migration before changing its embedding model.')
        if 'obsidian_vault' in names:
            rows = old.get_collection('obsidian_vault').get(include=['metadatas'])
            paths = {str(meta.get('path') or '') for meta in rows['metadatas'] if meta}
            if paths:
                ingester = VaultIngester(store=store, embedder=embedder)
                for relative in sorted(paths):
                    path = (settings.obsidian_vault_path / relative).resolve()
                    if path.is_file() and path.is_relative_to(settings.obsidian_vault_path.resolve()):
                        report['vault_chunks'] += ingester.ingest_file(path)
        if 'agent_queries' in names:
            rows = old.get_collection('agent_queries').get(include=['documents', 'metadatas'])
            for identifier, text, metadata in zip(rows['ids'], rows['documents'], rows['metadatas'], strict=True):
                if text:
                    store.upsert('agent_queries', text, embedder.embed_query(text), metadata or {}, point_id=identifier)
                    report['query_vectors'] += 1
        core = get_knowledge_core()
        for row in books:
            core.book_materializations.materialize(BookMaterializationRequest(**row))
            report['book_materializations'] += 1
            print(json.dumps({'book_materializations': report['book_materializations']}), flush=True)
        report['collections'] = {name: store._collection(name).count() for name in store.collection_names()}
        # Publish the settings together only after every existing source rebuilt.
        from dotenv import set_key
        staged_env = backup / 'settings.next.env'
        staged_env.write_bytes(env_path.read_bytes() if env_path.exists() else b'')
        for key in ('CHROMA_PATH', 'EMBEDDING_BACKEND', 'EMBEDDING_MODEL', 'EMBEDDING_MODEL_REVISION', 'EMBEDDING_DIMENSIONS'):
            set_key(str(staged_env), key, os.environ[key])
        # Atomic replacement must remain on the same volume as the .env owner.
        temporary_env = env_path.with_name('.env.embedding-migration.tmp')
        shutil.copy2(staged_env, temporary_env)
        os.replace(temporary_env, env_path)
        report['status'] = 'complete'
    except Exception:
        # Restore only the original active-book pointers, never the entire
        # canonical DB. New artifacts remain inspectable but inactive.
        with sqlite3.connect(settings.knowledge_core_db_path) as conn:
            for row in active:
                conn.execute('UPDATE active_book_materializations SET materialization_id=?, activated_at=? WHERE user_id=? AND edition_id=?',
                    (row['materialization_id'], row['activated_at'], row['user_id'], row['edition_id']))
        report['status'] = 'failed_settings_unchanged'
        raise
    finally:
        (backup / 'receipt.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-path', type=Path, default=ROOT/'data/embeddings/chroma')
    parser.add_argument('--target-path', type=Path, default=ROOT/'data/embeddings/chroma-embeddinggemma2-v1')
    parser.add_argument('--apply', action='store_true', help='Rebuild existing projections and activate the new model offline.')
    args = parser.parse_args()
    if not args.apply:
        parser.exit(message='Use --apply after stopping the API. Old source/index/model data will be retained.\n')
    print(json.dumps(migrate(args.source_path.resolve(), args.target_path.resolve()), indent=2))
