from datetime import datetime
from types import SimpleNamespace

from agent.tools.capabilities import x_service
from agent.tools.capabilities.agent_reach_x_provider import AgentReachCommandError
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.registry import ToolPermissionError


class AgentReachUnavailable:
    def available(self):
        return False


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

    service = XCapabilityService(search_posts_backend=fake_search, agent_reach_provider=AgentReachUnavailable())

    result = service.search_posts({"query": "Arsenal", "max_results": 3})

    assert calls == {"query": "Arsenal", "max_results": 3}
    assert result["action"] == "x.search_posts"
    assert result["items"][0]["url"] == "https://x.com/arsenal/status/1"
    assert result["items"][0]["handle"] == "Arsenal"


def test_x_service_default_search_backend_passes_window_to_script(monkeypatch):
    calls = {}

    def fake_search_x(**kwargs):
        calls.update(kwargs)
        return [
            {
                "body": "Training photos posted.",
                "x_url": "https://x.com/arsenal/status/2",
                "handle": "arsenal",
                "date": "2026-05-31T10:00:00Z",
            }
        ]

    monkeypatch.setattr(x_service, "_load_script", lambda name: SimpleNamespace(search_x=fake_search_x))

    result = XCapabilityService(search_posts_backend=None, allow_posts=False, agent_reach_provider=AgentReachUnavailable()).search_posts(
        {"query": "Arsenal", "max_results": 5}
    )

    assert calls["query"] == "Arsenal"
    assert calls["max_items"] == 5
    assert calls["oauth_file"] == x_service.XCapabilityService._xai_oauth_file()
    assert isinstance(calls["start"], datetime)
    assert isinstance(calls["end"], datetime)
    assert calls["start"] < calls["end"]
    assert result["items"][0]["url"] == "https://x.com/arsenal/status/2"


def test_x_service_prefers_agent_reach_for_search_when_ready():
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def search(self, query, max_results):
            calls.append((query, max_results))
            return [{"text": "Agent-Reach result", "url": "https://x.com/a/status/1", "handle": "a"}]

    service = XCapabilityService(
        search_posts_backend=lambda query, max_results: [{"text": "xai fallback"}],
        agent_reach_provider=FakeAgentReach(),
    )

    result = service.search_posts({"query": "latest x posts", "max_results": 4})

    assert calls == [("latest x posts", 4)]
    assert result["provider"] == "agent-reach"
    assert result["items"][0]["text"] == "Agent-Reach result"


def test_x_service_falls_back_to_xai_search_when_agent_reach_unavailable():
    calls = []

    class FakeAgentReach:
        def available(self):
            return False

        def search(self, query, max_results):
            raise AssertionError("unavailable provider should not be called")

    service = XCapabilityService(
        search_posts_backend=lambda query, max_results: calls.append((query, max_results)) or [
            {"text": "xAI fallback", "url": "https://x.com/fallback/status/1"}
        ],
        agent_reach_provider=FakeAgentReach(),
    )

    result = service.search_posts({"query": "latest x posts", "max_results": 2})

    assert calls == [("latest x posts", 2)]
    assert result["provider"] == "xai"
    assert result["items"][0]["text"] == "xAI fallback"


def test_x_service_falls_back_to_xai_search_when_agent_reach_command_fails():
    class FakeAgentReach:
        def available(self):
            return True

        def search(self, query, max_results):
            raise AgentReachCommandError("twitter-cli failed")

    service = XCapabilityService(
        search_posts_backend=lambda query, max_results: [
            {"text": "xAI fallback", "url": "https://x.com/fallback/status/1"}
        ],
        agent_reach_provider=FakeAgentReach(),
    )

    result = service.search_posts({"query": "latest x posts", "max_results": 2})

    assert result["provider"] == "xai"
    assert "twitter-cli failed" in result["fallback_reason"]


def test_x_service_prefers_agent_reach_for_text_post_when_ready_and_confirmed():
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def post_tweet(self, text):
            calls.append(text)
            return {"id": "agent-reach-1", "text": text}

    service = XCapabilityService(
        post_backend=lambda text: {"id": "xapi-1", "text": text},
        agent_reach_provider=FakeAgentReach(),
        allow_posts=True,
    )

    result = service.publish_post({"text": "hello", "confirm": True})

    assert calls == ["hello"]
    assert result["provider"] == "agent-reach"
    assert result["tweet"]["id"] == "agent-reach-1"


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


