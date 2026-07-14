import asyncio
from pathlib import Path
from types import SimpleNamespace

from agent.obsidian import wiki_api


class FakeWiki:
    def query(self, query: str, limit: int = 8):
        return {
            "results": [
                {
                    "ref": "wiki-memory",
                    "title": "Memory architecture",
                    "type": "concept",
                    "status": "verified",
                    "description": "Compiled memory design.",
                    "score": 0.8,
                }
            ]
        }


def test_federated_search_returns_vault_and_wiki_refs(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    note = vault / "Projects" / "Vellum memory.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Vellum memory\n\nThe memory orchestrator owns retrieval.", encoding="utf-8")
    monkeypatch.setattr(wiki_api, "get_settings", lambda: SimpleNamespace(obsidian_vault_path=vault))
    monkeypatch.setattr(wiki_api, "get_knowledge_wiki", lambda: FakeWiki())

    result = asyncio.run(wiki_api.federated_knowledge_search(q="memory", scope="all", limit=10))

    assert {item["kind"] for item in result["results"]} == {"vault_note", "wiki_page"}
    assert any(item["ref"] == "Projects/Vellum memory.md" for item in result["results"])


def test_read_vault_note_returns_private_note_content(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "USER.md").write_text("# User profile\n\nPrivate context.", encoding="utf-8")
    monkeypatch.setattr(wiki_api, "get_settings", lambda: SimpleNamespace(obsidian_vault_path=vault))

    result = asyncio.run(wiki_api.read_vault_note(ref="USER.md"))

    assert result["kind"] == "vault_note"
    assert result["title"] == "User profile"
    assert "Private context" in result["content"]
