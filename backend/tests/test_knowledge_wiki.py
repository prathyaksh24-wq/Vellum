from pathlib import Path

import pytest

from agent.obsidian.wiki import KnowledgeWiki, KnowledgeWikiError


def _source(vault: Path, name: str = "article.md", text: str = "Raw source") -> Path:
    path = vault / "Library" / "Research" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_knowledge_wiki_initializes_three_layer_structure(tmp_path):
    wiki = KnowledgeWiki(tmp_path)

    result = wiki.ensure_structure()

    assert result["ready"] is True
    assert (tmp_path / "Knowledge" / "schema.md").exists()
    assert (tmp_path / "Knowledge" / "index.md").exists()
    assert (tmp_path / "Knowledge" / "log.md").exists()
    assert (tmp_path / "Knowledge" / "entities").is_dir()
    assert (tmp_path / "Knowledge" / ".history").is_dir()


def test_ingest_compiles_source_and_related_pages_without_mutating_library(tmp_path):
    source = _source(tmp_path, text="Immutable source text")
    wiki = KnowledgeWiki(tmp_path)

    result = wiki.ingest_source(
        source_path="Library/Research/article.md",
        title="Agent Memory",
        synthesis="A persistent synthesis compiled from the source.",
        approved_source=True,
        description="How agent memory compounds.",
        links=["Memory Orchestrator"],
        related_pages=[
            {
                "title": "Memory Orchestrator",
                "page_type": "concept",
                "content": "The orchestrator owns durable memory behavior.",
                "description": "Canonical memory coordination.",
                "tags": ["memory"],
            }
        ],
    )

    assert source.read_text(encoding="utf-8") == "Immutable source text"
    assert result["source_page"]["path"] == "Knowledge/sources/agent-memory.md"
    assert result["related_pages"][0]["path"] == "Knowledge/concepts/memory-orchestrator.md"
    source_page = (tmp_path / result["source_page"]["path"]).read_text(encoding="utf-8")
    assert 'sources: ["Library/Research/article.md"]' in source_page
    assert 'source_trust: "approved_path"' in source_page
    assert '"kind": "approved_path"' in source_page
    assert "[[Memory Orchestrator]]" in source_page
    index = (tmp_path / "Knowledge" / "index.md").read_text(encoding="utf-8")
    assert "[[Knowledge/sources/agent-memory|Agent Memory]]" in index
    assert "[[Knowledge/concepts/memory-orchestrator|Memory Orchestrator]]" in index
    log = (tmp_path / "Knowledge" / "log.md").read_text(encoding="utf-8")
    assert "ingest | Agent Memory" in log


def test_upsert_is_idempotent_and_saves_history_before_revision(tmp_path):
    wiki = KnowledgeWiki(tmp_path)
    first = wiki.upsert_page(title="Context", page_type="concept", content="Version one")
    repeated = wiki.upsert_page(title="Context", page_type="concept", content="Version one")
    revised = wiki.upsert_page(title="Context", page_type="concept", content="Version two")

    assert first["created"] is True
    assert repeated["updated"] is False
    assert revised["created"] is False
    history = list((tmp_path / "Knowledge" / ".history" / "concepts" / "context").glob("*.md"))
    assert len(history) == 1
    assert "Version one" in history[0].read_text(encoding="utf-8")


def test_stable_identity_renames_without_duplicate_and_exposes_history(tmp_path):
    wiki = KnowledgeWiki(tmp_path)
    first = wiki.upsert_page(
        title="Canonical Context",
        page_type="concept",
        content="Version one",
        page_id="concept:context",
        sensitivity="public",
    )
    revised = wiki.upsert_page(
        title="Canonical Context Revised",
        page_type="concept",
        content="Version two",
        page_id="concept:context",
        sensitivity="public",
    )

    assert revised["created"] is False
    assert revised["ref"] == first["ref"]
    assert not (tmp_path / first["path"]).exists()
    assert (tmp_path / revised["path"]).exists()
    history = wiki.version_history(first["ref"])
    assert history["current_version"] == 2
    assert [item["version"] for item in history["versions"]] == [1]
    assert "Version one" in wiki.read_page_version(first["ref"], 1)["content"]


