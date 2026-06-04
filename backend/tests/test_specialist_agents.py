from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from agent.agents.live_dispatcher import LiveAgentDispatcher
from agent.master.registry import PupilRegistry
from agent.master.state import MasterThreadStateStore
from agent.tools.capabilities.x_service import XCapabilityService
from agent.agents import (
    MemoryAgent,
    MemoryProposal,
    SpecialistResponse,
    SpecialistSource,
    SpecialistRouter,
    SportsAgent,
    XAgent,
    YoutubeAgent,
)
from agent.agents.base import (
    Freshness,
    MemoryScope,
    SourceKind,
    SpecialistStatus,
)


def test_specialist_response_defaults_are_empty_and_bounded():
    response = SpecialistResponse(
        agent="SportsAgent",
        status="answered",
        summary="Arsenal won the title.",
    )

    assert response.analysis == ""
    assert response.sources == []
    assert response.confidence == 0.0
    assert response.memory_proposals == []
    assert "answered" in get_args(SpecialistStatus)


def test_specialist_source_tracks_freshness_metadata():
    source = SpecialistSource(
        kind="api",
        title="NBA live scoreboard",
        path_or_url="https://example.com/scores",
        captured_at="2026-05-27T10:00:00Z",
        freshness="live",
    )

    assert source.kind == "api"
    assert source.captured_at == "2026-05-27T10:00:00Z"
    assert source.freshness == "live"
    assert "api" in get_args(SourceKind)
    assert "live" in get_args(Freshness)


def test_specialist_source_defaults_to_historical_without_capture_time():
    source = SpecialistSource(
        kind="vault",
        title="Sports ambient note",
        path_or_url="Vault/Library/Sports/Ambient/latest.md",
    )

    assert source.captured_at == ""
    assert source.freshness == "historical"


def test_memory_proposal_structure_and_confidence_validation():
    proposal = MemoryProposal(
        scope="sports",
        claim="User prefers strategic sports analysis over raw scoreboards.",
        evidence="Repeatedly asked for injuries, analysis, and key players.",
        confidence=0.8,
    )

    assert proposal.scope == "sports"
    assert proposal.claim.startswith("User prefers")
    assert proposal.evidence.startswith("Repeatedly")
    assert proposal.confidence == 0.8
    assert "sports" in get_args(MemoryScope)

    with pytest.raises(ValidationError):
        MemoryProposal(
            scope="sports",
            claim="Invalid confidence",
            evidence="Confidence must stay in range.",
            confidence=1.1,
        )


def test_sports_agent_detects_enabled_and_disabled_sports_queries(tmp_path):
    agent = SportsAgent(vault_root=tmp_path / "Vault")

    assert agent.can_handle("What is happening with the NBA Finals?")
    assert agent.can_handle("Give me Arsenal and Champions League news")
    assert agent.can_handle("Arsenal Champions League")
    assert agent.can_handle("Any F1 race updates?")
    assert agent.can_handle("NBA injury report")
    assert agent.can_handle("Arsenal score")
    assert agent.can_handle("UFC updates tonight?")
    assert not agent.can_handle("What is on my calendar tomorrow?")


def test_sports_agent_answers_combat_sports_with_web_sources_and_saves_note(tmp_path):
    vault_root = tmp_path / "Vault"
    search_output = (
        "**UFC 302 results and bonuses**\n"
        "Makhachev retained his title and the co-main ended by decision.\n"
        "https://www.espn.com/mma/story/ufc-302-results"
    )
    agent = SportsAgent(vault_root=vault_root, web_searcher=lambda query: search_output)

    response = agent.answer("Any UFC fight card updates tonight?")

    assert response.status == "answered"
    assert "UFC 302" in response.summary
    assert "[1]" in response.summary
    assert response.agent == "SportsAgent"
    assert response.sources[0].kind == "web"
    assert response.sources[0].path_or_url == "https://www.espn.com/mma/story/ufc-302-results"
    saved = list((vault_root / "Library" / "Sports" / "UFC").glob("*.md"))
    assert saved
    assert "UFC 302 results and bonuses" in saved[0].read_text(encoding="utf-8")


