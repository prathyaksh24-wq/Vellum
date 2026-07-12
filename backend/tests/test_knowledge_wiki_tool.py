import json

from agent.tools import knowledge_wiki as tool_module


class FakeWiki:
    def status(self):
        return {"ready": True, "page_count": 3}

    def query(self, query, *, limit):
        return {"query": query, "limit": limit, "results": [{"title": "Memory"}]}

    def lint(self, *, stale_days):
        return {"health": "green", "stale_days": stale_days}

    def version_history(self, page_ref):
        return {"ref": page_ref, "current_version": 2, "versions": [{"version": 1}]}

    def read_page_version(self, page_ref, version):
        return {"ref": page_ref, "version": version, "content": "old"}


def test_knowledge_wiki_tool_exposes_status_query_and_lint(monkeypatch):
    fake = FakeWiki()
    monkeypatch.setattr(tool_module, "get_knowledge_wiki", lambda: fake)

    status = json.loads(tool_module.knowledge_wiki.func(action="status"))
    query = json.loads(tool_module.knowledge_wiki.func(action="query", query="memory", limit=4))
    lint = json.loads(tool_module.knowledge_wiki.func(action="lint", stale_days=30))

    assert status == {"action": "status", "ok": True, "ready": True, "page_count": 3}
    assert query["results"][0]["title"] == "Memory"
    assert query["limit"] == 4
    assert lint["health"] == "green"
    assert lint["stale_days"] == 30

    history = json.loads(tool_module.knowledge_wiki.func(action="history", page_ref="kw-0000000000000000"))
    old = json.loads(
        tool_module.knowledge_wiki.func(
            action="read_version", page_ref="kw-0000000000000000", version=1
        )
    )
    assert history["current_version"] == 2
    assert old["page"]["content"] == "old"


def test_agent_activity_uses_action_specific_wiki_labels():
    from agent.api import _activity_for

    assert _activity_for("knowledge_wiki", {"action": "query", "query": "memory"}) == (
        "Searching your knowledge wiki",
        "memory",
    )
    assert _activity_for("knowledge_wiki", {"action": "lint"})[0] == "Checking wiki health"
