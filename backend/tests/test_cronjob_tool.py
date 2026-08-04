"""Tool-call tests for the cronjob action tool (ticket 07)."""

import json

import pytest

from agent.automations import api as automations_api
from agent.automations import builtins
from agent.automations.store import AutomationStore
from agent.tools.cronjob import cronjob


@pytest.fixture
def store(tmp_path):
    store = AutomationStore(tmp_path / "automations")
    automations_api.set_store(store)
    automations_api.set_mutation_hook(None)
    yield store
    automations_api.set_store(None)
    automations_api.set_mutation_hook(None)


def _invoke(**payload) -> dict:
    return json.loads(cronjob.invoke(payload))


def test_cronjob_tool_creates_automation(store):
    mutations = []
    automations_api.set_mutation_hook(lambda automation_id: mutations.append(automation_id))

    result = _invoke(
        action="create",
        name="Morning summary",
        instructions="Summarize the vault changes from yesterday.",
        schedule="0 9 * * *",
    )

    assert result["ok"] is True
    automation = result["automation"]
    assert automation["name"] == "Morning summary"
    assert automation["schedule"]["expression"] == "0 9 * * *"
    assert automation["destination"]["kind"] == "new_chat"
    assert automation["permission"]["full_access"] is False
    assert automation["state"] == "active"
    assert automation["run_count"] == 0
    records = store.list()
    assert len(records) == 1
    assert records[0]["id"] == automation["id"]
    assert mutations == [automation["id"]]


def test_cronjob_tool_creates_existing_chat_destination(store):
    result = _invoke(
        action="create",
        name="Pinned digest",
        instructions="Append a short digest to my pinned thread.",
        schedule="every 1d at 09:00",
        destination="existing_chat",
        thread_id="thread-123",
        full_access=True,
        reasoning_mode="high",
    )

    assert result["ok"] is True
    automation = result["automation"]
    assert automation["destination"] == {"kind": "existing_chat", "thread_id": "thread-123"}
    assert automation["permission"]["full_access"] is True
    assert automation["model_profile"]["reasoning_mode"] == "high"


def test_cronjob_tool_rejects_bad_schedule(store):
    result = _invoke(
        action="create",
        name="Broken",
        instructions="Do a thing.",
        schedule="every 99 lightyears",
    )

    assert result["ok"] is False
    assert "invalid" in result["error"].lower() or "schedule" in result["error"].lower()
    assert store.list() == []


def test_cronjob_tool_rejects_blank_required_fields(store):
    no_name = _invoke(action="create", name="", instructions="Do a thing.", schedule="30m")
    assert no_name["ok"] is False
    assert "name is required" in no_name["error"]

    no_instructions = _invoke(action="create", name="X", instructions="", schedule="30m")
    assert no_instructions["ok"] is False
    assert "instructions are required" in no_instructions["error"]

    no_schedule = _invoke(action="create", name="X", instructions="Do a thing.", schedule="")
    assert no_schedule["ok"] is False
    assert "schedule is required" in no_schedule["error"]


def test_cronjob_tool_existing_chat_requires_thread_id(store):
    result = _invoke(
        action="create",
        name="No thread",
        instructions="Do a thing.",
        schedule="30m",
        destination="existing_chat",
    )

    assert result["ok"] is False
    assert "requires a thread_id" in result["error"]


def test_cronjob_tool_lists_automations(store):
    _invoke(action="create", name="Alpha", instructions="A", schedule="30m")
    _invoke(action="create", name="Beta", instructions="B", schedule="0 1 * * *")

    result = _invoke(action="list")

    assert result["ok"] is True
    names = {item["name"] for item in result["automations"]}
    assert names == {"Alpha", "Beta"}


def test_cronjob_tool_updates_automation(store):
    created = _invoke(action="create", name="Old", instructions="Old text", schedule="30m")
    automation_id = created["automation"]["id"]

    result = _invoke(
        action="update",
        automation_id=automation_id,
        name="New",
        schedule="every 2h",
        full_access=True,
    )

    assert result["ok"] is True
    automation = result["automation"]
    assert automation["name"] == "New"
    assert automation["schedule"]["expression"] == "every 2h"
    assert automation["permission"]["full_access"] is True
    assert automation["instructions"] == "Old text"


