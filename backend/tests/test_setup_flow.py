"""First-run setup: new users only, local model download, and applying the wizard's choices."""
import asyncio
import io
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from agent import setup_flow


def _sessions(root, *, titles=0, memories=0):
    db = root / "data" / "memory" / "sessions.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE thread_titles (id TEXT)")
        connection.execute("CREATE TABLE thread_state (id TEXT)")
        connection.execute("CREATE TABLE memory_items (id TEXT)")
        connection.executemany("INSERT INTO thread_titles VALUES (?)", [(str(i),) for i in range(titles)])
        connection.executemany("INSERT INTO memory_items VALUES (?)", [(str(i),) for i in range(memories)])


def test_a_fresh_install_needs_onboarding(tmp_path):
    assert setup_flow.onboarding_status(tmp_path) == {"needs_onboarding": True, "reason": "new_user"}
    _sessions(tmp_path)  # empty tables still mean a new user
    assert setup_flow.onboarding_status(tmp_path)["needs_onboarding"] is True


@pytest.mark.parametrize("history", [{"titles": 2}, {"memories": 1}])
def test_existing_users_never_see_onboarding_and_are_marked_set_up(tmp_path, history):
    _sessions(tmp_path, **history)
    assert setup_flow.onboarding_status(tmp_path) == {"needs_onboarding": False, "reason": "existing_user"}
    state = setup_flow.read_state(tmp_path)
    assert state["existing_user"] is True and state["completed_at"]
    assert setup_flow.onboarding_status(tmp_path)["reason"] == "completed"


def test_memories_imported_during_setup_do_not_end_it(tmp_path):
    assert setup_flow.onboarding_status(tmp_path)["reason"] == "new_user"
    _sessions(tmp_path, memories=3)  # imported from ChatGPT on the memory step
    assert setup_flow.onboarding_status(tmp_path) == {"needs_onboarding": True, "reason": "in_progress"}


def test_finished_setup_is_not_shown_again(tmp_path):
    setup_flow.write_state(tmp_path, {"completed_at": "2026-11-18T00:00:00+00:00"})
    assert setup_flow.onboarding_status(tmp_path) == {"needs_onboarding": False, "reason": "completed"}


