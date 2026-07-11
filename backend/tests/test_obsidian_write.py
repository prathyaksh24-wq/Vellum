from types import SimpleNamespace

from agent.tools import obsidian_write


def test_store_qa_pair_is_a_noop_compatibility_hook(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        obsidian_vault_path=tmp_path,
        agent_notes_folder="Agent",
        enable_vector_search=False,
    )
    monkeypatch.setattr(obsidian_write, "get_settings", lambda: settings)

    touched = {"vector": False}

    def fail_vector_store():
        touched["vector"] = True
        raise RuntimeError("vector store should not be touched when vector search is disabled")

    monkeypatch.setattr(obsidian_write, "get_vector_store", fail_vector_store)

    obsidian_write.store_qa_pair("question", "answer")

    assert not (tmp_path / "Agent" / "Responses").exists()
    assert touched["vector"] is False