def test_cronjob_tool_update_rejects_unknown_id(store):
    result = _invoke(action="update", automation_id="automation-nope", name="X")

    assert result["ok"] is False
    assert "not found" in result["error"]


def test_cronjob_tool_pause_and_resume(store):
    created = _invoke(action="create", name="Flip", instructions="A", schedule="30m")
    automation_id = created["automation"]["id"]

    paused = _invoke(action="pause", automation_id=automation_id)
    assert paused["automation"]["state"] == "paused"

    resumed = _invoke(action="resume", automation_id=automation_id)
    assert resumed["automation"]["state"] == "active"


def test_cronjob_tool_removes_automation(store):
    created = _invoke(action="create", name="Gone", instructions="A", schedule="30m")
    automation_id = created["automation"]["id"]

    result = _invoke(action="remove", automation_id=automation_id)

    assert result["ok"] is True
    assert result["removed"] == automation_id
    assert store.list() == []


def test_cronjob_tool_restores_builtin_on_remove(store):
    builtins.seed_builtins(store)
    digest = next(r for r in store.list() if r["builtin_key"] == "nightly_digest")
    store.update(digest["id"], name="Scratched", state="paused")

    result = _invoke(action="remove", automation_id=digest["id"])

    assert result["ok"] is True
    assert result["restored"] is True
    record = store.get(digest["id"])
    assert record is not None
    assert record["name"] == "Nightly digest"
    assert record["schedule"]["expression"] == "15 2 * * *"
    assert record["state"] == "active"


def test_cronjob_tool_run_now(store, monkeypatch):
    created = _invoke(action="create", name="Run me", instructions="A", schedule="30m")
    automation_id = created["automation"]["id"]

    async def fake_run_automation_now(automation, store_):
        return {"id": "run-abc", "status": "complete", "output": "done"}

    monkeypatch.setattr("agent.automations.runner.run_automation_now", fake_run_automation_now)

    result = _invoke(action="run", automation_id=automation_id)

    assert result["ok"] is True
    assert result["run"]["status"] == "complete"
    assert result["run"]["id"] == "run-abc"


def test_cronjob_tool_run_now_unknown_id(store):
    result = _invoke(action="run", automation_id="automation-nope")

    assert result["ok"] is False
    assert "not found" in result["error"]


def test_cronjob_tool_unknown_action(store):
    result = _invoke(action="explode")

    assert result["ok"] is False
    assert "Unsupported cronjob action" in result["error"]


def test_cronjob_tool_validation_error_matches_api(tmp_path):
    from fastapi.testclient import TestClient

    from agent import api

    store = AutomationStore(tmp_path / "automations")
    automations_api.set_store(store)
    try:
        tool_result = _invoke(
            action="create",
            name="Bad",
            instructions="A",
            schedule="every 99 lightyears",
        )

        with TestClient(api.app) as client:
            response = client.post(
                "/api/automations",
                json={
                    "name": "Bad",
                    "instructions": "A",
                    "schedule": "every 99 lightyears",
                },
            )
    finally:
        automations_api.set_store(None)

    assert response.status_code == 400
    assert tool_result["ok"] is False
    assert tool_result["error"] == response.json()["detail"]


def test_create_prompt_endpoint_prefills_chat_guidance(tmp_path):
    from fastapi.testclient import TestClient

    from agent import api

    automations_api.set_store(AutomationStore(tmp_path / "automations"))
    try:
        with TestClient(api.app) as client:
            response = client.get("/api/automations/create-prompt")
    finally:
        automations_api.set_store(None)

    assert response.status_code == 200
    prompt = response.json()["prompt"]
    assert "cronjob" in prompt
    assert "0 9 * * *" in prompt
    assert "full access" in prompt
