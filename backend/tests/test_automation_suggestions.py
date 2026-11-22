"""Scheduled-page suggestions: grounded in signals, validated, cached, privacy-scrubbed."""

import json

from agent.automations.suggestions import (
    STARTER_SUGGESTIONS,
    AutomationSuggestions,
    parse_suggestions,
    scrub_signals,
)

SIGNALS = {
    "memories": ["The user follows the NBA closely.", "The user is job hunting for backend roles."],
    "chats": ["Lakers trade rumours", "Resume review"],
    "tasks": ["Weekly NBA recap"],
}


def _answer(*items):
    return json.dumps({"suggestions": list(items)})


def test_learned_suggestions_replace_starters_and_skip_existing_tasks(tmp_path) -> None:
    prompts = []

    def ask(system, prompt):
        prompts.append(prompt)
        return _answer(
            {"name": "Weekly NBA recap", "icon": "sports", "request": "Every Monday, recap the NBA week.", "reason": "dup"},
            {"name": "Backend job matches", "icon": "work", "request": "Every Monday and Thursday at 9am, find new backend roles that fit me.", "reason": "You are job hunting."},
            {"name": "Odd icon", "icon": "rocket", "request": "Every day at 7am, check something.", "reason": ""},
        )

    service = AutomationSuggestions(tmp_path, signals=lambda: SIGNALS, ask=ask, background=False)
    snapshot = service.snapshot()

    assert snapshot["source"] == "learned"
    assert [item["name"] for item in snapshot["suggestions"]] == ["Backend job matches", "Odd icon"]
    assert snapshot["suggestions"][1]["icon"] == "research"
    assert "job hunting" in prompts[0] and "Lakers trade rumours" in prompts[0]

    # Fresh cache with unchanged signals: no second model call.
    service.snapshot()
    assert len(prompts) == 1


def test_model_failure_keeps_starters_and_reports_unavailable(tmp_path) -> None:
    def ask(system, prompt):
        raise RuntimeError("privacy is set to local only; learning waits for a local model")

    snapshot = AutomationSuggestions(tmp_path, signals=lambda: SIGNALS, ask=ask, background=False).snapshot()

    assert snapshot["source"] == "starter"
    assert snapshot["suggestions"] == STARTER_SUGGESTIONS
    assert snapshot["status"] == "unavailable"
    assert "local only" in snapshot["reason"]


def test_nothing_learned_yet_shows_starters_without_a_model_call(tmp_path) -> None:
    def ask(system, prompt):
        raise AssertionError("no model call without signals")

    snapshot = AutomationSuggestions(tmp_path, signals=lambda: {"memories": [], "chats": [], "tasks": []},
                                     ask=ask, background=False).snapshot()

    assert snapshot["source"] == "starter"


def test_parse_rejects_placeholders_and_non_json() -> None:
    assert parse_suggestions(_answer({"name": "Call mum", "icon": "home", "request": "Remind me to call [PERSON]."})) == []
    try:
        parse_suggestions("no json here")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_scrub_drops_secrets_and_masks_contact_details() -> None:
    clean = scrub_signals({
        "memories": ["My api_key: sk-123", "Email me at someone@example.com about NBA scores."],
        "chats": [],
        "tasks": [],
    })

    assert len(clean["memories"]) == 1
    assert "someone@example.com" not in clean["memories"][0]
    assert "NBA" in clean["memories"][0]
