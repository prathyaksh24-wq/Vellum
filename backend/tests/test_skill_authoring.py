from agent.skills import build_learn_prompt


def test_learn_prompt_enforces_hermes_structure_and_vellum_privacy() -> None:
    prompt = build_learn_prompt("https://docs.example.com/sdk", focus="authentication and pagination")

    assert "https://docs.example.com/sdk" in prompt
    assert "authentication and pagination" in prompt
    assert "## When to Use" in prompt
    assert "## Procedure" in prompt
    assert "## Pitfalls" in prompt
    assert "## Verification" in prompt
    assert "Do not invent commands" in prompt
    assert "private-folder" in prompt
    assert "machine paths" in prompt
    assert 'skill_manage(action="create"' in prompt


def test_learn_prompt_accepts_conversation_or_local_source_description() -> None:
    prompt = build_learn_prompt("the deployment workflow from this conversation")

    assert "existing tools" in prompt
    assert "the deployment workflow from this conversation" in prompt
