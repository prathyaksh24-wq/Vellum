from concurrent.futures import ThreadPoolExecutor
import json

from agent.app_actions.automations import (
    AUTOMATION_CREATE_ACTION_ID,
    AUTOMATION_HISTORY_ACTION_ID,
    AUTOMATION_PAUSE_ACTION_ID,
    AUTOMATION_REMOVE_ACTION_ID,
    AUTOMATION_RESUME_ACTION_ID,
    AUTOMATION_RUN_ACTION_ID,
    AUTOMATION_UPDATE_ACTION_ID,
    AutomationActionService,
)
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.automations.store import AutomationStore


def _context() -> AppActionContext:
    return AppActionContext(source="nlp", invocation_conversation_id="chat-1")


def _arguments(**updates):
    values = {
        "name": "Morning brief",
        "description": "Start the day informed.",
        "instructions": "Summarize what changed overnight.",
        "schedule": "every 2h",
        "destination": {"kind": "new_chat"},
        "model_profile": {"tier": "fast", "reasoning_mode": "high"},
        "permission": {"full_access": False},
        "notifications": {"level": "important"},
    }
    values.update(updates)
    return values


def _runtime(tmp_path, *, scheduler_available=True, runner=None):
    store = AutomationStore(tmp_path / "data")
    notifications = []
    service = AutomationActionService(
        store_provider=lambda: store,
        scheduler_available=lambda: scheduler_available,
        mutation_notifier=lambda automation_id: notifications.append(automation_id),
        runner=runner,
    )
    return AppActionRuntime(automation_handler=service.execute), store, notifications


def _create(runtime: AppActionRuntime):
    return runtime.dispatch(
        AppActionRequest(action_id=AUTOMATION_CREATE_ACTION_ID, arguments=_arguments()),
        _context(),
    )


def test_catalog_exposes_all_automation_actions_only_when_owner_is_wired(tmp_path):
    runtime, _store, _notifications = _runtime(tmp_path)
    wired = {definition.id: definition for definition in runtime.catalog().actions}
    unwired = {definition.id for definition in AppActionRuntime().catalog().actions}

    assert set(wired).issuperset({
        AUTOMATION_CREATE_ACTION_ID,
        AUTOMATION_UPDATE_ACTION_ID,
        AUTOMATION_PAUSE_ACTION_ID,
        AUTOMATION_RESUME_ACTION_ID,
        AUTOMATION_RUN_ACTION_ID,
        AUTOMATION_HISTORY_ACTION_ID,
        AUTOMATION_REMOVE_ACTION_ID,
    })
    assert wired[AUTOMATION_RUN_ACTION_ID].confirmation_rule == "operation_bound"
    assert wired[AUTOMATION_REMOVE_ACTION_ID].access_class == "destructive"
    assert not set(unwired).intersection({
        AUTOMATION_CREATE_ACTION_ID,
        AUTOMATION_UPDATE_ACTION_ID,
        AUTOMATION_PAUSE_ACTION_ID,
        AUTOMATION_RESUME_ACTION_ID,
        AUTOMATION_RUN_ACTION_ID,
        AUTOMATION_HISTORY_ACTION_ID,
        AUTOMATION_REMOVE_ACTION_ID,
    })


def test_nlp_matches_automation_lifecycle_without_catching_casual_questions(tmp_path):
    runtime, _store, _notifications = _runtime(tmp_path)

    created = runtime.match_submission(
        "create an automation named Morning Brief to summarize overnight every 2h"
    )
    assert created.action_id == AUTOMATION_CREATE_ACTION_ID
    assert created.arguments["schedule"] == "every 2h"
    assert runtime.match_submission("pause automation Morning Brief").action_id == AUTOMATION_PAUSE_ACTION_ID
    assert runtime.match_submission("resume scheduled task Morning Brief").action_id == AUTOMATION_RESUME_ACTION_ID
    assert runtime.match_submission("run automation Morning Brief now").action_id == AUTOMATION_RUN_ACTION_ID
    assert runtime.match_submission("show run history for automation Morning Brief").action_id == AUTOMATION_HISTORY_ACTION_ID
    assert runtime.match_submission("delete automation Morning Brief").action_id == AUTOMATION_REMOVE_ACTION_ID
    update = runtime.match_submission("change automation Morning Brief schedule to every 1h")
    assert update.action_id == AUTOMATION_UPDATE_ACTION_ID
    assert update.arguments == {"reference": "Morning Brief", "schedule": "every 1h"}
    assert runtime.match_submission("How do scheduled automations work?") is None


