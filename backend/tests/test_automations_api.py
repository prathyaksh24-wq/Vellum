"""CRUD + validation tests for the real /api/automations endpoints.

No network and no LLM: the store lives in a tmp dir and the runner's reasoning
turn is monkeypatched. Heavy side-effecting api-module services are disabled,
matching the pattern of tests/test_api.py.
"""

import json

from fastapi.testclient import TestClient
import pytest

from agent import api
from agent.automations import api as automations_api
from agent.automations.store import AutomationStore


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "start_scheduler", lambda: None)
    monkeypatch.setattr(api, "start_vault_watcher", lambda: None)
    automations_api.set_store(AutomationStore(tmp_path / "data"))
    yield
    automations_api.set_store(None)


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Morning brief",
        "instructions": "Summarize what changed overnight.",
        "schedule": "every 2h",
        "destination": {"kind": "new_chat"},
    }
    payload.update(overrides)
    return client.post("/api/automations", json=payload)


def test_list_starts_empty_without_mock_marker() -> None:
    with TestClient(api.app) as client:
        response = client.get("/api/automations")

    assert response.status_code == 200
    body = response.json()
    assert "mock" not in body
    assert body["automations"] == []


def test_create_persists_parsed_schedule_and_defaults() -> None:
    with TestClient(api.app) as client:
        response = _create(client)

    assert response.status_code == 200
    automation = response.json()["automation"]
    assert automation["name"] == "Morning brief"
    assert automation["instructions"] == "Summarize what changed overnight."
    assert automation["state"] == "active"
    assert automation["builtin"] is False
    assert automation["schedule"]["kind"] == "interval"
    assert automation["schedule"]["expression"] == "every 2h"
    assert automation["destination"] == {"kind": "new_chat"}
    assert automation["permission"] == {"full_access": False}
    assert automation["run_history"] == []


def test_create_accepts_all_schedule_formats() -> None:
    with TestClient(api.app) as client:
        relative = _create(client, name="One-shot", schedule="30m")
        cron = _create(client, name="Cron", schedule="0 9 * * *")
        iso = _create(client, name="ISO", schedule="2026-08-03T09:00:00Z")

    assert relative.json()["automation"]["schedule"]["kind"] == "relative"
    assert cron.json()["automation"]["schedule"]["kind"] == "cron"
    assert iso.json()["automation"]["schedule"]["kind"] == "iso"


def test_create_rejects_invalid_schedule() -> None:
    with TestClient(api.app) as client:
        response = _create(client, schedule="not a schedule at all")

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].casefold()


def test_create_rejects_existing_chat_without_thread_id() -> None:
    with TestClient(api.app) as client:
        response = _create(client, destination={"kind": "existing_chat"})

    assert response.status_code == 400
    assert "thread_id" in response.json()["detail"]


def test_create_rejects_invalid_reasoning_mode() -> None:
    with TestClient(api.app) as client:
        response = _create(
            client,
            model_profile={"tier": "primary", "reasoning_mode": "galaxy"},
        )

    assert response.status_code == 400


def test_create_rejects_blank_name_and_unknown_fields() -> None:
    with TestClient(api.app) as client:
        blank = _create(client, name="   ")
        unknown = client.post(
            "/api/automations",
            json={
                "name": "x",
                "instructions": "y",
                "schedule": "1h",
                "surprise": True,
            },
        )

    assert blank.status_code == 422
    assert unknown.status_code == 422


def test_list_contains_created_automation() -> None:
    with TestClient(api.app) as client:
        created = _create(client).json()["automation"]
        listed = client.get("/api/automations").json()["automations"]

    assert [item["id"] for item in listed] == [created["id"]]


def test_patch_edits_fields_and_pauses() -> None:
    with TestClient(api.app) as client:
        automation_id = _create(client).json()["automation"]["id"]
        response = client.patch(
            f"/api/automations/{automation_id}",
            json={
                "name": "Renamed brief",
                "schedule": "every 1d at 09:00",
                "state": "paused",
                "permission": {"full_access": True},
            },
        )

    assert response.status_code == 200
    updated = response.json()["automation"]
    assert updated["name"] == "Renamed brief"
    assert updated["state"] == "paused"
    assert updated["permission"] == {"full_access": True}
    assert updated["schedule"]["kind"] == "interval"
    assert updated["schedule"]["at_time"] == "09:00"


def test_patch_rejects_invalid_schedule_and_state() -> None:
    with TestClient(api.app) as client:
        automation_id = _create(client).json()["automation"]["id"]
        bad_schedule = client.patch(
            f"/api/automations/{automation_id}",
            json={"schedule": "garbage"},
        )
        bad_state = client.patch(
            f"/api/automations/{automation_id}",
            json={"state": "archived"},
        )

    assert bad_schedule.status_code == 400
    assert bad_state.status_code == 422


def test_patch_missing_automation_is_404() -> None:
    with TestClient(api.app) as client:
        response = client.patch("/api/automations/automation-nope", json={"name": "x"})

    assert response.status_code == 404


def test_delete_removes_automation() -> None:
    with TestClient(api.app) as client:
        automation_id = _create(client).json()["automation"]["id"]
        deleted = client.delete(f"/api/automations/{automation_id}")
        listed = client.get("/api/automations").json()["automations"]
        missing = client.delete(f"/api/automations/{automation_id}")

    assert deleted.status_code == 200
    assert listed == []
    assert missing.status_code == 404


