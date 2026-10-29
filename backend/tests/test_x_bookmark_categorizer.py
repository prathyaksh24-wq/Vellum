from agent.knowledge.x_bookmark_categorizer import categorize_bookmark, categorize_bookmarks


def test_categorizer_uses_text_hashtags_and_known_tool_domains() -> None:
    result = categorize_bookmark(
        {
            "id": "1",
            "text": "A practical LLM agent built with Python #AI https://github.com/example/project",
            "url": "https://x.com/example/status/1",
        }
    )

    categories = [entry["category"] for entry in result["assignments"]]
    assert categories[0] == "dev-tools"
    assert "ai-resources" in categories
    assert result["entities"]["hashtags"] == ["ai"]
    assert result["entities"]["tools"] == ["GitHub"]
    assert result["taxonomy_version"] == "siftly-inspired-v1"


def test_categorizer_uses_general_only_when_no_specific_signal_exists() -> None:
    result = categorize_bookmark({"id": "2", "text": "A quiet Sunday morning."})

    assert result["assignments"] == [
        {"category": "general", "name": "General", "confidence": 0.5}
    ]


def test_categorize_bookmarks_preserves_source_item() -> None:
    items = categorize_bookmarks([{"id": "3", "text": "Figma UI design system"}])

    assert items[0]["id"] == "3"
    assert items[0]["bookmark_intelligence"]["assignments"][0]["category"] == "design"
