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
    for folder in ("Books", "feedback"):
        assert can_store(folder) is True
        assert can_index(folder) is True
        assert can_send_to_llm(folder) is False
        assert can_use_tools(folder) is False
        assert needs_scrubbing(folder) is True


def test_public_content_folders_can_go_to_llm_and_tools():
    for folder in ("X", "X/naval", "X/another-public-profile", "Youtube", "Youtube/channels/moresidemen"):
        assert can_store(folder) is True
        assert can_index(folder) is True
        assert can_send_to_llm(folder) is True
        assert can_use_tools(folder) is True
        assert needs_scrubbing(folder) is False


def test_sports_folders_can_go_to_llm_and_tools():
    for folder in ("Sports", "Sports/NBA", "Sports/Formula One", "Sports/football"):
        assert can_store(folder) is True
        assert can_index(folder) is True
        assert can_send_to_llm(folder) is True
        assert can_use_tools(folder) is True
        assert needs_scrubbing(folder) is False


def test_agent_memories_can_go_to_llm_and_tools():
    for folder in ("Agent", "Agent/Memories", "Agent/Memories/X/naval"):
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
        {"metadata": {"path": "Youtube/channels/moresidemen/latest-5.md"}, "text": "public youtube note"},
        {"path": "Books/private.md", "text": "private book note"},
    ]

    allowed, blocked = filter_chunks_for_llm(chunks)

    assert [chunk["text"] for chunk in allowed] == ["public sports note", "public youtube note"]
    assert [chunk["text"] for chunk in blocked] == [
        "private book note",
    ]
    assert [chunk_folder(chunk) for chunk in blocked] == ["Books"]
