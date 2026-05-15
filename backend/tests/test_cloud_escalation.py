from agent.tools import cloud_escalation


def test_agent_prompt_mentions_cloud_escalation():
    from agent.graph.agent import VELLUM_SYSTEM_PROMPT

    assert "escalate_to_cloud" in VELLUM_SYSTEM_PROMPT
    assert "private vault" in VELLUM_SYSTEM_PROMPT.casefold()


def test_public_code_task_auto_allowed():
    decision = cloud_escalation.classify_escalation_request(
        "Debug this FastAPI route",
        "Public repo code and documentation.",
        approval=False,
    )

    assert decision.privacy_class == "public"
    assert decision.allowed is True


def test_private_vault_task_requires_approval():
    decision = cloud_escalation.classify_escalation_request(
        "Summarize my notes",
        "Agent/Memories/vellum-computer-use-gemma-orchestration.md",
        approval=False,
    )

    assert decision.privacy_class == "private"
    assert decision.allowed is False
    assert "requires approval" in decision.reason


def test_private_vault_task_allowed_with_approval():
    decision = cloud_escalation.classify_escalation_request(
        "Summarize my notes",
        "Agent/Memories/vellum-computer-use-gemma-orchestration.md",
        approval=True,
    )

    assert decision.privacy_class == "private"
    assert decision.allowed is True


def test_secret_content_is_blocked_even_with_approval():
    decision = cloud_escalation.classify_escalation_request(
        "Use this key",
        "OPENROUTER_API_KEY=sk-secret",
        approval=True,
    )

    assert decision.privacy_class == "secret"
    assert decision.allowed is False


def test_parse_structured_cloud_json():
    parsed = cloud_escalation.parse_cloud_response(
        '{"answer":"done","what_gemma_missed":"x","workflow_used":"y","lesson_for_vellum":"z","suggested_skill":"s"}'
    )

    assert parsed["answer"] == "done"
    assert parsed["lesson_for_vellum"] == "z"


def test_parse_non_json_cloud_text_as_best_effort():
    parsed = cloud_escalation.parse_cloud_response("Use pytest and inspect the traceback.")

    assert parsed["answer"] == "Use pytest and inspect the traceback."
    assert parsed["lesson_for_vellum"]


def test_escalate_to_cloud_blocks_private_without_approval():
    result = cloud_escalation.escalate_to_cloud.invoke(
        {"task": "Use my memory", "context": "Agent/Memories/private.md", "approval": False}
    )

    assert "requires approval" in result


def test_escalate_to_cloud_blocks_secret():
    result = cloud_escalation.escalate_to_cloud.invoke(
        {"task": "Use key", "context": "OPENROUTER_API_KEY=sk-secret", "approval": True}
    )

    assert "blocked" in result


def test_escalate_to_cloud_saves_lesson(monkeypatch):
    saved = {}

    def fake_cloud(task, context, privacy_class):
        return {
            "answer": "Use the traceback.",
            "what_gemma_missed": "It did not inspect the failing line.",
            "workflow_used": "Ran focused test, inspected traceback.",
            "lesson_for_vellum": "Always inspect the first concrete traceback line.",
            "suggested_skill": "Debug pytest failures from traceback first.",
        }

    def fake_obsidian(params):
        saved.update(params)
        return "saved"

    monkeypatch.setattr(cloud_escalation, "_call_cloud_model", fake_cloud)
    monkeypatch.setattr(cloud_escalation, "obsidian_run", fake_obsidian)

    result = cloud_escalation.escalate_to_cloud.invoke(
        {"task": "Debug public pytest failure", "context": "public repo traceback", "reason": "tool failed"}
    )

    assert "Cloud escalation used" in result
    assert "Use the traceback" in result
    assert saved["action"] == "write"
    assert saved["path"].startswith("Agent/Memories/Lessons/")
    assert "Always inspect" in saved["content"]