def test_sports_agent_disabled_keywords_do_not_match_word_fragments(tmp_path):
    agent = SportsAgent(vault_root=tmp_path / "Vault", web_searcher=lambda query: "No web results found.")

    response = agent.answer("Give me a summary of NBA Finals")

    assert response.status != "blocked"
    assert response.status == "error"
    assert not agent.can_handle("Summarize my calendar")


def test_sports_agent_enabled_keywords_do_not_match_word_fragments():
    agent = SportsAgent(vault_root=Path("unused"))

    assert not agent.can_handle("How do I type an underscore in Python?")


def test_sports_agent_generic_terms_need_sports_context():
    agent = SportsAgent(vault_root=Path("unused"))

    assert not agent.can_handle("How do I write a pytest fixture?")
    assert not agent.can_handle("What is my injury insurance policy?")
    assert not agent.can_handle("Can you improve my model score function?")


def test_sports_agent_ignores_seeded_placeholder_latest_and_uses_web(tmp_path):
    vault_root = tmp_path / "Vault"
    latest = vault_root / "Library" / "Sports" / "NBA" / "latest.md"
    latest.parent.mkdir(parents=True)
    latest.write_text("# NBA - Latest Snapshots\n\n_No snapshots yet._\n", encoding="utf-8")
    search_output = (
        "**NBA Finals schedule update**\n"
        "Game 1 tips off next week with injury reports expected before shootaround.\n"
        "https://www.nba.com/news/finals-schedule"
    )
    agent = SportsAgent(vault_root=vault_root, web_searcher=lambda query: search_output)

    response = agent.answer("NBA Finals update")

    assert response.status == "answered"
    assert "Finals schedule" in response.summary
    assert "placeholder" not in response.analysis.lower()
    assert response.sources[0].kind == "web"


def test_sports_agent_prefers_web_over_stale_latest_sports_note(tmp_path):
    vault_root = tmp_path / "Vault"
    latest = vault_root / "Library" / "Sports" / "NBA" / "latest.md"
    latest.parent.mkdir(parents=True)
    latest.write_text(
        "---\n"
        "captured_at: 2026-05-27T12:00:00Z\n"
        "---\n\n"
        "Knicks beat the Celtics behind a late fourth-quarter run.\n",
        encoding="utf-8",
    )
    search_output = (
        "**NBA Finals live injury report**\n"
        "The latest report lists two starters questionable for Game 1.\n"
        "https://www.nba.com/news/finals-injury-report"
    )
    agent = SportsAgent(vault_root=vault_root, web_searcher=lambda query: search_output)

    response = agent.answer("NBA Finals update")

    assert response.status == "answered"
    assert "injury report" in response.summary
    assert "Knicks" not in response.summary
    assert response.sources[0].path_or_url == "https://www.nba.com/news/finals-injury-report"
    assert response.memory_proposals[0].scope == "sports"


def test_live_dispatcher_routes_sports_to_sports_agent_and_records_handoff(tmp_path):
    search_output = (
        "**Last F1 race result**\n"
        "The last Grand Prix was won from pole after a late safety-car restart.\n"
        "https://www.formula1.com/en/latest/article/race-report"
    )
    dispatcher = LiveAgentDispatcher(
        vault_root=tmp_path / "Vault",
        sports_agent=SportsAgent(vault_root=tmp_path / "Vault", web_searcher=lambda query: search_output),
        state_store=MasterThreadStateStore(sessions_db=tmp_path / "sessions.db"),
    )

    result = dispatcher.maybe_handle("Who won the last F1 race?", thread_id="t1")

    assert result is not None
    assert result.agent_name == "SportsAgent"
    assert result.handled is True
    assert result.sources[0]["url"] == "https://www.formula1.com/en/latest/article/race-report"
    handoffs = list((tmp_path / "Vault" / "Agent" / "Queries").glob("*.md"))
    assert handoffs
    assert "routed_to: SportsAgent" in handoffs[0].read_text(encoding="utf-8")


