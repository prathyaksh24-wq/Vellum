"""Chat titles come from what the chat is about, with safe fallbacks."""

from agent.conversations.titles import clean_title, fallback_title, suggest_title


def test_title_uses_request_and_reply() -> None:
    seen = []

    def ask(system, prompt):
        seen.append(prompt)
        return '"Scheduled Job Matches."'

    result = suggest_title(
        "Every Monday and Thursday morning, find fresh job matches for me.",
        "I'll set up a scheduled task that searches for backend roles twice a week.",
        ask=ask,
    )

    assert result == {"title": "Scheduled Job Matches", "source": "model"}
    assert "Request:" in seen[0] and "backend roles" in seen[0]


def test_unusable_model_output_falls_back_to_message_words() -> None:
    result = suggest_title("Can you please review my backend resume?", "Sure.",
                           ask=lambda system, prompt: "Title: [PERSON] resume")
    assert result == {"title": "Review My Backend Resume", "source": "fallback"}


def test_model_errors_fall_back() -> None:
    def ask(system, prompt):
        raise RuntimeError("no model")

    assert suggest_title("hi", "Hello!", ask=ask)["source"] == "fallback"


def test_secrets_never_reach_the_model() -> None:
    def ask(system, prompt):
        raise AssertionError("must not be called")

    result = suggest_title("my api_key: sk-live-123 why does it fail", "", ask=ask)
    assert result["source"] == "fallback"


def test_clean_and_fallback_shapes() -> None:
    assert clean_title("Title: NBA Trade Deadline Recap!\nextra") == "NBA Trade Deadline Recap"
    assert clean_title("a b c d e f g h i j k") == ""
    assert clean_title('{ "title": "Lakers Game Analysis" }') == "Lakers Game Analysis"
    assert clean_title('{"name": "x"}') == ""
    assert fallback_title("") == "New chat"
    assert fallback_title("hey vellum, plan my weekend in Goa") == "Plan My Weekend in Goa"
