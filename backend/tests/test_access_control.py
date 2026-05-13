from agent.obsidian.folder_policy import (
    can_index,
    can_send_to_llm,
    can_store,
    can_use_tools,
    chunk_folder,
    filter_chunks_for_llm,
    needs_scrubbing,
)


def test_private_folders_are_local_only():
    for folder in ("X", "Youtube", "Books", "feedback"):
        assert can_store(folder) is True
        assert can_index(folder) is True
        assert can_send_to_llm(folder) is False
        assert can_use_tools(folder) is False
        assert needs_scrubbing(folder) is True


def test_public_x_collections_can_go_to_llm_and_tools():
    assert can_store("X/naval") is True
    assert can_index("X/naval") is True
    assert can_send_to_llm("X/naval") is True
    assert can_use_tools("X/naval") is True
    assert needs_scrubbing("X/naval") is False


def test_sports_folders_can_go_to_llm_and_tools():
    for folder in ("Sports", "Sports/NBA", "Sports/Formula One", "Sports/football"):
        assert can_store(folder) is True
        assert can_index(folder) is True
        assert can_send_to_llm(folder) is True
        assert can_use_tools(folder) is True
        assert needs_scrubbing(folder) is False


def test_default_policy_is_private_local_only():
    assert can_store("Unclassified") is True
    assert can_index("Unclassified") is True
    assert can_send_to_llm("Unclassified") is False
    assert can_use_tools("Unclassified") is False
    assert needs_scrubbing("Unclassified") is True


def test_folder_policy_filters_chunks_before_llm():
    chunks = [
        {"path": "Sports/NBA/latest.md", "text": "public sports note"},
        {"path": "Books/private.md", "text": "private book note"},
        {"metadata": {"path": "Youtube/private.md"}, "text": "private youtube note"},
    ]

    allowed, blocked = filter_chunks_for_llm(chunks)

    assert [chunk["text"] for chunk in allowed] == ["public sports note"]
    assert [chunk["text"] for chunk in blocked] == [
        "private book note",
        "private youtube note",
    ]
    assert [chunk_folder(chunk) for chunk in blocked] == ["Books", "Youtube"]
