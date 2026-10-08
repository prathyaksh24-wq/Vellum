"""Account requests preserve the requested entity, quantity and evidence boundary."""
import re

import pytest

from agent.agents.youtube import YoutubeAgent
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


def liked_service(tmp_path, *, unique=15):
    return YoutubeCapabilityService(vault_root=tmp_path,
        account_backend=lambda: {"connected": True},
        search_backend=lambda *_args: pytest.fail("A personal request reached public search"),
        liked_videos_backend=lambda limit: [
            {"video_id": f"video{index:06d}", "title": f"Liked title {index}",
             "channel_id": f"UC-{index % unique}", "channel": f"Creator {index % unique}"}
            for index in range(limit)
        ])


def test_exact_ten_channels_request_returns_ten_distinct_names_without_video_titles(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path))
    response = agent.answer("name any 10 channels from my liked videos")
    assert response.status == "answered"
    assert "Liked title" not in response.summary
    names = re.findall(r"(?m)^\d+\. (.+)$", response.summary)
    assert len(names) == len(set(names)) == 10
    assert all("Creator" in name for name in names)


def test_requested_video_count_is_respected(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path))
    response = agent.answer("show just 3 of my liked videos")
    assert len(re.findall(r"(?m)^\d+\. ", response.summary)) == 3


def test_channels_request_reports_insufficient_distinct_channels_without_padding(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path, unique=3))
    response = agent.answer("name any 10 channels from my liked videos")
    assert "Liked title" not in response.summary
    assert len(re.findall(r"(?m)^\d+\. ", response.summary)) == 3
    assert "only 3" in response.summary.lower()
    assert "recent" in response.summary.lower()


def test_second_video_link_uses_the_displayed_order(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path))
    first = agent.answer_with_context("show just 3 of my liked videos", {})
    context = agent.thread_context(first, {})
    response = agent.answer_with_context("give me the link to the second video", context)
    assert response.status == "answered"
    assert "https://www.youtube.com/watch?v=video000001" in response.summary
    assert "video000000" not in response.summary and "video000002" not in response.summary


def test_missing_previous_list_explains_the_failure_without_search(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path))
    assert agent.can_handle("give me the link to the second video")
    response = agent.answer_with_context("give me the link to the second video", {})
    assert response.status == "needs_fetch"
    assert "list" in response.summary.lower()
    assert "this chat" in response.summary.lower()


def test_model_plan_controls_projection_count_and_creator_filter(tmp_path):
    calls = []
    def planner(query, context):
        calls.append(query)
        return {"source":"liked", "view":"videos", "limit":2, "creator":"Creator 3", "names_only":True}
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path), planner=planner)
    result = agent.answer("Pick a pair of uploads I enjoyed by that creator; titles alone please")
    assert len(calls) == 1
    assert len(re.findall(r"(?m)^\d+\. ", result.summary)) == 2
    assert "Liked title 3" in result.summary and "Liked title 18" in result.summary
    assert "watch?v=" not in result.summary


@pytest.mark.parametrize("error, explanation", [
    (RuntimeError("YouTube quota is temporarily exhausted"), "quota"),
    (RuntimeError("YouTube authorization is invalid or insufficient"), "authorization"),
    (RuntimeError("YouTube request is unreachable"), "could not be reached"),
])
def test_account_failures_explain_reason_without_public_search(tmp_path, error, explanation):
    def failed(_limit):
        raise error
    service = liked_service(tmp_path)
    service.liked_videos_backend = failed
    result = YoutubeAgent(vault_root=tmp_path, youtube_service=service).answer("name 10 channels from my liked videos")
    assert result.status == "error"
    assert explanation in result.summary.lower()


def test_invalid_model_plan_fails_honestly_without_reading_or_searching(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path),
        planner=lambda *_args: {"source":"invented", "view":"channels", "limit":10})
    result = agent.answer("name any 10 channels from my liked videos")
    assert result.status == "error"
    assert "interpret" in result.summary.lower()


def test_account_request_interpreter_uses_local_route_and_validates_output():
    import json
    from types import SimpleNamespace
    from agent.agents.youtube_synthesis import LocalYoutubeAccountPlanner
    calls = []
    class Model:
        def invoke(self, messages, **kwargs):
            calls.append((messages, kwargs))
            assert kwargs["request_timeout"] <= 60
            assert "Private creator" not in messages[-1].content
            return SimpleNamespace(content=json.dumps({"source":"liked", "view":"channels", "limit":10, "names_only":True}))
    planner = LocalYoutubeAccountPlanner(model_resolver=lambda:"ollama/gemma4:12b", model_factory=lambda *_args:Model())
    plan = planner("name ten creators from videos I've liked", {"account_items":[{"title":"Private creator"}]})
    assert plan.view == "channels" and plan.limit == 10
    assert len(calls) == 1
    cloud = LocalYoutubeAccountPlanner(model_resolver=lambda:"openai/gpt-4o", model_factory=lambda *_args:pytest.fail("Cloud route called"))
    with pytest.raises(ValueError, match="local model"):
        cloud("name ten creators from videos I've liked", {})


def test_out_of_range_reference_retains_order_and_explains_missing_item(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path))
    first = agent.answer_with_context("show just 3 of my liked videos", {})
    response = agent.answer_with_context("give me the link to the fifth video", agent.thread_context(first, {}))
    assert response.status == "needs_fetch"
    assert "3 items" in response.summary and "item 5" in response.summary


def test_channel_list_is_not_silently_treated_as_a_video_list(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path))
    first = agent.answer_with_context("name any 10 channels from my liked videos", {})
    response = agent.answer_with_context("give me the link to the second video", agent.thread_context(first, {}))
    assert response.status == "needs_fetch" and "contains channels" in response.summary


def test_distinct_channel_count_has_explicit_recent_coverage(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path, unique=3))
    response = agent.answer("how many distinct channels are in my liked videos?")
    assert "3 distinct channels" in response.summary and "50 recent liked videos" in response.summary


def test_profile_selected_cloud_model_is_rejected_before_account_interpretation():
    from agent.agents.youtube_synthesis import LocalYoutubeAccountPlanner
    execution_module = pytest.importorskip("agent.profiles.execution")
    execution = execution_module.ProfileExecution(profile_id="YoutubeAgent", model_id="openai/gpt-4o",
        reasoning_mode=None, instructions="", skills="", memory={}, context="", thread_id="test")
    planner = LocalYoutubeAccountPlanner(model_resolver=lambda:"ollama/gemma4:12b",
        model_factory=lambda *_args:pytest.fail("Cloud route called"))
    with execution_module.profile_execution(execution), pytest.raises(ValueError, match="local model"):
        planner("name ten creators from videos I've liked", {})


@pytest.mark.parametrize("query", ["link to the 0th video", "link to the 51st video"])
def test_invalid_ordinals_are_reported_without_search(tmp_path, query):
    response = YoutubeAgent(vault_root=tmp_path, youtube_service=liked_service(tmp_path)).answer(query)
    assert response.status == "needs_fetch"