def test_live_dispatcher_asks_handback_for_non_sports_turn_while_sports_active(tmp_path):
    search_output = (
        "**NBA update**\n"
        "A short live sports result.\n"
        "https://www.nba.com/news/update"
    )
    dispatcher = LiveAgentDispatcher(
        vault_root=tmp_path / "Vault",
        sports_agent=SportsAgent(vault_root=tmp_path / "Vault", web_searcher=lambda query: search_output),
        state_store=MasterThreadStateStore(sessions_db=tmp_path / "sessions.db"),
    )
    assert dispatcher.maybe_handle("NBA update", thread_id="t1") is not None

    result = dispatcher.maybe_handle("Now draft an email to Sam", thread_id="t1")

    assert result is not None
    assert result.agent_name == "SportsAgent"
    assert "route this back to Vellum" in result.answer


def test_live_dispatcher_routes_x_youtube_and_memory_pupils(tmp_path):
    x_service = XCapabilityService(
        search_posts_backend=lambda query, max_results: [
            {
                "text": "NBA posted its Finals schedule.",
                "url": "https://x.com/nba/status/1",
                "author": {"username": "nba"},
                "created_at": "2026-05-31T12:00:00Z",
            }
        ]
    )
    registry = PupilRegistry(
        {
            "XAgent": XAgent(vault_root=tmp_path / "Vault", x_service=x_service),
            "YoutubeAgent": YoutubeAgent(vault_root=tmp_path / "Vault"),
            "MemoryAgent": MemoryAgent(vault_root=tmp_path / "Vault"),
            "SportsAgent": SportsAgent(vault_root=tmp_path / "Vault"),
        }
    )
    dispatcher = LiveAgentDispatcher(
        vault_root=tmp_path / "Vault",
        registry=registry,
        state_store=MasterThreadStateStore(sessions_db=tmp_path / "sessions.db"),
    )

    x_result = dispatcher.maybe_handle("What did the NBA post on X?", thread_id="x-thread")
    youtube_result = dispatcher.maybe_handle("Summarize Arsenal highlights on YouTube", thread_id="yt-thread")
    memory_result = dispatcher.maybe_handle("Remember that I prefer concise sports analysis", thread_id="mem-thread")

    assert x_result is not None
    assert x_result.agent_name == "XAgent"
    assert "NBA posted its Finals schedule" in x_result.answer
    assert x_result.tools == ["x_agent", "web_search"]

    assert youtube_result is not None
    assert youtube_result.agent_name == "YoutubeAgent"
    assert "read-only YouTube backend is not configured" in youtube_result.answer
    assert youtube_result.tools == ["youtube_agent"]

    assert memory_result is not None
    assert memory_result.agent_name == "MemoryAgent"
    assert "reviewed proposal" in memory_result.answer
    assert memory_result.tools == ["memory_agent"]


def test_live_dispatcher_switches_between_pupils_and_keeps_main_fallback(tmp_path):
    search_output = (
        "**NBA update**\n"
        "A short live sports result.\n"
        "https://www.nba.com/news/update"
    )
    state_store = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    x_service = XCapabilityService(search_posts_backend=lambda query, max_results: [])
    registry = PupilRegistry(
        {
            "XAgent": XAgent(vault_root=tmp_path / "Vault", x_service=x_service),
            "YoutubeAgent": YoutubeAgent(vault_root=tmp_path / "Vault"),
            "MemoryAgent": MemoryAgent(vault_root=tmp_path / "Vault"),
            "SportsAgent": SportsAgent(vault_root=tmp_path / "Vault", web_searcher=lambda query: search_output),
        }
    )
    dispatcher = LiveAgentDispatcher(
        vault_root=tmp_path / "Vault",
        registry=registry,
        state_store=state_store,
    )

    sports_result = dispatcher.maybe_handle("NBA update", thread_id="thread-1")
    x_result = dispatcher.maybe_handle("What did Shams post on X?", thread_id="thread-1")
    main_result = dispatcher.maybe_handle("Draft an email to Sam", thread_id="new-thread")

    assert sports_result is not None
    assert sports_result.agent_name == "SportsAgent"
    assert x_result is not None
    assert x_result.agent_name == "XAgent"
    assert state_store.get("thread-1").active_agent == "XAgent"
    assert main_result is None