def test_x_service_publish_post_uses_settings_when_allow_posts_omitted(monkeypatch):
    monkeypatch.setattr(x_service, "get_settings", lambda: SimpleNamespace(x_tool_allow_posts=True))
    service = XCapabilityService(post_backend=lambda text: {"id": "1", "text": text}, agent_reach_provider=AgentReachUnavailable())

    result = service.publish_post({"text": "hello", "confirm": True})

    assert result == {"action": "x.publish_post", "tweet": {"id": "1", "text": "hello"}}


def test_x_service_publish_post_with_generated_image_uploads_media():
    calls = {}

    def fake_image(prompt):
        calls["image"] = prompt
        return {"path": "D:/tmp/x-image.png", "model": "fake-image-model"}

    def fake_upload(path):
        calls["upload"] = path
        return {"id": "media-1"}

    def fake_post(text, media_ids=None, made_with_ai=False):
        calls["post"] = {"text": text, "media_ids": media_ids, "made_with_ai": made_with_ai}
        return {"id": "tweet-1", "text": text}

    service = XCapabilityService(
        post_backend=fake_post,
        image_backend=fake_image,
        media_upload_backend=fake_upload,
        allow_posts=True,
    )

    result = service.publish_post_with_media(
        {"text": "hello", "image_prompt": "clean product photo", "confirm": True}
    )

    assert result["action"] == "x.publish_post_with_media"
    assert result["tweet"]["id"] == "tweet-1"
    assert result["image"]["path"] == "D:/tmp/x-image.png"
    assert calls == {
        "image": "clean product photo",
        "upload": "D:/tmp/x-image.png",
        "post": {"text": "hello", "media_ids": ["media-1"], "made_with_ai": True},
    }


def test_x_service_private_oauth_reads_require_enabled_gate():
    service = XCapabilityService(
        account_backend=lambda: {"id": "42", "username": "vellum"},
        bookmarks_backend=lambda user_id, max_results: {"data": []},
        allow_private_reads=False,
    )

    try:
        service.account({})
    except ToolPermissionError as exc:
        assert "X_TOOL_ALLOW_PRIVATE_READS=true" in str(exc)
    else:
        raise AssertionError("account read should require private-read env gate")

    try:
        service.bookmarks({"max_results": 3})
    except ToolPermissionError as exc:
        assert "X_TOOL_ALLOW_PRIVATE_READS=true" in str(exc)
    else:
        raise AssertionError("bookmark read should require private-read env gate")


def test_x_service_account_and_bookmarks_use_oauth_backends():
    calls = {}

    def fake_account():
        calls["account"] = True
        return {"id": "42", "username": "vellum"}

    def fake_bookmarks(user_id, max_results):
        calls["bookmarks"] = {"user_id": user_id, "max_results": max_results}
        return {
            "data": [
                {"id": "1", "text": "Useful post", "url": "https://x.com/vellum/status/1"},
            ],
            "meta": {"result_count": 1},
        }

    service = XCapabilityService(
        account_backend=fake_account,
        bookmarks_backend=fake_bookmarks,
        agent_reach_provider=AgentReachUnavailable(),
        allow_private_reads=True,
    )

    account = service.account({})
    bookmarks = service.bookmarks({"max_results": 3})

    assert account == {"action": "x.account", "account": {"id": "42", "username": "vellum"}}
    assert bookmarks["items"][0]["text"] == "Useful post"
    assert bookmarks["meta"] == {"result_count": 1}
    assert calls == {"account": True, "bookmarks": {"user_id": "42", "max_results": 3}}


