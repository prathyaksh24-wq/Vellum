from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.obsidian import wiki_api
from agent.obsidian.wiki import KnowledgeWiki


def test_knowledge_api_lifecycle_is_source_aware_and_knowledge_only(tmp_path, monkeypatch):
    library_source = tmp_path / "Library" / "inaccurate.md"
    library_source.parent.mkdir(parents=True)
    library_source.write_text("inaccurate raw source", encoding="utf-8")
    outside_sentinel = tmp_path / "Agent" / "private.md"
    outside_sentinel.parent.mkdir(parents=True)
    outside_sentinel.write_text("private note", encoding="utf-8")

    wiki = KnowledgeWiki(tmp_path)
    monkeypatch.setattr(wiki_api, "get_knowledge_wiki", lambda: wiki)
    app = FastAPI()
    app.include_router(wiki_api.router, prefix="/api")

    with TestClient(app) as client:
        status = client.get("/api/knowledge/status")
        assert status.status_code == 200
        assert status.json()["source_policy"]["library_auto_ingestion"] is False

        rejected = client.post(
            "/api/knowledge/ingest",
            json={
                "source_path": "Library/inaccurate.md",
                "title": "Unsafe Source",
                "content": "Caller content",
            },
        )
        assert rejected.status_code == 422
        assert "approved_source" in rejected.json()["detail"]

        supplied = client.post(
            "/api/knowledge/ingest",
            json={
                "title": "Supplied Source",
                "content": "Maintained synthesis supplied by the caller.",
                "source_trust": "user_supplied",
            },
        )
        assert supplied.status_code == 200
        assert supplied.json()["source_trust"] == "user_supplied"

        created = client.post(
            "/api/knowledge/pages",
            json={
                "title": "Lifecycle Page",
                "page_type": "concept",
                "content": "The public lifecycle page.",
                "sensitivity": "public",
                "id": "concept:lifecycle-page",
            },
        )
        assert created.status_code == 200
        ref = created.json()["ref"]

        query = client.get("/api/knowledge/query", params={"q": "lifecycle page"})
        assert query.status_code == 200
        assert query.json()["results"][0]["ref"] == ref
        assert client.get(f"/api/knowledge/pages/{ref}").json()["content"].startswith("# Lifecycle Page")

        revised = client.post(
            "/api/knowledge/pages",
            json={
                "title": "Lifecycle Page Revised",
                "page_type": "concept",
                "content": "The revised public lifecycle page.",
                "sensitivity": "public",
                "id": "concept:lifecycle-page",
            },
        )
        assert revised.status_code == 200
        assert revised.json()["ref"] == ref
        assert revised.json()["page"]["version"] == 2

        history = client.get(f"/api/knowledge/pages/{ref}/history")
        assert history.status_code == 200
        assert [item["version"] for item in history.json()["versions"]] == [1]
        assert client.get(f"/api/knowledge/pages/{ref}/history/1").json()["version"] == 1
        assert client.post("/api/knowledge/index/rebuild").status_code == 200
        assert client.post("/api/knowledge/overview", json={"content": "The wiki overview."}).status_code == 200
        assert client.post("/api/knowledge/lint", json={"stale_days": 120}).status_code == 200

    assert library_source.read_text(encoding="utf-8") == "inaccurate raw source"
    assert outside_sentinel.read_text(encoding="utf-8") == "private note"
    assert all(
        path.relative_to(tmp_path).as_posix().startswith("Knowledge/")
        for path in tmp_path.joinpath("Knowledge").rglob("*")
        if path.is_file()
    )
