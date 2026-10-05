"""Personal liked-video requests must read the account rather than public tutorials."""
import pytest

from agent.agents.live_dispatcher import LiveAgentDispatcher
from agent.agents.youtube import YoutubeAgent
from agent.master.state import MasterThreadStateStore
from agent.profiles import AgentCatalog, builtin_profiles
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


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

    service = YoutubeCapabilityService(vault_root=tmp_path,
        search_backend=public_search, account_backend=lambda: {"connected": True},
        liked_videos_backend=lambda _limit: [{"video_id": "abc123XYZ09", "title": "Saved account video"}])
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=service)
    catalog = AgentCatalog(profile_dir=tmp_path / "profiles",
        builtins={"YoutubeAgent": builtin_profiles()["YoutubeAgent"]}, executors={"YoutubeAgent": agent})
    state = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    if selected:
        state.set_active_agent("liked-request", "YoutubeAgent", selected=True)
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state)
    result = dispatcher.maybe_handle(query, thread_id="liked-request")
    assert result is not None
    assert result.status == "answered"
    assert "Saved account video" in result.answer
    assert result.agent_name == "YoutubeAgent"
    assert "web_search" not in result.tools


def test_public_liked_video_tutorial_remains_search(tmp_path):
    calls = []
    service = YoutubeCapabilityService(vault_root=tmp_path,
        search_backend=lambda query, _limit: calls.append(query) or [],
        liked_videos_backend=lambda _limit: pytest.fail("A public tutorial read the private account"))
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=service)
    agent.answer("How to find liked videos on YouTube")
    assert calls == ["How to find liked videos on YouTube"]