def test_specialist_router_delegates_sports_queries(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)

    decision = router.route("Give me NBA updates")

    assert decision.agent_name == "SportsAgent"
    assert decision.should_delegate is True


def test_specialist_router_keeps_general_queries_with_vellum(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)

    decision = router.route("Draft a polite email")

    assert decision.agent_name == "VellumAgent"
    assert decision.should_delegate is False


def test_specialist_router_delegates_x_and_youtube_queries(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)

    x_decision = router.route("What did AlexHormozi post on X?")
    youtube_decision = router.route("Summarize the latest YouTube videos")

    assert x_decision.agent_name == "XAgent"
    assert x_decision.should_delegate is True
    assert youtube_decision.agent_name == "YoutubeAgent"
    assert youtube_decision.should_delegate is True


def test_specialist_router_does_not_route_bare_math_or_chart_x(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)

    equation_decision = router.route("Solve for x in this equation")
    axis_decision = router.route("How do I label the x-axis in matplotlib?")

    assert equation_decision.agent_name == "VellumAgent"
    assert equation_decision.should_delegate is False
    assert axis_decision.agent_name == "VellumAgent"
    assert axis_decision.should_delegate is False


def test_specialist_router_does_not_route_generic_video_queries(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)

    file_decision = router.route("Can you summarize this video file?")
    driver_decision = router.route("Fix my video driver issue on Windows")

    assert file_decision.agent_name == "VellumAgent"
    assert file_decision.should_delegate is False
    assert driver_decision.agent_name == "VellumAgent"
    assert driver_decision.should_delegate is False


def test_specialist_router_prioritizes_explicit_source_intent_over_sports(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)

    x_decision = router.route("What did the NBA post on X?")
    arsenal_youtube_decision = router.route("Summarize Arsenal highlights on YouTube")
    nba_youtube_decision = router.route("Give me NBA YouTube videos")

    assert x_decision.agent_name == "XAgent"
    assert x_decision.should_delegate is True
    assert arsenal_youtube_decision.agent_name == "YoutubeAgent"
    assert arsenal_youtube_decision.should_delegate is True
    assert nba_youtube_decision.agent_name == "YoutubeAgent"
    assert nba_youtube_decision.should_delegate is True


def test_x_agent_searches_posts_through_capability_service(tmp_path):
    service = XCapabilityService(
        search_posts_backend=lambda query, max_results: [
            {
                "text": "Naval posted about leverage.",
                "url": "https://x.com/naval/status/1",
                "author": {"username": "naval"},
                "created_at": "2026-05-31T12:00:00Z",
            }
        ]
    )
    agent = XAgent(vault_root=tmp_path, x_service=service)

    response = agent.answer("What did Naval post on X?")

    assert response.status == "answered"
    assert "Naval posted about leverage" in response.summary
    assert response.sources[0].kind == "web"
    assert response.sources[0].path_or_url == "https://x.com/naval/status/1"


def test_x_agent_reports_needs_fetch_when_service_has_no_posts(tmp_path):
    service = XCapabilityService(search_posts_backend=lambda query, max_results: [])
    agent = XAgent(vault_root=tmp_path, x_service=service)

    response = agent.answer("What did AlexHormozi post on X?")

    assert agent.name == "XAgent"
    assert agent.can_handle("latest-50 tweets from AlexHormozi")
    assert response.status == "needs_fetch"
    assert response.summary == "XAgent did not find matching X posts."


def test_x_agent_returns_structured_response_when_service_fails(tmp_path):
    class FailingXService:
        def search_posts(self, payload):
            raise RuntimeError("network unavailable")

    agent = XAgent(vault_root=tmp_path, x_service=FailingXService())

    response = agent.answer("What did Naval post on X?")

    assert response.agent == "XAgent"
    assert response.status == "error"
    assert response.confidence == 0.2
    assert "could not fetch X posts" in response.summary
    assert "network unavailable" in response.analysis


