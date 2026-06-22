import json
from types import SimpleNamespace

from agent.tools import x as x_tool


class AgentReachUnavailable:
    def available(self):
        return False


def test_search_uses_xai_search_client(monkeypatch):
    seen = {}

    class FakeSearchClient:
        @staticmethod
        def search_x(**kwargs):
            seen.update(kwargs)
            return [{"id": "1", "text": "hello", "url": "https://x.com/a/status/1"}]

    monkeypatch.setattr(x_tool, "_xai_client", lambda: FakeSearchClient)
    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: AgentReachUnavailable())

    out = json.loads(x_tool.x_action.func(action="search", query="nba", max_results=3))

    assert out["action"] == "search"
    assert out["items"][0]["id"] == "1"
    assert seen["query"] == "nba"
    assert seen["max_items"] == 3
    assert seen["oauth_file"] == x_tool._xai_oauth_file()


def test_search_prefers_agent_reach_when_ready(monkeypatch):
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def search(self, query, max_results):
            calls.append((query, max_results))
            return [{"text": "agent reach result", "url": "https://x.com/a/status/1"}]

    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: FakeAgentReach())

    out = json.loads(x_tool.x_action.func(action="search", query="nba", max_results=3))

    assert out["action"] == "search"
    assert out["provider"] == "agent-reach"
    assert out["items"][0]["text"] == "agent reach result"
    assert calls == [("nba", 3)]


def test_status_reports_agent_reach_connector(monkeypatch):
    class FakeStatus:
        configured = True
        status = "ready"
        notes = "Agent-Reach X connector is ready."

        def model_dump(self):
            return {"configured": self.configured, "status": self.status, "notes": self.notes}

    class FakeAgentReach:
        def status(self):
            return FakeStatus()

        def available(self):
            return True

    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: FakeAgentReach())

    out = json.loads(x_tool.x_action.func(action="status"))

    assert out["action"] == "status"
    assert out["agent_reach"]["status"] == "ready"
    assert out["agent_reach"]["configured"] is True


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
    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: AgentReachUnavailable())

    out = json.loads(x_tool.x_action.func(action="bookmarks", max_results=5))

    assert out["action"] == "bookmarks"
    assert out["account"]["username"] == "me"
    assert out["items"][0]["text"] == "Saved"


def test_bookmarks_prefer_agent_reach_when_ready(monkeypatch):
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def bookmarks(self, max_results):
            calls.append(max_results)
            return [{"text": "Agent-Reach saved", "url": "https://x.com/a/status/1"}]

    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=False))
    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: FakeAgentReach())

    out = json.loads(x_tool.x_action.func(action="bookmarks", max_results=4))

    assert out["provider"] == "agent-reach"
    assert out["items"][0]["text"] == "Agent-Reach saved"
    assert calls == [4]


def test_agent_reach_read_actions(monkeypatch):
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def timeline(self, max_results):
            calls.append(("timeline", max_results))
            return [{"text": "Timeline"}]

        def likes(self, handle, max_results):
            calls.append(("likes", handle, max_results))
            return [{"text": "Liked"}]

        def profile(self, handle):
            calls.append(("profile", handle))
            return {"username": handle}

        def read_tweet(self, tweet_id_or_url):
            calls.append(("read", tweet_id_or_url))
            return {"text": "Tweet"}

    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=False))
    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: FakeAgentReach())

    assert json.loads(x_tool.x_action.func(action="timeline", max_results=2))["items"][0]["text"] == "Timeline"
    assert json.loads(x_tool.x_action.func(action="likes", query="@me", max_results=3))["items"][0]["text"] == "Liked"
    assert json.loads(x_tool.x_action.func(action="likes", max_results=1))["items"][0]["text"] == "Liked"
    assert json.loads(x_tool.x_action.func(action="profile", query="@openai"))["profile"]["username"] == "openai"
    assert json.loads(x_tool.x_action.func(action="read_tweet", query="123"))["tweet"]["text"] == "Tweet"
    assert calls == [("timeline", 2), ("likes", "me", 3), ("likes", "me", 1), ("profile", "openai"), ("read", "123")]


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
    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: AgentReachUnavailable())

    out = json.loads(x_tool.x_action.func(action="post", text="hello", confirm=True))

    assert out["action"] == "post"
    assert out["tweet"]["id"] == "99"


def test_post_when_allowed_prefers_agent_reach(monkeypatch):
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def post_tweet(self, text):
            calls.append(text)
            return {"id": "agent-reach-99", "text": text}

    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=True))
    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: FakeAgentReach())

    out = json.loads(x_tool.x_action.func(action="post", text="hello", confirm=True))

    assert out["action"] == "post"
    assert out["provider"] == "agent-reach"
    assert out["tweet"]["id"] == "agent-reach-99"
    assert calls == ["hello"]


def test_agent_reach_write_actions_require_confirm(monkeypatch):
    class FakeAgentReach:
        def available(self):
            return True

        def delete(self, tweet_id):
            return {"deleted": tweet_id}

    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=True))
    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: FakeAgentReach())

    no_confirm = x_tool.x_action.func(action="delete", query="123", confirm=False)

    assert "confirm=True" in no_confirm


def test_agent_reach_confirmed_write_actions(monkeypatch):
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def reply(self, tweet_id, text):
            calls.append(("reply", tweet_id, text))
            return {"ok": True}

        def like(self, tweet_id):
            calls.append(("like", tweet_id))
            return {"ok": True}

        def repost(self, tweet_id):
            calls.append(("repost", tweet_id))
            return {"ok": True}

        def delete(self, tweet_id):
            calls.append(("delete", tweet_id))
            return {"ok": True}

    monkeypatch.setattr(x_tool, "get_settings", lambda: SimpleNamespace(x_tool_allow_private_reads=True, x_tool_allow_posts=True))
    monkeypatch.setattr(x_tool, "_agent_reach_provider", lambda: FakeAgentReach())

    assert json.loads(x_tool.x_action.func(action="reply", query="123", text="hello", confirm=True))["provider"] == "agent-reach"
    assert json.loads(x_tool.x_action.func(action="like", query="123", confirm=True))["provider"] == "agent-reach"
    assert json.loads(x_tool.x_action.func(action="repost", query="https://x.com/openai/status/1234567890123456789", confirm=True))["provider"] == "agent-reach"
    assert json.loads(x_tool.x_action.func(action="delete", query="https://twitter.com/openai/status/1234567890123456789?s=20", confirm=True))["provider"] == "agent-reach"
    assert calls == [
        ("reply", "123", "hello"),
        ("like", "123"),
        ("repost", "1234567890123456789"),
        ("delete", "1234567890123456789"),
    ]


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