def test_create_update_pause_resume_and_history_share_the_canonical_store(tmp_path):
    runtime, store, notifications = _runtime(tmp_path)
    created = _create(runtime)
    automation_id = created.result["automation"]["id"]

    updated = runtime.dispatch(
        AppActionRequest(
            action_id=AUTOMATION_UPDATE_ACTION_ID,
            arguments={"automation_id": automation_id, "schedule": "every 1d at 09:00"},
        ),
        _context(),
    )
    paused = runtime.dispatch(
        AppActionRequest(action_id=AUTOMATION_PAUSE_ACTION_ID, arguments={"automation_id": automation_id}),
        _context(),
    )
    resumed = runtime.dispatch(
        AppActionRequest(action_id=AUTOMATION_RESUME_ACTION_ID, arguments={"automation_id": automation_id}),
        _context(),
    )
    history = runtime.dispatch(
        AppActionRequest(action_id=AUTOMATION_HISTORY_ACTION_ID, arguments={"automation_id": automation_id}),
        _context(),
    )

    assert created.status == updated.status == paused.status == resumed.status == history.status == "applied"
    assert updated.result["automation"]["schedule"]["at_time"] == "09:00"
    assert paused.result["automation"]["state"] == "paused"
    assert resumed.result["automation"]["state"] == "active"
    assert history.result["runs"] == []
    assert store.get(automation_id)["state"] == "active"
    assert notifications == [automation_id, automation_id, automation_id, automation_id]


def test_invalid_create_and_update_payloads_do_not_mutate_store(tmp_path):
    runtime, store, notifications = _runtime(tmp_path)
    invalid_create = runtime.dispatch(
        AppActionRequest(
            action_id=AUTOMATION_CREATE_ACTION_ID,
            arguments=_arguments(schedule="not a schedule", permission={"full_access": "yes"}),
        ),
        _context(),
    )
    valid = _create(runtime)
    automation_id = valid.result["automation"]["id"]
    before = store.get(automation_id)
    invalid_update = runtime.dispatch(
        AppActionRequest(
            action_id=AUTOMATION_UPDATE_ACTION_ID,
            arguments={"automation_id": automation_id, "destination": {"kind": "existing_chat"}},
        ),
        _context(),
    )

    assert invalid_create.status == "failed"
    assert invalid_create.error_code == "INVALID_ACTION_ARGUMENTS"
    assert invalid_update.status == "failed"
    assert invalid_update.error_code == "INVALID_ACTION_ARGUMENTS"
    assert store.get(automation_id) == before
    assert len(store.list()) == 1
    assert notifications == [automation_id]


def test_run_and_remove_require_bound_confirmation(tmp_path):
    async def runner(record, store):
        run = store.record_run(record["id"], "run-test")
        return store.finish_run(record["id"], run["id"], status="complete", output="done")

    runtime, store, _notifications = _runtime(tmp_path, runner=runner)
    automation_id = _create(runtime).result["automation"]["id"]
    run_request = AppActionRequest(action_id=AUTOMATION_RUN_ACTION_ID, arguments={"automation_id": automation_id})
    run_review = runtime.dispatch(run_request, _context())

    assert run_review.status == "confirmation_required"
    assert store.runs(automation_id) == []
    ran = runtime.confirm(run_review.confirmation.token, run_request, _context())
    assert ran.status == "applied"
    assert ran.result["run"]["status"] == "complete"

    remove_request = AppActionRequest(action_id=AUTOMATION_REMOVE_ACTION_ID, arguments={"automation_id": automation_id})
    remove_review = runtime.dispatch(remove_request, _context())
    assert remove_review.status == "confirmation_required"
    assert store.get(automation_id)["id"] == automation_id
    removed = runtime.confirm(remove_review.confirmation.token, remove_request, _context())
    assert removed.status == "applied"
    assert removed.result["removed"] == automation_id
    assert store.list() == []


def test_confirmation_rejects_an_automation_that_changed_after_review(tmp_path):
    runtime, store, _notifications = _runtime(tmp_path)
    automation_id = _create(runtime).result["automation"]["id"]
    request = AppActionRequest(action_id=AUTOMATION_REMOVE_ACTION_ID, arguments={"automation_id": automation_id})
    review = runtime.dispatch(request, _context())
    store.update(automation_id, description="Changed after review")

    receipt = runtime.confirm(review.confirmation.token, request, _context())

    assert receipt.status == "failed"
    assert receipt.error_code == "STALE_ACTION_TARGET"
    assert store.get(automation_id)["description"] == "Changed after review"


def test_scheduler_unavailability_prevents_mutation(tmp_path):
    runtime, store, notifications = _runtime(tmp_path, scheduler_available=False)

    receipt = _create(runtime)

    assert receipt.status == "unavailable"
    assert receipt.error_code == "AUTOMATION_SCHEDULER_UNAVAILABLE"
    assert store.list() == []
    assert notifications == []


def test_concurrent_pause_actions_keep_the_store_valid(tmp_path):
    runtime, store, _notifications = _runtime(tmp_path)
    automation_id = _create(runtime).result["automation"]["id"]

    def pause(_index):
        return runtime.dispatch(
            AppActionRequest(action_id=AUTOMATION_PAUSE_ACTION_ID, arguments={"automation_id": automation_id}),
            _context(),
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(pause, range(24)))

    assert all(receipt.status == "applied" for receipt in receipts)
    assert store.get(automation_id)["state"] == "paused"
    assert isinstance(json.loads(store.path.read_text(encoding="utf-8")), dict)
