from types import SimpleNamespace

from agent.tools import vault_search


def test_query_logging_uses_one_human_readable_monthly_system_note(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        obsidian_vault_path=tmp_path,
        agent_notes_folder="Agent",
        enable_query_vector_storage=False,
    )
    monkeypatch.setattr(vault_search, "_settings", lambda: settings)

    vault_search._store_query("What did we decide about memory?")
    vault_search._store_query("What did we decide about memory?")
    vault_search._store_query("Find the Vellum architecture note")

    logs = list((tmp_path / "Agent" / "System" / "Search Logs").glob("Search Activity - *.md"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert text.count("What did we decide about memory?") == 1
    assert "Find the Vellum architecture note" in text
    assert not (tmp_path / "Agent" / "Queries").exists()
