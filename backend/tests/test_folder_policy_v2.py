from agent.obsidian.folder_policy import (
    can_index,
    can_send_to_llm,
    can_store,
)


def test_meta_sent_to_llm():
    assert can_send_to_llm("Meta/profile.md")
    assert can_send_to_llm("Meta/goals.md")


def test_projects_sent_to_llm():
    assert can_send_to_llm("Projects/fitness/vellum.md")
    assert can_send_to_llm("Projects/fitness/hot.md")
    assert can_send_to_llm("Projects/fitness/notes/anything.md")


def test_library_books_private():
    assert not can_send_to_llm("Library/Books/some-book.md")
    assert can_index("Library/Books/some-book.md")


def test_library_feedback_private():
    assert not can_send_to_llm("Library/feedback/note.md")


def test_library_x_sent():
    assert can_send_to_llm("Library/X/naval/topics/leverage.md")


def test_library_youtube_sent():
    assert can_send_to_llm("Library/Youtube/channels/moresidemen/latest.md")


def test_library_sports_sent():
    assert can_send_to_llm("Library/Sports/NBA/lakers.md")


def test_agent_unchanged():
    assert can_send_to_llm("Agent/Responses/QA 20260108_143022.md")
    assert can_store("Agent/Queries/x.md")


def test_default_private():
    assert not can_send_to_llm("Unknown/something.md")


# Backward-compat for pre-migration top-level paths (must keep working until
# users run the migration script).
def test_backward_compat_top_level_x_sent():
    assert can_send_to_llm("X/naval/topics/leverage.md")


def test_backward_compat_top_level_books_private():
    assert not can_send_to_llm("Books/some-book.md")
