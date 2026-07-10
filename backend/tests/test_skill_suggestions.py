from agent.skills import BlueprintSuggestionStore, SkillManager


BLUEPRINT_SKILL = """---
name: morning-brief
description: Prepare a morning brief
metadata:
  hermes:
    blueprint:
      schedule: "0 8 * * *"
      deliver: origin
      prompt: Summarize the morning inputs.
---
# Morning Brief

## Procedure
Summarize approved inputs.
"""


def test_blueprint_suggestion_is_stable_deduplicated_and_latched(tmp_path) -> None:
    store = BlueprintSuggestionStore(tmp_path)

    first = store.observe(
        skill_name="morning-brief",
        schedule="0 8 * * *",
        deliver="origin",
        prompt="Summarize the morning inputs.",
        no_agent=False,
    )
    second = store.observe(
        skill_name="morning-brief",
        schedule="0 8 * * *",
        deliver="origin",
        prompt="Summarize the morning inputs.",
        no_agent=False,
    )

    assert first["id"] == second["id"]
    assert len(store.list()) == 1

    store.dismiss(first["id"])
    observed = store.observe(
        skill_name="morning-brief",
        schedule="0 8 * * *",
        deliver="origin",
        prompt="Summarize the morning inputs.",
        no_agent=False,
    )
    assert observed["state"] == "dismissed"

    store.accept(first["id"])
    assert store.get(first["id"])["state"] == "accepted"
    assert not (tmp_path / "scheduled-jobs.json").exists()


def test_skill_manager_creates_blueprint_suggestion_without_scheduling(tmp_path) -> None:
    result = SkillManager(tmp_path).create(BLUEPRINT_SKILL, confirm=True)

    suggestions = BlueprintSuggestionStore(tmp_path).list()
    assert result["suggestion_id"] == suggestions[0]["id"]
    assert suggestions[0]["state"] == "pending"
    assert suggestions[0]["skill_name"] == "morning-brief"
