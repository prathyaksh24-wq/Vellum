import subprocess
import time
from types import SimpleNamespace

import pytest

from agent.agents.books_synthesis import RoutedBooksSynthesizer
from agent.agents.x_agent import XAgent
from agent.agents.youtube import YoutubeAgent
from agent.tools.capabilities.agent_reach_x_provider import AgentReachXProvider, AgentReachCommandError
from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
from agent.contracts.music import MusicPlan
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from test_music_agent import fixture_agent
from test_youtube_intelligence_capability import _snapshot


def test_x_does_not_claim_published_when_cli_returns_no_post_receipt(tmp_path):
    provider = AgentReachXProvider(runner=lambda args, **kw: subprocess.CompletedProcess(args, 0, '{"success":true}', ''))
    provider.available = lambda: True
    agent = XAgent(tmp_path, x_service=XCapabilityService(agent_reach_provider=provider, allow_posts=True))
    result = agent.execute_action_request({"action":"x.publish_post", "payload":{"text":"A requested post."}})
    assert result.status == "error"
    assert "Posted to X" not in result.summary
    assert "unconfirmed" in result.summary


def test_youtube_my_data_question_reads_local_evidence_not_public_how_to(tmp_path):
    calls = []
    service = YoutubeCapabilityService(vault_root=tmp_path,
        search_backend=lambda query, limit: calls.append(query) or [{"title":"How to start YouTube"}],
        personal_context_backend=_snapshot)
    result = YoutubeAgent(tmp_path, youtube_service=service).answer("what can u tell me about my youtube data")
    assert calls == []
    assert "Sidemen" in result.summary
    assert "local Knowledge Core" in result.analysis


@pytest.mark.parametrize("query", ["play a song from my liked songs playlist on shuffle", "by a song inside my liked songs playlist"])
def test_liked_songs_source_overrides_previous_failed_song_search(query):
    agent, _, calls = fixture_agent(library={"items":[{"track":{"uri":"spotify:track:liked"}}],"total":1})
    assert agent.can_handle(query)
    result = agent.answer_with_context(query, {"last_plan":{"operation":"play_song","provider":"spotify","query":"old wrong song","artist":""},"at":time.time()})
    assert result.status == "answered"
    assert calls[0][0] == "spotify_library"
    assert not any(name in {"spotify_search", "spotify_playlists"} for name, _ in calls)


def test_book_synthesis_requests_bounded_json_generation():
    calls = []
    class Model:
        def invoke(self, messages, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content='{"answer":"Source summary","claims":[],"status":"abstained"}')
    synthesis = RoutedBooksSynthesizer(model_id="ollama/gemma4:12b", model_factory=lambda *a, **k:Model())
    synthesis("what have u lerant from the meditations book?", [{"evidence_id":"source-1","text":"A source passage."}])
    assert calls[0].get("response_format") == {"type":"json_object"}
    assert 0 < calls[0].get("request_timeout", 0) <= 60


def test_book_source_labels_resolve_only_exact_known_evidence_ids():
    class Model:
        def invoke(self, messages, **kwargs):
            assert '"evidence_id":"passage-1"' in messages[1].content
            return SimpleNamespace(content='{"claims":[{"evidence_ids":["passage-1","invented-id"],"conflicting_evidence_ids":[]}],"status":"partial"}')
    synthesis = RoutedBooksSynthesizer(model_id="ollama/gemma4:12b", model_factory=lambda *a, **k:Model())
    result = synthesis("What does the book say?", [{"evidence_id":"canonical-long-id","text":"Source passage."}])
    assert result["claims"][0]["evidence_ids"] == ["canonical-long-id","invented-id"]


def test_reported_book_question_is_routed_to_books_agent():
    from agent.agents.books import BooksAgent
    from agent.tools.registry import ToolRegistry
    assert BooksAgent(tool_registry=ToolRegistry()).can_handle("what have u lerant from the meditations book?")


@pytest.mark.parametrize("query", ["nah play the original track", "play that song nby the original artist"])
def test_original_track_followup_preserves_title_without_slow_model_planning(query):
    def forbidden(*args):
        raise AssertionError("A contextual version correction must not start a second model plan")
    agent, _, calls = fixture_agent(planner=forbidden, tracks=[
        {"name":"Rain Over Me","uri":"spotify:track:cover","artists":[{"name":"XTC Planet"}]},
        {"name":"Rain Over Me","uri":"spotify:track:original","artists":[{"name":"Pitbull"},{"name":"Marc Anthony"}]},
    ])
    context={"last_plan":{"operation":"play_song","provider":"spotify","query":"Rain Over Me","artist":"XTC Planet"},"at":time.time()}
    assert agent.can_handle_with_context(query, context)
    result=agent.answer_with_context(query, context)
    assert result.status == "needs_fetch"
    assert "Pitbull" in result.summary
    assert calls[0][0] == "spotify_search"
    assert "Rain Over Me" in calls[0][1]["query"]
    assert "original track" not in calls[0][1]["query"]
    assert not any(name == "spotify_playback" for name,_ in calls)


