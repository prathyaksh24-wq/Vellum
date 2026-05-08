"""Vault search tool with local RAG, privacy classification, and folder policy."""

from __future__ import annotations

from datetime import datetime
import logging
import re

from langchain_core.tools import tool

from agent.config import get_settings
from agent.memory.long_term import LongTermMemory
from agent.obsidian.folder_policy import can_send_to_llm, needs_scrubbing
from agent.obsidian.vault import ObsidianVault
from agent.privacy.classifier import DataClass, classify
from agent.privacy.metadata_strip import strip_obsidian_metadata
from agent.privacy.scrubber import PrivacyScrubber
from agent.rag.embedder import Embedder
from agent.rag.store import VectorStore

logger = logging.getLogger(__name__)


def _settings():
    return get_settings()


def _rerank(clean_query: str, results: list[dict]) -> list[tuple[float, dict]]:
    try:
        from sentence_transformers import CrossEncoder

        reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        scores = reranker.predict([(clean_query, item["text"]) for item in results])
        return sorted(zip(scores, results), key=lambda item: item[0], reverse=True)
    except Exception as exc:
        logger.warning("[TOOL:vault] Cross-encoder unavailable; using lexical rerank: %s", exc)
        terms = {term.casefold() for term in re.findall(r"[A-Za-z0-9]+", clean_query) if len(term) > 2}
        scored = []
        for item in results:
            text = item.get("text", "").casefold()
            score = sum(1 for term in terms if term in text) / max(len(terms), 1)
            scored.append((max(float(item.get("score", 0.0)), score), item))
        return sorted(scored, key=lambda item: item[0], reverse=True)


@tool
def search_my_notes(query: str) -> str:
    """Search the user's private Obsidian knowledge vault. Always use this before web search."""

    settings = _settings()
    scrubber = PrivacyScrubber()
    data_class, reason = classify(query)
    if data_class == DataClass.RED:
        logger.warning("[TOOL:vault] Blocked RED query: %s", reason)
        return f"Query blocked for privacy reasons: {reason}. Please rephrase without sensitive personal identifiers."

    clean_query = scrubber.scrub(query)[0] if data_class == DataClass.YELLOW else query
    _store_query(query)

    try:
        results = VectorStore().search(
            collection="obsidian_vault",
            embedding=Embedder().embed(clean_query),
            top_k=12,
            score_threshold=0.40,
        )
    except Exception as exc:
        logger.warning("[TOOL:vault] Vector search unavailable; using vault fallback: %s", exc)
        vault = ObsidianVault(settings.obsidian_vault_path)
        results = vault.search_notes(clean_query, limit=12)

    if not results:
        return "No relevant notes found in vault for this query."

    ranked = _rerank(clean_query, results)
    top_score = float(ranked[0][0]) if ranked else 0.0
    if top_score < settings.min_retrieval_score:
        return (
            f"No sufficiently relevant notes found (best match score: {top_score:.2f}, "
            f"threshold: {settings.min_retrieval_score}). I don't have enough information about this in your vault."
        )

    allowed_chunks = []
    for score, chunk in ranked[: settings.max_context_chunks * 2]:
        metadata = chunk.get("metadata", {})
        folder = metadata.get("folder", "")
        if not can_send_to_llm(folder):
            logger.info("[TOOL:vault] Skipping private folder: %s", folder)
            continue

        text = strip_obsidian_metadata(chunk.get("text", ""))
        if needs_scrubbing(folder):
            text, _ = scrubber.scrub(text)

        allowed_chunks.append({"text": text, "folder": folder, "score": score})
        if len(allowed_chunks) >= settings.max_context_chunks:
            break

    if not allowed_chunks:
        return "Found relevant notes, but none are allowed to be surfaced directly by the folder policy."

    context = "\n\n---\n\n".join(
        f"[Note {index} - {chunk['folder']}]\n{chunk['text']}"
        for index, chunk in enumerate(allowed_chunks, 1)
    )
    max_chars = settings.max_context_tokens * 4
    if len(context) > max_chars:
        context = context[:max_chars] + "\n[TRUNCATED]"

    LongTermMemory().log_query(query, "vault_search", top_score)
    return context


def _store_query(query: str) -> None:
    """Store a query locally after deduplication."""
    settings = _settings()
    try:
        embedder = Embedder()
        store = VectorStore()
        embedding = embedder.embed(query)
        existing = store.search("agent_queries", embedding, top_k=1, score_threshold=0.92)
        if existing:
            return
        store.upsert(
            collection="agent_queries",
            text=query,
            embedding=embedding,
            metadata={"timestamp": datetime.now().isoformat(), "type": "query"},
        )
    except Exception as exc:
        logger.warning("[TOOL:vault] Query vector storage skipped: %s", exc)

    ObsidianVault(settings.obsidian_vault_path).create_note(
        folder=f"{settings.agent_notes_folder}/Queries",
        title=f"Query {datetime.now().strftime('%Y%m%d_%H%M%S')}",
        content=f"**Query logged at {datetime.now().strftime('%Y-%m-%d %H:%M')}**\n\n{query}",
    )