def test_ingest_requires_explicit_approval_for_any_source_path(tmp_path):
    outside = tmp_path / "Agent" / "private.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("private", encoding="utf-8")
    wiki = KnowledgeWiki(tmp_path)

    with pytest.raises(KnowledgeWikiError, match="approved_source"):
        wiki.ingest_source(source_path="Agent/private.md", title="Private", synthesis="No")


def test_ingest_accepts_supplied_content_without_reading_library(tmp_path):
    source = _source(tmp_path, text="This inaccurate Library text must not be used.")
    wiki = KnowledgeWiki(tmp_path)

    result = wiki.ingest_source(
        title="Supplied Research",
        synthesis="The caller supplied this maintained synthesis.",
        source_trust="user_supplied",
    )

    assert result["source_trust"] == "user_supplied"
    page = (tmp_path / result["source_page"]["path"]).read_text(encoding="utf-8")
    assert "The caller supplied this maintained synthesis." in page
    assert "inaccurate Library text" not in page
    assert "supplied-content:" in page
    assert source.read_text(encoding="utf-8") == "This inaccurate Library text must not be used."

    revised = wiki.ingest_source(
        title="Supplied Research",
        synthesis="A revised maintained synthesis supplied by the caller.",
        source_trust="user_supplied",
    )
    assert revised["source_page"]["created"] is False
    assert revised["source_page"]["page"]["version"] == 2


def test_query_consults_index_and_returns_relevant_pages(tmp_path):
    wiki = KnowledgeWiki(tmp_path)
    wiki.upsert_page(
        title="Compounding Knowledge",
        page_type="concept",
        content="A maintained wiki integrates new sources into durable synthesis.",
        description="Persistent synthesis instead of repeated retrieval.",
        sensitivity="public",
    )

    result = wiki.query("How does persistent knowledge synthesis work?")

    assert result["index_consulted"] == "Knowledge/index.md"
    assert result["results"][0]["title"] == "Compounding Knowledge"
    assert result["results"][0]["sensitivity"] == "public"
    assert result["results"][0]["ref"].startswith("kw-")
    assert "path" not in result["results"][0]
    page = wiki.read_page(result["results"][0]["ref"])
    assert "maintained wiki integrates new sources" in page["content"]


def test_query_withholds_red_content(tmp_path):
    wiki = KnowledgeWiki(tmp_path)
    wiki.upsert_page(
        title="Credential Handling",
        page_type="concept",
        content="A password=super-secret must never enter a model prompt.",
    )

    result = wiki.query("credential password")
    page = wiki.read_page(result["results"][0]["ref"])

    assert "[SECRET_1]" in page["content"]
    assert "super-secret" not in page["content"]


def test_lint_reports_broken_links_and_never_deletes_pages(tmp_path):
    wiki = KnowledgeWiki(tmp_path)
    result = wiki.upsert_page(
        title="Orphan Concept",
        page_type="concept",
        content="This page points to [[Missing Concept]].",
    )
    page = tmp_path / result["path"]

    report = wiki.lint()

    assert report["health"] == "yellow"
    assert report["broken_links"] == [{"path": result["path"], "link": "Missing Concept"}]
    assert result["path"] in report["orphan_pages"]
    assert page.exists()
    assert (tmp_path / report["report_path"]).exists()


def test_overview_updates_are_versioned_and_idempotent(tmp_path):
    wiki = KnowledgeWiki(tmp_path)
    first = wiki.update_overview(content="Memory and knowledge are separate layers.", links=["Memory"])
    repeated = wiki.update_overview(content="Memory and knowledge are separate layers.", links=["Memory"])
    revised = wiki.update_overview(content="The knowledge graph now includes [[Memory]].", links=["Memory"])

    assert first["version"] == 1
    assert repeated["updated"] is False
    assert revised["version"] == 2
    history = list((tmp_path / "Knowledge" / ".history" / "overview").glob("*.md"))
    assert len(history) == 1
