"""Personal liked-video requests must read the account rather than public tutorials."""
import pytest

from agent.agents.live_dispatcher import LiveAgentDispatcher
from agent.agents.youtube import YoutubeAgent
from agent.master.state import MasterThreadStateStore
from agent.profiles import AgentCatalog, builtin_profiles
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from delegation_turns import turn


@pytest.mark.parametrize("query", [
    "what is in my liked videos",
    "what is in my liked vidoes",
    "what are my liked youtube videos",
    "what videos have I liked?",
    "show my recently liked YT videos",
])
@pytest.mark.parametrize("selected", [False, True])
def test_liked_request_reaches_account_capability_without_public_search(tmp_path, query, selected):
    def public_search(*_args):
        pytest.fail("A personal liked-video request reached public YouTube search")

    service = YoutubeCapabilityService(search_backend=public_search, account_backend=lambda: {"connected": True},
        liked_videos_backend=lambda _limit: [{"video_id": "abc123XYZ09", "title": "Saved account video"}])
    agent = YoutubeAgent(youtube_service=service)
    catalog = AgentCatalog(profile_dir=tmp_path / "profiles",
        builtins={"YoutubeAgent": builtin_profiles()["YoutubeAgent"]}, executors={"YoutubeAgent": agent})
    state = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    if selected:
        state.set_active_agent("liked-request", "YoutubeAgent", selected=True)
    dispatcher = LiveAgentDispatcher(agent_catalog=catalog, state_store=state)
    result = turn(dispatcher, "YoutubeAgent", query, "liked-request")
    assert result is not None
    assert result.status == "answered"
    assert "Saved account video" in result.answer
    assert result.agent_name == "YoutubeAgent"
    assert "web_search" not in result.tools


def test_public_liked_video_tutorial_remains_search(tmp_path):
    calls = []
    service = YoutubeCapabilityService(search_backend=lambda query, _limit: calls.append(query) or [],
        liked_videos_backend=lambda _limit: pytest.fail("A public tutorial read the private account"))
    agent = YoutubeAgent(youtube_service=service)
    agent.answer("How to find liked videos on YouTube")
    assert calls == ["How to find liked videos on YouTube"]


def test_liked_reply_displays_every_video_it_claims_to_show(tmp_path):
    service = YoutubeCapabilityService(account_backend=lambda: {"connected": True},
        liked_videos_backend=lambda limit: [
            {"video_id": f"video{index:06d}", "title": f"Saved video {index}", "channel": "Creator"}
            for index in range(1, limit + 1)
        ])
    response = YoutubeAgent(youtube_service=service).answer("what is in my liked vidoes")
    assert "20" in response.summary
    for index in range(1, 21):
        assert f"Saved video {index}]" in response.summary
    assert response.summary.count("https://www.youtube.com/watch?v=") == 20
    assert "recent" in response.summary.lower()


@pytest.mark.parametrize("query", [
    "how many channels am I subscribed to?",
    "how many YouTube channels have I subscribed to?",
    "how many subscriptions do I have?",
    "how many subscribes i have subscried to",
    "how many channels have I subscribed to on yt?",
    "what is my subscription count?",
])
def test_subscription_count_reads_entire_account_and_answers_with_count(tmp_path, query):
    service = YoutubeCapabilityService(account_backend=lambda: {"connected": True},
        search_backend=lambda *_args: pytest.fail("A personal subscription count reached public search"),
        subscriptions_backend=lambda: [
            {"channel_id": f"UC-{index}", "title": f"Channel {index}"} for index in range(137)
        ])
    agent = YoutubeAgent(youtube_service=service)
    assert agent.can_handle(query)
    catalog = AgentCatalog(profile_dir=tmp_path / "profiles",
        builtins={"YoutubeAgent": builtin_profiles()["YoutubeAgent"]}, executors={"YoutubeAgent": agent})
    state = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    state.set_active_agent("count-request", "YoutubeAgent", selected=True)
    result = turn(LiveAgentDispatcher(agent_catalog=catalog, state_store=state), "YoutubeAgent",
                  query, "count-request")
    assert result.status == "answered"
    assert result.answer == "You're subscribed to 137 YouTube channels."


def test_subscription_count_marks_takeout_count_as_a_snapshot(tmp_path):
    service = YoutubeCapabilityService(search_backend=lambda *_args: pytest.fail("Snapshot count reached public search"),
        account_backend=lambda: {"connected": False},
        takeout_library_backend=lambda *_args: {"available": True, "provider": "takeout", "total": 137,
            "items": [{"channel_id": "UC-one", "title": "Channel One"}]})
    result = YoutubeAgent(youtube_service=service).answer("how many subscriptions do I have?")
    assert result.status == "answered"
    assert "137" in result.summary and "snapshot" in result.summary.lower()
    assert "Channel One" not in result.summary


def test_youtube_chat_formatting_retains_account_links_but_removes_reference_links():
    from agent.api import _clean_answer_body

    text = "Here are your 2 recent liked videos:\n\n1. [First](https://www.youtube.com/watch?v=abc123XYZ09)\n2. [Second](https://www.youtube.com/watch?v=video000002)\n[Other](https://example.com/)\n[Fake](https://www.youtube.com.evil.test/watch?v=abc123XYZ09)\n[1]"
    cleaned = _clean_answer_body(text, preserve_youtube_links=True)
    assert cleaned.count("https://www.youtube.com/watch?v=") == 2
    assert "example.com" not in cleaned and "evil.test" not in cleaned
    assert "[1]" not in cleaned
    # Ordinary answers preserve Markdown and citations; account-result links
    # use the specialist-only filtering above.
    assert _clean_answer_body(text) == text
