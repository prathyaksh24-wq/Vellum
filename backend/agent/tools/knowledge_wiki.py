"""LangChain tool for Vellum's agent-maintained Obsidian knowledge wiki."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from agent.obsidian.wiki import KnowledgeWikiError
from agent.obsidian.wiki_runtime import get_knowledge_wiki


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def knowledge_wiki(
    action: str,
    query: str = "",
    page_ref: str = "",
    source_path: str = "",
    title: str = "",
    page_type: str = "concept",
    content: str = "",
    description: str = "",
    sources: list[str] | None = None,
    links: list[str] | None = None,
    tags: list[str] | None = None,
    status: str = "draft",
    sensitivity: str = "private",
    related_pages: list[dict[str, Any]] | None = None,
    limit: int = 8,
    stale_days: int = 120,
) -> str:
    """Operate Vellum's compiled Obsidian knowledge wiki.

    Actions:
    - status: inspect wiki health and page counts.
    - query: read index.md first and return a small relevant page set.
    - read_page: read one page selected by the opaque ref returned from query.
    - ingest_source: compile one immutable Library/ source plus related pages.
    - upsert_page: create or revise one complete entity/concept/topic/project/analysis/source page.
    - update_overview: revise the high-level synthesis after meaningful wiki changes.
    - rebuild_index: regenerate the content-oriented index.
    - lint: report schema, source, link, duplicate, orphan, stale, and overview issues.

    Never use this tool to edit Library/. Before ingest_source, read the raw
    source and existing relevant wiki pages, then provide complete revised
    synthesis in content/related_pages. Lint never deletes or rewrites pages.
    """

    wiki = get_knowledge_wiki()
    normalized = action.strip().casefold().replace("-", "_")
    try:
        if normalized == "status":
            return _json({"action": normalized, "ok": True, **wiki.status()})
        if normalized == "query":
            return _json({"action": normalized, "ok": True, **wiki.query(query, limit=limit)})
        if normalized == "read_page":
            return _json({"action": normalized, "ok": True, "page": wiki.read_page(page_ref)})
        if normalized == "upsert_page":
            return _json(
                {
                    "action": normalized,
                    "ok": True,
                    **wiki.upsert_page(
                        title=title,
                        page_type=page_type,
                        content=content,
                        description=description,
                        sources=sources,
                        links=links,
                        tags=tags,
                        status=status,
                        sensitivity=sensitivity,
                    ),
                }
            )
        if normalized == "ingest_source":
            return _json(
                {
                    "action": normalized,
                    "ok": True,
                    **wiki.ingest_source(
                        source_path=source_path,
                        title=title,
                        synthesis=content,
                        description=description,
                        links=links,
                        tags=tags,
                        related_pages=related_pages,
                    ),
                }
            )
        if normalized == "rebuild_index":
            return _json({"action": normalized, "ok": True, **wiki.rebuild_index()})
        if normalized == "update_overview":
            return _json(
                {
                    "action": normalized,
                    "ok": True,
                    **wiki.update_overview(content=content, links=links, sources=sources),
                }
            )
        if normalized == "lint":
            return _json({"action": normalized, "ok": True, **wiki.lint(stale_days=stale_days)})
    except KnowledgeWikiError as exc:
        return _json({"action": normalized, "ok": False, "error": str(exc)})

    return _json(
        {
            "action": normalized,
            "ok": False,
            "error": "Unsupported action. Use status, query, read_page, ingest_source, upsert_page, update_overview, rebuild_index, or lint.",
        }
    )