def test_runs_endpoint_returns_recorded_history() -> None:
    with TestClient(api.app) as client:
        automation_id = _create(client).json()["automation"]["id"]
        runs = client.get(f"/api/automations/{automation_id}/runs")
        missing = client.get("/api/automations/automation-nope/runs")

    assert runs.status_code == 200
    assert runs.json()["runs"] == []
    assert missing.status_code == 404


def test_run_now_records_complete_run(monkeypatch) -> None:
    from agent.automations import runner

    async def fake_turn(automation):
        return "Summarized the night."

    monkeypatch.setattr(runner, "_execute_reasoning_turn", fake_turn)

    with TestClient(api.app) as client:
        automation_id = _create(client).json()["automation"]["id"]
        ran = client.post(f"/api/automations/{automation_id}/run")
        runs = client.get(f"/api/automations/{automation_id}/runs").json()["runs"]

    assert ran.status_code == 200
    assert ran.json()["run"]["status"] == "complete"
    assert ran.json()["run"]["output"] == "Summarized the night."
    assert len(runs) == 1
    assert runs[0]["status"] == "complete"
    assert runs[0]["finished_at"] is not None


def test_run_now_records_failure_without_raising(monkeypatch) -> None:
    from agent.automations import runner

    async def failing_turn(automation):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(runner, "_execute_reasoning_turn", failing_turn)

    with TestClient(api.app) as client:
        automation_id = _create(client).json()["automation"]["id"]
        ran = client.post(f"/api/automations/{automation_id}/run")
        runs = client.get(f"/api/automations/{automation_id}/runs").json()["runs"]

    assert ran.status_code == 200
    assert ran.json()["run"]["status"] == "failed"
    assert "provider timeout" in ran.json()["run"]["error"]
    assert runs[0]["status"] == "failed"


def test_run_now_missing_automation_is_404() -> None:
    with TestClient(api.app) as client:
        response = client.post("/api/automations/automation-nope/run")

    assert response.status_code == 404


def test_run_now_delivers_new_chat_to_feed(monkeypatch, tmp_path) -> None:
    from agent.automations import runner

    conversations_path = tmp_path / "conversations.json"
    conversations_path.write_text('{"conversations": []}', encoding="utf-8")
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", conversations_path)

    async def fake_turn(automation):
        return "Feed summary."

    monkeypatch.setattr(runner, "_execute_reasoning_turn", fake_turn)

    with TestClient(api.app) as client:
        automation_id = _create(client).json()["automation"]["id"]
        ran = client.post(f"/api/automations/{automation_id}/run")

    assert ran.status_code == 200
    assert ran.json()["run"]["status"] == "complete"
    conversations = json.loads(conversations_path.read_text(encoding="utf-8"))["conversations"]
    assert len(conversations) == 1
    assert conversations[0]["title"] == "Automation: Morning brief"
    texts = [message["text"] for message in conversations[0]["messages"]]
    assert texts == ["Summarize what changed overnight.", "Feed summary."]


def test_run_now_appends_to_pinned_existing_chat(monkeypatch, tmp_path) -> None:
    from agent.automations import runner

    conversations_path = tmp_path / "conversations.json"
    conversations_path.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "pinned-1",
                        "thread_id": "thread-pinned",
                        "title": "Pinned briefing",
                        "created": "Today",
                        "pinned": True,
                        "archived": False,
                        "messages": [
                            {"role": "user", "text": "old question", "id": "m1"},
                            {"role": "assistant", "text": "old answer", "id": "m2"},
                        ],
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "organization": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", conversations_path)

    async def fake_turn(automation):
        return "Pinned summary."

    monkeypatch.setattr(runner, "_execute_reasoning_turn", fake_turn)

    with TestClient(api.app) as client:
        automation_id = _create(
            client,
            destination={"kind": "existing_chat", "thread_id": "thread-pinned"},
        ).json()["automation"]["id"]
        ran = client.post(f"/api/automations/{automation_id}/run")

    assert ran.status_code == 200
    assert ran.json()["run"]["status"] == "complete"
    conversations = json.loads(conversations_path.read_text(encoding="utf-8"))["conversations"]
    assert len(conversations) == 1
    texts = [message["text"] for message in conversations[0]["messages"]]
    assert texts == ["old question", "old answer", "Summarize what changed overnight.", "Pinned summary."]
    assert conversations[0]["updated_at"] != "2026-01-01T00:00:00+00:00"


def test_run_now_keeps_result_when_pinned_thread_missing(monkeypatch, tmp_path) -> None:
    from agent.automations import runner

    conversations_path = tmp_path / "conversations.json"
    conversations_path.write_text('{"conversations": []}', encoding="utf-8")
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", conversations_path)

    async def fake_turn(automation):
        return "Orphaned summary."

    monkeypatch.setattr(runner, "_execute_reasoning_turn", fake_turn)

    with TestClient(api.app) as client:
        automation_id = _create(
            client,
            destination={"kind": "existing_chat", "thread_id": "thread-gone"},
        ).json()["automation"]["id"]
        ran = client.post(f"/api/automations/{automation_id}/run")

    assert ran.status_code == 200
    assert ran.json()["run"]["status"] == "complete"
    assert ran.json()["run"]["output"] == "Orphaned summary."
    assert json.loads(conversations_path.read_text(encoding="utf-8"))["conversations"] == []