def test_youtube_agent_stub_defers_full_execution(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path)

    response = agent.answer("Summarize the latest YouTube videos")

    assert agent.name == "YoutubeAgent"
    assert agent.can_handle("youtube channel transcript")
    assert response.status == "needs_fetch"
    assert "read-only YouTube backend is not configured" in response.summary


def test_youtube_agent_does_not_match_yt_hyphenated_tool_names(tmp_path):
    agent = YoutubeAgent(vault_root=tmp_path)

    assert not agent.can_handle("how do I fix yt-dlp on windows")


def test_youtube_agent_returns_structured_response_when_service_fails(tmp_path):
    class FailingYoutubeService:
        def search_videos(self, payload):
            raise RuntimeError("youtube API key leaked-user-token-123456789012345678901234567890")

    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=FailingYoutubeService())

    response = agent.answer("Summarize the latest YouTube videos")

    assert response.agent == "YoutubeAgent"
    assert response.status == "error"
    assert response.summary == "YoutubeAgent could not fetch YouTube data right now."
    assert response.confidence == 0.2
    assert "YouTube search failed" in response.analysis
    assert "leaked-user-token" not in response.analysis


def test_memory_agent_builds_context_pack_and_reviews_memory(tmp_path):
    from agent.agents.memory_agent import MemoryAgent
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    vault = tmp_path / "Vault"
    card_dir = vault / "Agent" / "Memories" / "Shared"
    card_dir.mkdir(parents=True)
    (card_dir / "style.md").write_text("User prefers concise answers.", encoding="utf-8")
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")
    agent = MemoryAgent(vault_root=vault, memory_service=service)

    response = agent.answer("What should you remember about my answer style?")

    assert response.status == "answered"
    assert "concise answers" in response.summary
    assert response.memory_proposals


def test_memory_agent_answers_through_memory_service(tmp_path):
    agent = MemoryAgent(vault_root=tmp_path)

    response = agent.answer("Remember my sports analysis preference")

    assert agent.name == "MemoryAgent"
    assert agent.can_handle("remember my preference")
    assert agent.can_handle("build memory context for this thread")
    assert not agent.can_handle("build context for this Python error")
    assert response.status == "answered"
    assert "reviewed proposal" in response.summary
    assert response.memory_proposals
    assert all(proposal.confidence >= 0.75 for proposal in response.memory_proposals)
    assert response.memory_proposals[0].claim == "User's sports analysis preference."


def test_memory_agent_proposes_user_specific_memory_claim(tmp_path):
    agent = MemoryAgent(vault_root=tmp_path)

    response = agent.answer("Remember that I prefer concise sports analysis")

    assert response.memory_proposals[0].claim == "User prefers concise sports analysis."


def test_memory_agent_review_proposals_filters_low_confidence(tmp_path):
    agent = MemoryAgent(vault_root=tmp_path)
    low_confidence = MemoryProposal(
        scope="memory",
        claim="Weak preference signal.",
        evidence="One vague mention.",
        confidence=0.5,
    )
    high_confidence = MemoryProposal(
        scope="memory",
        claim="Stable preference signal.",
        evidence="Repeated explicit preference.",
        confidence=0.85,
    )

    proposals = agent.review_proposals([low_confidence, high_confidence])

    assert proposals == [high_confidence]


def test_memory_agent_returns_error_when_memory_service_fails(tmp_path):
    class FailingMemoryService:
        def build_context_pack(self, payload):
            raise RuntimeError("sessions database locked with user@example.com")

    agent = MemoryAgent(vault_root=tmp_path, memory_service=FailingMemoryService())

    response = agent.answer("Remember my preference")

    assert response.status == "error"
    assert response.summary == "MemoryAgent could not build memory context right now."
    assert response.confidence == 0.2
    assert "sessions database locked" in response.analysis
    assert "user@example.com" not in response.analysis
