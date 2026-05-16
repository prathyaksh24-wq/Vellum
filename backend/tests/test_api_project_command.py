import pytest

from agent import api as api_mod


@pytest.mark.asyncio
async def test_chat_intercepts_project_command(monkeypatch, tmp_path):
    # Reset singleton and point context at tmp vault via fake settings
    monkeypatch.setattr(api_mod, "_project_context_singleton", None, raising=False)

    class FakeSettings:
        obsidian_vault_path = tmp_path
        thread_id = "default"

    monkeypatch.setattr(api_mod, "get_settings", lambda: FakeSettings())

    response = await api_mod._run_agent("/project", thread_id="t1")
    assert isinstance(response.answer, str)
    assert "active:" in response.answer.lower()
