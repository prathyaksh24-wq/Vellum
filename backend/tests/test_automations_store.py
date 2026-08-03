import json

from agent.automations.store import MAX_RUN_HISTORY, AutomationStore


def _automation(store: AutomationStore, name: str = "morning brief") -> dict:
    return store.create(
        name=name,
        instructions="Summarize the morning inputs.",
        schedule={"kind": "cron", "expression": "0 8 * * *"},
        destination={"kind": "new_chat"},
        model_profile={"tier": "primary", "reasoning_mode": "high"},
    )


def test_store_round_trips_an_automation(tmp_path) -> None:
    store = AutomationStore(tmp_path)

    created = _automation(store)

    assert created["id"].startswith("automation-")
    assert created["state"] == "active"
    assert created["builtin"] is False
    assert created["permission"]["full_access"] is False
    assert created["run_history"] == []

    loaded = AutomationStore(tmp_path).get(created["id"])
    assert loaded == created


def test_store_writes_atomically_with_temp_file(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _automation(store)

    assert (tmp_path / "automations.json").exists()
    assert not (tmp_path / "automations.json.tmp").exists()
    data = json.loads((tmp_path / "automations.json").read_text(encoding="utf-8"))
    assert len(data) == 1


def test_update_validates_state_and_mutates_fields(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation_id = _automation(store)["id"]

    updated = store.update(automation_id, state="paused", instructions="Different prompt.")
    assert updated["state"] == "paused"
    assert updated["instructions"] == "Different prompt."

    try:
        store.update(automation_id, state="bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid state should be rejected")

    assert store.get(automation_id)["state"] == "paused"


def test_remove_deletes_automation(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation_id = _automation(store)["id"]

    store.remove(automation_id)

    try:
        store.get(automation_id)
    except ValueError:
        pass
    else:
        raise AssertionError("removed automation should not be found")


def test_run_history_is_bounded_and_ordered(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation_id = _automation(store)["id"]

    for index in range(MAX_RUN_HISTORY + 10):
        run_id = f"run-{index}"
        store.record_run(automation_id, run_id)
        store.finish_run(automation_id, run_id, status="complete", output=f"out-{index}")

    runs = store.runs(automation_id)
    assert len(runs) == MAX_RUN_HISTORY
    assert runs[0]["id"] == "run-10"
    assert runs[-1]["id"] == f"run-{MAX_RUN_HISTORY + 9}"
    assert runs[-1]["output"] == f"out-{MAX_RUN_HISTORY + 9}"
    assert runs[-1]["finished_at"] is not None


def test_finish_run_records_failure(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation_id = _automation(store)["id"]

    store.record_run(automation_id, "run-1")
    store.finish_run(automation_id, "run-1", status="failed", error="provider timeout")

    run = store.runs(automation_id)[0]
    assert run["status"] == "failed"
    assert run["error"] == "provider timeout"


def test_corrupt_file_recovered_and_preserved(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _automation(store)
    (tmp_path / "automations.json").write_text("{not-valid-json", encoding="utf-8")

    assert store.list() == []

    assert (tmp_path / "automations.json.corrupt").exists()


def test_list_filters_by_state(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    first = _automation(store, name="one")
    store.update(first["id"], state="paused")

    assert [item["id"] for item in store.list(state="paused")] == [first["id"]]
    assert store.list(state="active") == []