def test_original_correction_cannot_silently_replay_single_cover():
    agent, _, calls = fixture_agent(tracks=[{"name":"Rain Over Me", "uri":"spotify:track:cover", "artists":[{"name":"XTC Planet"}]}])
    previous = agent.answer("play Rain Over Me")
    context = agent.thread_context(previous, {})
    current = agent.answer_with_context("what song is currently playing?", context)
    assert current.status == "answered"
    context = agent.thread_context(current, context)
    calls.clear()
    result = agent.answer_with_context("play the original song", context)
    assert result.status == "needs_fetch"
    assert result.structured_payload["music_plan"]["query"] == "Rain Over Me"
    assert not any(name == "spotify_playback" for name, _ in calls)


def test_original_without_fresh_context_asks_for_title_without_model_call():
    agent, _, calls = fixture_agent(planner=lambda *_:pytest.fail("Must not plan a pronoun without its antecedent"))
    assert agent.can_handle("play the original song")
    result = agent.answer_with_context("play the original song", {"at":time.time()-3600})
    assert result.status == "needs_fetch"
    assert "Which song" in result.summary
    assert calls == []


def test_current_song_reads_provider_state_and_artist():
    agent, _, calls = fixture_agent()
    assert agent.can_handle("what song is currently playing?")
    result = agent.answer("what song is currently playing?")
    assert calls == [("spotify_playback", {"action":"get_state"})]
    assert "Nothing is playing" in result.summary
    state = {"item":{"name":"Rain Over Me", "artists":[{"name":"Pitbull"}]}}
    assert SpotifyCapabilityService().execute(MusicPlan(operation="current"), lambda *_:state) == "Currently playing Rain Over Me by Pitbull."


def test_featured_artist_credit_matches_title_but_remix_does_not():
    agent, _, calls = fixture_agent(tracks=[
        {"name":"Rain Over Me (feat. Marc Anthony)","uri":"spotify:track:original","artists":[{"name":"Pitbull"},{"name":"Marc Anthony"}]},
        {"name":"Rain Over Me (Technoposse Remix Edit)","uri":"spotify:track:remix","artists":[{"name":"Love Empire"}]},
    ])
    result = agent.answer("play Rain Over Me")
    assert result.status == "answered"
    assert "Pitbull" in result.summary
    assert calls[0][1]["query"] == 'track:"Rain Over Me"'
    assert calls[-1][1]["uris"] == ["spotify:track:original"]


def test_featured_artist_version_still_requires_choice_between_different_artists():
    agent, _, calls = fixture_agent(tracks=[
        {"name":"Rain Over Me (feat. Marc Anthony)","uri":"spotify:track:original","artists":[{"name":"Pitbull"}]},
        {"name":"Rain Over Me","uri":"spotify:track:cover","artists":[{"name":"XTC Planet"}]},
    ])
    result=agent.answer("play Rain Over Me")
    assert result.status == "needs_fetch"
    assert "Pitbull" in result.summary
    assert not any(name == "spotify_playback" for name, _ in calls)


def test_one_artist_name_selects_a_collaboration_after_original_version_question():
    agent, _, calls = fixture_agent(tracks=[
        {"name":"Rain Over Me (feat. Marc Anthony)","uri":"spotify:track:original","artists":[{"name":"Pitbull"},{"name":"Marc Anthony"}]},
        {"name":"Rain Over Me","uri":"spotify:track:other","artists":[{"name":"Bhaskar"}]},
    ])
    response = agent.answer("play Rain Over Me")
    context = agent.thread_context(response, {})
    response = agent.answer_with_context("nah play the original track", context)
    context = agent.thread_context(response, context)
    assert agent.can_handle_with_context("Pitbull", context)
    response = agent.answer_with_context("Pitbull", context)
    assert response.status == "answered"
    assert "Pitbull" in response.summary
    assert calls[-1][1]["uris"] == ["spotify:track:original"]


def test_x_post_readback_failure_is_uncertain_and_does_not_repeat_write():
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{"id":"123"}' if args[1] == "post" else '{}', '')
    provider = AgentReachXProvider(runner=runner)
    with pytest.raises(AgentReachCommandError, match="Publication is unconfirmed"):
        provider.post_tweet("Requested text")
    assert [args[1] for args in calls] == ["post", "tweet"]


def test_x_semantic_error_with_zero_exit_status_is_not_success():
    provider = AgentReachXProvider(runner=lambda args, **kw:subprocess.CompletedProcess(args, 0, '{"ok":false,"error":{"message":"Write denied"}}', ''))
    with pytest.raises(AgentReachCommandError, match="Write denied"):
        provider.like("123")


def test_x_custom_backend_missing_receipt_does_not_return_success():
    service = XCapabilityService(post_backend=lambda _: {}, allow_posts=True)
    with pytest.raises(Exception, match="did not confirm publication"):
        service.publish_post({"text":"Requested text", "confirm":True})
