"""Vault search tool with local RAG, privacy classification, and folder policy."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import re

from langchain_core.tools import tool

from agent.config import get_settings
from agent.obsidian.folder_policy import can_send_to_llm, needs_scrubbing
from agent.obsidian.vault import ObsidianVault
from agent.privacy.classifier import DataClass, classify
from agent.privacy.metadata_strip import strip_obsidian_metadata
from agent.privacy.scrubber import PrivacyScrubber
from agent.rag.embedder import get_embedder
from agent.rag.store import get_vector_store

logger = logging.getLogger(__name__)


# Module-level capture of citations from the most recent search_my_notes call.
# Process-local; available to API clients that render source footnotes.
_LAST_CITATIONS: list[dict] = []


def get_last_citations() -> list[dict]:
    """Return citations from the most recent search_my_notes call."""
    return list(_LAST_CITATIONS)


def _settings():
    return get_settings()


_RERANKER_SINGLETON = None
_RERANKER_LOCK = __import__("threading").Lock()


def _get_reranker():
    """Return a process-wide CrossEncoder, lazy-loaded on first call.

    Same rationale as get_embedder(): constructing a fresh CrossEncoder per
    query reloaded the cross-encoder weights every chat turn and contributed
    to native-allocation failures (`memory allocation of N bytes failed`)."""
    global _RERANKER_SINGLETON
    if _RERANKER_SINGLETON is not None:
        return _RERANKER_SINGLETON
    with _RERANKER_LOCK:
        if _RERANKER_SINGLETON is None:
            from sentence_transformers import CrossEncoder
            _RERANKER_SINGLETON = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    return _RERANKER_SINGLETON


def _rerank(clean_query: str, results: list[dict]) -> list[tuple[float, dict]]:
    if not getattr(_settings(), "enable_cross_encoder_rerank", False):
        return _lexical_rerank(clean_query, results)

    try:
        reranker = _get_reranker()
        scores = reranker.predict([(clean_query, item["text"]) for item in results])
        return sorted(zip(scores, results), key=lambda item: item[0], reverse=True)
    except Exception as exc:
        logger.warning("[TOOL:vault] Cross-encoder unavailable; using lexical rerank: %s", exc)
        return _lexical_rerank(clean_query, results)


def _lexical_rerank(clean_query: str, results: list[dict]) -> list[tuple[float, dict]]:
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
    _LAST_CITATIONS.clear()
    _store_query(query)

    results: list[dict]
    if getattr(settings, "enable_vector_search", False):
        try:
            results = get_vector_store().search(
                collection="obsidian_vault",
                embedding=get_embedder().embed(clean_query),
                top_k=12,
                score_threshold=0.40,
            )
        except Exception as exc:
            logger.warning("[TOOL:vault] Vector search unavailable; using vault fallback: %s", exc)
            vault = ObsidianVault(settings.obsidian_vault_path)
            results = vault.search_notes(clean_query, limit=12)
    else:
        logger.info("[TOOL:vault] Vector search disabled; using vault fallback.")
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
        path = metadata.get("path", "")
        if not can_send_to_llm(folder):
            logger.info("[TOOL:vault] Skipping private folder: %s", folder)
            continue

        text = strip_obsidian_metadata(chunk.get("text", ""))
        if needs_scrubbing(folder):
            text, _ = scrubber.scrub(text)

        allowed_chunks.append({"text": text, "folder": folder, "score": score, "path": path})
        if len(allowed_chunks) >= settings.max_context_chunks:
            break

    if not allowed_chunks:
        _LAST_CITATIONS.clear()
        return "Found relevant notes, but none are allowed to be surfaced directly by the folder policy."

    # Capture citations for API clients to render as footnotes.
    _LAST_CITATIONS.clear()
    _LAST_CITATIONS.extend(
        {"n": index, "folder": chunk["folder"], "path": chunk["path"], "score": float(chunk["score"])}
        for index, chunk in enumerate(allowed_chunks, 1)
    )

    context = "\n\n---\n\n".join(
        f"[Note {index} - {chunk['folder']}]\n{chunk['text']}"
        for index, chunk in enumerate(allowed_chunks, 1)
    )
    max_chars = settings.max_context_tokens * 4
    if len(context) > max_chars:
        context = context[:max_chars] + "\n[TRUNCATED]"

    return context


def _store_query(query: str) -> None:
    """Store private search telemetry without creating user-facing note clutter."""
    settings = _settings()
    if getattr(settings, "enable_query_vector_storage", False):
        try:
            embedder = get_embedder()
            store = get_vector_store()
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

    try:
        now = datetime.now(timezone.utc)
        log_dir = Path(settings.obsidian_vault_path) / settings.agent_notes_folder / "System" / "Search Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"Search Activity - {now:%Y-%m}.md"
        if log_path.exists():
            existing = log_path.read_text(encoding="utf-8", errors="ignore")
        else:
            existing = (
                "---\n"
                "type: system-search-log\n"
                f"month: {now:%Y-%m}\n"
                "visibility: system\n"
                "retention: archive\n"
                "---\n\n"
                f"# Search Activity - {now:%B %Y}\n\n"
                "> Private tool telemetry. Conversation history and durable memory live elsewhere.\n"
            )
        marker = f"<!-- query:{_query_fingerprint(query)} -->"
        if marker in existing:
            return
        entry = f"\n## {now:%d %B %Y at %H:%M UTC}\n\n{marker}\n\n{query.strip()}\n"
        log_path.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8", newline="\n")
    except Exception as exc:
        logger.warning("[TOOL:vault] Query note logging skipped: %s", exc)


def _query_fingerprint(query: str) -> str:
    import hashlib

    return hashlib.sha256(query.strip().casefold().encode("utf-8")).hexdigest()[:16]

