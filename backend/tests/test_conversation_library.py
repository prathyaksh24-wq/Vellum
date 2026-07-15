from __future__ import annotations

import json
from pathlib import Path

from agent.conversations.library import build_conversation_library, organize_conversation, search_conversations


CASES = json.loads(
    (Path(__file__).parents[1] / "evals" / "conversation_library_cases.json").read_text(encoding="utf-8")
)
CONVERSATIONS = {item["id"]: item for item in CASES["conversations"]}


def test_organizer_classifies_topics_and_plugin_sources_locally() -> None:
    for case in CASES["classification"]:
        result = organize_conversation(CONVERSATIONS[case["id"]])
        assert result["space_id"] == case["space"]
        assert result["topic_id"] == case["topic"]
        assert result["sources"] == case["sources"]


def test_topic_drift_creates_message_addressable_segments() -> None:
    result = organize_conversation(CONVERSATIONS["mixed-topic"])

    assert [segment["space_id"] for segment in result["segments"]] == ["sports", "vellum"]
    assert result["segments"][0]["start_message_id"] == "mix-u1"
    assert result["segments"][1]["start_message_id"] == "mix-u2"


def test_manual_assignment_is_stable_while_facets_refresh() -> None:
    conversation = {
        **CONVERSATIONS["f1-calendar"],
        "organization": {
            "assignment": "manual",
            "space_id": "weekend",
            "space_label": "Weekend",
            "topic_id": "motorsport",
            "topic_label": "Motorsport",
        },
    }

    result = organize_conversation(conversation)

    assert result["space_id"] == "weekend"
    assert result["topic_id"] == "motorsport"
    assert result["confidence"] == 1.0
    assert result["sources"] == ["Calendar"]


def test_library_is_a_projection_with_shallow_spaces_and_smart_views() -> None:
    source = list(CONVERSATIONS.values())
    library = build_conversation_library(source)

    assert source[0].get("organization") is None
    assert {space["id"] for space in library["spaces"]} >= {"sports", "music", "vellum", "personal"}
    assert all("topics" in space for space in library["spaces"])
    assert {view["id"] for view in library["smart_views"]} >= {"calendar", "slack", "spotify"}


def test_repeated_unknown_subjects_form_a_dynamic_space_but_one_offs_do_not() -> None:
    conversations = [
        CONVERSATIONS["sourdough-starter"],
        CONVERSATIONS["bread-temperature"],
        {"id": "one-off", "title": "Repair a fountain pen", "messages": [{"id": "p1", "role": "user", "text": "How do I repair a fountain pen nib?"}]},
    ]

    library = build_conversation_library(conversations)
    organizations = {item["id"]: item["organization"] for item in library["conversations"]}

    assert organizations["sourdough-starter"]["space_id"] == "bread"
    assert organizations["bread-temperature"]["space_id"] == "bread"
    assert organizations["one-off"]["space_id"] == "unsorted"
    assert next(space for space in library["spaces"] if space["id"] == "bread")["count"] == 2


def test_persisted_dynamic_space_anchors_future_matching_chats() -> None:
    first = build_conversation_library([
        CONVERSATIONS["sourdough-starter"],
        CONVERSATIONS["bread-temperature"],
    ])
    third = {
        "id": "rye-loaf",
        "title": "Rye bread loaf",
        "messages": [{"id": "rye-u1", "role": "user", "text": "How long should rye bread proof before baking?"}],
    }

    second = build_conversation_library([*first["conversations"], third])
    organizations = {item["id"]: item["organization"] for item in second["conversations"]}

    assert organizations["rye-loaf"]["space_id"] == "bread"
    assert next(space for space in second["spaces"] if space["id"] == "bread")["count"] == 3


def test_search_ranks_expected_chat_and_returns_exact_message_target() -> None:
    conversations = list(CONVERSATIONS.values())
    for case in CASES["search"]:
        hits = search_conversations(conversations, case["query"])
        assert hits, case["query"]
        assert hits[0]["id"] == case["expected_first"], case["query"]
        assert hits[0]["message_id"]
        assert hits[0]["snippet"]


def test_search_filters_by_space_source_and_archive_state() -> None:
    conversations = list(CONVERSATIONS.values())

    calendar_hits = search_conversations(conversations, "calendar", source="Calendar")
    sports_hits = search_conversations(conversations, "match", space="Sports")

    assert {hit["id"] for hit in calendar_hits} == {"f1-calendar", "personal-trip"}
    assert sports_hits[0]["id"] == "arsenal-fixtures"