class _Stream(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _wait(pull, timeout=5.0):
    deadline = time.monotonic() + timeout
    while pull.snapshot()["state"] == "pulling" and time.monotonic() < deadline:
        time.sleep(0.01)
    return pull.snapshot()


def test_model_pull_reports_progress_then_applies_the_model():
    lines = [{"status": "pulling manifest"}, {"status": "downloading", "total": 1000, "completed": 250},
             {"status": "downloading", "total": 1000, "completed": 1000}, {"status": "success"}]
    sent, applied = [], []

    def opener(request, timeout):
        sent.append((request.full_url, json.loads(request.data)))
        return _Stream(b"\n".join(json.dumps(line).encode() for line in lines))

    pull = setup_flow.ModelPull(opener=opener, on_done=lambda model: applied.append(model) or f"ollama/{model}")
    started = pull.start("http://127.0.0.1:11434", "hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M")
    assert started["state"] == "pulling"
    final = _wait(pull)
    assert final["state"] == "done" and final["percent"] == 100.0
    assert final["applied_model"] == "ollama/hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M"
    assert sent == [("http://127.0.0.1:11434/api/pull", {"model": "hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M", "stream": True})]
    assert applied == ["hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M"]


def test_model_pull_errors_are_reported_and_nothing_is_applied():
    applied = []
    pull = setup_flow.ModelPull(opener=lambda *a, **k: _Stream(json.dumps({"error": "pull model manifest: file does not exist"}).encode()),
                                on_done=applied.append)
    pull.start("http://127.0.0.1:11434", "hf.co/nobody/missing:Q4_K_M")
    final = _wait(pull)
    assert final["state"] == "error" and "couldn't be found" in final["error"]
    assert applied == []


def test_model_pull_rejects_bad_names_and_a_second_download():
    pull = setup_flow.ModelPull(opener=lambda *a, **k: _Stream(b""))
    with pytest.raises(ValueError):
        pull.start("http://x", "two words")
    pull.status = setup_flow.PullStatus(model="a", state="pulling")
    pull._thread = SimpleNamespace(is_alive=lambda: True)
    assert pull.start("http://x", "a")["model"] == "a"  # same model: just reports progress
    with pytest.raises(RuntimeError):
        pull.start("http://x", "b")


def test_ollama_status_when_not_running(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)

    def refuse(*a, **k):
        raise OSError("Connection refused")

    assert setup_flow.ollama_status("http://127.0.0.1:11434", opener=refuse) == {
        "installed": False, "running": False, "download_url": setup_flow.OLLAMA_DOWNLOAD_URL}


def _complete(monkeypatch, tmp_path, state, *, selectable=("ollama", "openrouter", "openai")):
    from agent import api

    calls = {"actions": [], "env": {}}

    def dispatch(action_id, arguments):
        calls["actions"].append((action_id, arguments))
        model = arguments.get("model") or f"{arguments.get('provider')}/default"
        return SimpleNamespace(result={"model": {"id": model}, "settings": {}})

    monkeypatch.setattr(api, "_dispatch_user_confirmed", dispatch)
    monkeypatch.setattr(api, "_set_env_value", lambda key, value: calls["env"].__setitem__(key, value))
    monkeypatch.setattr(api, "_SETUP_STATE_PATH", tmp_path / "setup_state.json")
    monkeypatch.setattr("agent.memory.engines.runtime.restart_engines", lambda: None)
    connections = [SimpleNamespace(id=p, model_selection_supported=p in selectable)
                   for p in ("ollama", "openrouter", "openai", "anthropic", "groq", "google")]
    monkeypatch.setattr("agent.llm.providers.provider_connections", lambda: connections)
    groups = [SimpleNamespace(key="anthropic", default_id="anthropic/claude-opus-5")]
    registry = lambda: SimpleNamespace(list_groups=lambda: groups)  # noqa: E731
    registry.cache_clear = lambda: None  # the shared cleanup clears the real one's cache
    monkeypatch.setattr("agent.llm.providers.get_provider_registry", registry)
    result = asyncio.run(api.setup_complete(api.SetupStateBody(state=state)))
    return result, calls, json.loads((tmp_path / "setup_state.json").read_text())


def test_complete_applies_privacy_learning_and_a_picker_provider(monkeypatch, tmp_path):
    from agent.app_actions.settings_runtime import DEFAULT_MODEL_SET_ACTION_ID, MEMORY_SETTINGS_UPDATE_ACTION_ID

    result, calls, saved = _complete(monkeypatch, tmp_path, {
        "apply_provider": "openrouter", "privacy": "ask_before_sharing", "learn": False,
        "connectors": ["gmail"], "openrouter_api_key": "sk-should-not-be-saved"})
    assert result["applied"] == {"model": "openrouter/default", "privacy": "ask_before_sharing", "learn": False}
    assert (DEFAULT_MODEL_SET_ACTION_ID, {"provider": "openrouter"}) in calls["actions"]
    assert (MEMORY_SETTINGS_UPDATE_ACTION_ID, {"patch": {"save_new_memories": False, "reference_history_enabled": False}}) in calls["actions"]
    assert calls["env"] == {"PRIVACY_MODE": "ask_before_sharing"}
    assert "openrouter_api_key" not in saved and saved["completed_at"] and saved["connectors"] == ["gmail"]


def test_complete_uses_the_vendor_default_model_for_claude(monkeypatch, tmp_path):
    result, calls, _ = _complete(monkeypatch, tmp_path, {"apply_provider": "anthropic"})
    assert result["applied"]["model"] == "anthropic/claude-opus-5"


def test_complete_leaves_the_model_for_key_only_providers_and_ignores_unknown_privacy(monkeypatch, tmp_path):
    result, calls, _ = _complete(monkeypatch, tmp_path, {"apply_provider": "groq", "privacy": "share_everything"})
    assert result["applied"] == {"model": "unchanged"}
    assert calls["env"] == {} and calls["actions"] == []
