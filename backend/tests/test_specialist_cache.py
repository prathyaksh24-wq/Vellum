from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.memory.specialist_cache import SpecialistResponseCache
from agent.profiles import CachePolicy


NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


def response(summary: str = "Arsenal play on Saturday") -> SpecialistResponse:
    return SpecialistResponse(
        agent="SportsAgent",
        status="answered",
        summary=summary,
        confidence=0.9,
        sources=[SpecialistSource(kind="web", title="Official", path_or_url="https://example.com")],
    )


def test_cache_exact_hit_round_trips_specialist_response(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    policy = CachePolicy(default_ttl_seconds=3600, bypass_terms=[])
    cache.store(profile_id="SportsAgent", profile_version=1, query="When do Arsenal play?", response=response(), policy=policy)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=1, query=" when do  arsenal PLAY? ", policy=policy)

    assert decision.status == "hit"
    assert decision.response == response()


def test_cache_reuses_conservative_related_query(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    policy = CachePolicy(default_ttl_seconds=3600, bypass_terms=[])
    cache.store(profile_id="SportsAgent", profile_version=1, query="Who won the NBA title in 2024?", response=response("Boston"), policy=policy)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=1, query="Who won 2024 NBA title?", policy=policy)

    assert decision.status == "hit"
    assert decision.reason == "related_query"
    assert decision.response.summary == "Boston"


def test_cache_marks_expired_entry_stale(tmp_path: Path) -> None:
    clock = [NOW]
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: clock[0])
    policy = CachePolicy(default_ttl_seconds=60, bypass_terms=[])
    cache.store(profile_id="SportsAgent", profile_version=1, query="Arsenal fixture", response=response(), policy=policy)
    clock[0] += timedelta(seconds=61)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=1, query="Arsenal fixture", policy=policy)

    assert decision.status == "stale"
    assert decision.response is not None


def test_live_intent_bypasses_even_when_exact_entry_exists(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    policy = CachePolicy(default_ttl_seconds=3600, bypass_terms=["live", "today"])
    cache.store(profile_id="SportsAgent", profile_version=1, query="NBA score today", response=response(), policy=policy)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=1, query="NBA score today", policy=policy)

    assert decision.status == "bypass"
    assert decision.reason == "live_intent:today"


def test_profile_version_change_invalidates_old_cache(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    policy = CachePolicy(default_ttl_seconds=3600, bypass_terms=[])
    cache.store(profile_id="SportsAgent", profile_version=1, query="Arsenal fixture", response=response(), policy=policy)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=2, query="Arsenal fixture", policy=policy)

    assert decision.status == "miss"


def test_action_requests_are_not_cacheable(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    action = response().model_copy(update={"action_request": {"action": "x.post"}})

    assert cache.store(profile_id="XAgent", profile_version=1, query="post this", response=action, policy=CachePolicy()) is False
