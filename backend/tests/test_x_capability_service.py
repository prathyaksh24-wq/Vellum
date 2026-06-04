from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.registry import ToolPermissionError


def test_x_service_search_posts_returns_structured_records():
    calls = {}

    def fake_search(query, max_results):
        calls["query"] = query
        calls["max_results"] = max_results
        return [
            {
                "text": "Arsenal posted training photos.",
                "url": "https://x.com/arsenal/status/1",
                "author": {"username": "Arsenal"},
                "created_at": "2026-05-31T10:00:00Z",
            }
        ]

    service = XCapabilityService(search_posts_backend=fake_search)

    result = service.search_posts({"query": "Arsenal", "max_results": 3})

    assert calls == {"query": "Arsenal", "max_results": 3}
    assert result["action"] == "x.search_posts"
    assert result["items"][0]["url"] == "https://x.com/arsenal/status/1"
    assert result["items"][0]["handle"] == "Arsenal"


def test_x_service_publish_post_requires_confirm_and_enabled_gate():
    service = XCapabilityService(post_backend=lambda text: {"id": "1", "text": text}, allow_posts=False)

    try:
        service.publish_post({"text": "hello", "confirm": True})
    except ToolPermissionError as exc:
        assert "X_TOOL_ALLOW_POSTS=true" in str(exc)
    else:
        raise AssertionError("publish_post should require the posts env gate")

    service = XCapabilityService(post_backend=lambda text: {"id": "1", "text": text}, allow_posts=True)

    try:
        service.publish_post({"text": "hello"})
    except ToolPermissionError as exc:
        assert "confirm=True" in str(exc)
    else:
        raise AssertionError("publish_post should require confirm=True")


def test_x_service_registers_capabilities_with_tool_registry():
    service = XCapabilityService(search_posts_backend=lambda query, max_results: [])
    registry = service.build_registry()

    assert "x.search_posts" in registry.names()
    assert "x.publish_post" in registry.names()
    assert registry.get("x.search_posts").stream_label == "Searched X"
