import json
from types import SimpleNamespace

from agent.tools import x as x_tool


def test_search_uses_xai_search_client(monkeypatch):
    seen = {}

    class FakeSearchClient:
        @staticmethod
        def search_x(**kwargs):
            seen.update(kwargs)
            return [{"id": "1", "text": "hello", "url": "https://x.com/a/status/1"}]

    monkeypatch.setattr(x_tool, "_xai_client", lambda: FakeSearchClient)

    out = json.loads(x_tool.x_action.func(action="search", query="nba", max_results=3))

    assert out["action"] == "search"
    assert out["items"][0]["id"] == "1"
    assert seen["query"] == "nba"
    assert seen["max_items"] == 3
    assert seen["oauth_file"] == x_tool._xai_oauth_file()


def test_bookmarks_requires_private_read_gate(monkeypatch):
    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=False, x_tool_allow_posts=False))

    result = x_tool.x_action.func(action="bookmarks")

    assert "X_TOOL_ALLOW_PRIVATE_READS=true" in result


def test_bookmarks_fetches_me_then_bookmarks_when_allowed(monkeypatch):
    class FakeClient:
        @staticmethod
        def get_me(**_kwargs):
            return {"data": {"id": "42", "username": "me"}}

        @staticmethod
        def get_bookmarks(**kwargs):
            assert kwargs["user_id"] == "42"
            return {"data": [{"id": "7", "text": "Saved"}]}

    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=False))
    monkeypatch.setattr(x_tool, "_x_api_client", lambda: FakeClient)

    out = json.loads(x_tool.x_action.func(action="bookmarks", max_results=5))

    assert out["action"] == "bookmarks"
    assert out["account"]["username"] == "me"
    assert out["items"][0]["text"] == "Saved"


def test_post_requires_confirm_and_write_gate(monkeypatch):
    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=False))

    no_confirm = x_tool.x_action.func(action="post", text="hello", confirm=False)
    no_gate = x_tool.x_action.func(action="post", text="hello", confirm=True)

    assert "confirm=True" in no_confirm
    assert "X_TOOL_ALLOW_POSTS=true" in no_gate


def test_post_when_allowed_calls_client(monkeypatch):
    class FakeClient:
        @staticmethod
        def post_tweet(**kwargs):
            assert kwargs["text"] == "hello"
            return {"data": {"id": "99", "text": "hello"}}

    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=True))
    monkeypatch.setattr(x_tool, "_x_api_client", lambda: FakeClient)

    out = json.loads(x_tool.x_action.func(action="post", text="hello", confirm=True))

    assert out["action"] == "post"
    assert out["tweet"]["id"] == "99"


def test_post_image_when_allowed_generates_uploads_and_posts(monkeypatch, tmp_path):
    calls = {}

    class FakeClient:
        @staticmethod
        def upload_media(**kwargs):
            calls["upload"] = kwargs
            return {"data": {"id": "media-1"}}

        @staticmethod
        def post_tweet(**kwargs):
            calls["post"] = kwargs
            return {"data": {"id": "99", "text": "hello"}}

    class FakeImageClient:
        @staticmethod
        def generate_image_file(**kwargs):
            calls["image"] = kwargs
            image_path = tmp_path / "generated.png"
            image_path.write_bytes(b"fake-png")
            return {"path": str(image_path), "model": "fake-image-model"}

    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=True))
    monkeypatch.setattr(x_tool, "_x_api_client", lambda: FakeClient)
    monkeypatch.setattr(x_tool, "_image_client", lambda: FakeImageClient)

    out = json.loads(
        x_tool.x_action.func(
            action="post_image",
            text="hello",
            query="clean product photo",
            confirm=True,
        )
    )

    assert out["action"] == "post_image"
    assert out["tweet"]["id"] == "99"
    assert calls["image"]["prompt"] == "clean product photo"
    assert calls["upload"]["media_path"].name == "generated.png"
    assert calls["post"]["media_ids"] == ["media-1"]
    assert calls["post"]["made_with_ai"] is True