def test_x_service_prefers_agent_reach_for_bookmarks_timeline_likes_and_profile():
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def bookmarks(self, max_results):
            calls.append(("bookmarks", max_results))
            return [{"text": "Saved post", "url": "https://x.com/a/status/1", "handle": "a"}]

        def timeline(self, max_results):
            calls.append(("timeline", max_results))
            return [{"text": "Timeline post", "url": "https://x.com/b/status/2", "handle": "b"}]

        def likes(self, handle, max_results):
            calls.append(("likes", handle, max_results))
            return [{"text": "Liked post", "url": "https://x.com/c/status/3", "handle": "c"}]

        def profile(self, handle):
            calls.append(("profile", handle))
            return {"username": handle, "name": "Profile"}

        def read_tweet(self, tweet_id_or_url):
            calls.append(("read_tweet", tweet_id_or_url))
            return {"text": "Tweet detail", "url": "https://x.com/d/status/4", "handle": "d"}

    service = XCapabilityService(agent_reach_provider=FakeAgentReach(), allow_private_reads=True)

    assert service.bookmarks({"max_results": 4})["provider"] == "agent-reach"
    assert service.timeline({"max_results": 3})["items"][0]["text"] == "Timeline post"
    assert service.likes({"handle": "me", "max_results": 2})["items"][0]["text"] == "Liked post"
    assert service.profile({"handle": "openai"})["profile"]["username"] == "openai"
    assert service.read_tweet({"tweet_id": "4"})["tweet"]["text"] == "Tweet detail"
    assert calls == [
        ("bookmarks", 4),
        ("timeline", 3),
        ("likes", "me", 2),
        ("profile", "openai"),
        ("read_tweet", "4"),
    ]


def test_x_service_likes_defaults_to_me_for_private_reads():
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def likes(self, handle, max_results):
            calls.append((handle, max_results))
            return [{"id": "9", "text": "Liked post", "handle": "openai", "url": "https://x.com/openai/status/9"}]

    service = XCapabilityService(agent_reach_provider=FakeAgentReach(), allow_private_reads=True)

    result = service.likes({"max_results": 1})

    assert calls == [("me", 1)]
    assert result["items"][0]["url"] == "https://x.com/openai/status/9"


def test_x_service_agent_reach_write_actions_require_confirm_and_call_provider():
    calls = []

    class FakeAgentReach:
        def available(self):
            return True

        def reply(self, tweet_id_or_url, text):
            calls.append(("reply", tweet_id_or_url, text))
            return {"ok": True}

        def like(self, tweet_id_or_url):
            calls.append(("like", tweet_id_or_url))
            return {"ok": True}

        def repost(self, tweet_id_or_url):
            calls.append(("repost", tweet_id_or_url))
            return {"ok": True}

        def delete(self, tweet_id_or_url):
            calls.append(("delete", tweet_id_or_url))
            return {"ok": True}

    service = XCapabilityService(agent_reach_provider=FakeAgentReach(), allow_posts=True)

    for action in (service.reply, service.like, service.repost, service.delete):
        try:
            action({"tweet_id": "123", "text": "hello"})
        except ToolPermissionError as exc:
            assert "confirm=True" in str(exc)
        else:
            raise AssertionError("write action should require confirm=True")

    assert service.reply({"tweet_id": "123", "text": "hello", "confirm": True})["provider"] == "agent-reach"
    assert service.like({"tweet_id": "123", "confirm": True})["provider"] == "agent-reach"
    assert service.repost({"tweet_id": "123", "confirm": True})["provider"] == "agent-reach"
    assert service.delete({"tweet_id": "123", "confirm": True})["provider"] == "agent-reach"
    assert calls == [
        ("reply", "123", "hello"),
        ("like", "123"),
        ("repost", "123"),
        ("delete", "123"),
    ]


def test_x_service_registers_capabilities_with_tool_registry():
    service = XCapabilityService(search_posts_backend=lambda query, max_results: [])
    registry = service.build_registry()

    assert "x.search_posts" in registry.names()
    assert "x.timeline" in registry.names()
    assert "x.likes" in registry.names()
    assert "x.profile" in registry.names()
    assert "x.read_tweet" in registry.names()
    assert "x.reply" in registry.names()
    assert "x.like" in registry.names()
    assert "x.repost" in registry.names()
    assert "x.delete" in registry.names()
    assert "x.publish_post" in registry.names()
    assert "x.publish_post_with_media" in registry.names()
    assert "x.account" in registry.names()
    assert "x.bookmarks" in registry.names()
    assert registry.get("x.search_posts").stream_label == "Searched X"
