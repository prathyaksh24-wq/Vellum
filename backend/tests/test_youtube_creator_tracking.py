from datetime import UTC, datetime, timedelta
from pathlib import Path
import time

import pytest

from agent.contracts.youtube_tracking import CreatorTrackingConfig
from agent.conversations.lifecycle import ConversationLifecycle
from agent.knowledge.models import ObservationActor, ObservationInput, SourceItemInput
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_creator_tracking import AtomFeedReader, YouTubeCreatorTracking
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService

C1 = "UC" + "a" * 22
C2 = "UC" + "b" * 22
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


class Clock:
    value = NOW
    def __call__(self):
        return self.value


class Reader:
    def __init__(self):
        self.entries = []
        self.calls = []
        self.error = None
    def fetch(self, channel, state):
        self.calls.append((channel, state.copy()))
        if self.error:
            return self.error
        return {"entries": self.entries, "etag": "etag-1"}


@pytest.fixture
def setup(tmp_path):
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    source = store.upsert_source(SourceItemInput(kind="youtube_takeout_archive", external_id="archive", account_id="me"))["source_id"]
    clock, reader = Clock(), Reader()
    service = YouTubeCreatorTracking(store=store, reader=reader, clock=clock, metadata_provider=lambda _: {})
    return store, source, clock, reader, service


def configure(service, rules=(), **options):
    return service.configure({"account_id": "me", "history_accounts": ["me"], "enabled": True, "api_fallback": False, "rules": list(rules), **options})


def test_api_fallback_baseline_and_later_upload_share_outbox_identity(setup):
    _, _, clock, reader, service = setup
    configure(service, [rule()], api_fallback=True)
    reader.error = {"error": "feed_http_404"}
    fallback = []
    service.uploads_provider = lambda channel, **kwargs: fallback.append((channel, kwargs)) or {"entries": [upload()], "uploads_playlist": "UU" + "a"*22, "transport": "youtube_data_api"}
    assert service.refresh()["fallback_checks"] == 1
    clock.value += timedelta(hours=1)
    reader.error = None
    reader.entries = [upload(), upload("00000000002")]
    calls = []
    service.refresh(deliver=lambda *args: calls.append(args))
    assert len(calls) == 1 and "00000000002" in calls[0][1]


def test_linked_sources_deduplicate_across_midnight_in_history_timezone(setup):
    store, source, clock, _, service = setup
    clock.value = NOW + timedelta(days=1)
    configure(service, timezone="Asia/Kolkata")
    watched = NOW.replace(hour=21)
    store.record_observations([watch(store, source, day=watched), watch(store, source, origin="youtube_browser_history", day=clock.value)])
    service.project()
    assert service.snapshot()["creators"][0]["total_video_days"] == 1


def test_local_day_after_midnight_is_not_discarded_as_future_utc_day(setup):
    store, source, clock, _, service = setup
    clock.value = NOW.replace(hour=21)  # 02:30 on October 11 in Kolkata
    configure(service, timezone="Asia/Kolkata")
    store.record_observations([watch(store, source, day=clock.value), watch(store, source,
        origin="youtube_browser_history", day=clock.value, history_day="2026-10-11")])
    service.project()
    creator = service.snapshot()["creators"][0]
    assert creator["total_video_days"] == 1
    assert creator["recent_days"] == 1
    assert creator["last_watched"] == "2026-10-11"


def rule(channel=C1, name="Creator", relationship="long_term", **options):
    return {"channel_id": channel, "name": name, "relationship": relationship, **options}


def watch(store, source, *, video="00000000001", channel=C1, name="Creator", day=NOW, origin="youtube_takeout", **payload):
    return ObservationInput(origin=origin, action="youtube.watch" if origin == "youtube_takeout" else "youtube.history_presence",
        actor=ObservationActor.IMPORTED, source_id=source, event_key=f"{origin}:{source}:{video}:{day.date()}",
        observed_at=day, payload={"video_id": video, "channel_id": channel, "channel_title": name,
            "history_day": day.date().isoformat(), **payload})


def upload(video="00000000001", **values):
    return {"video_id": video, "title": "A new video", "creator": "Creator", "published_at": NOW.isoformat(), **values}


def test_incremental_scope_cross_source_dedup_and_search_is_not_endorsement(setup):
    store, source, _, _, service = setup
    other = store.upsert_source(SourceItemInput(kind="youtube_takeout_archive", external_id="other", account_id="other"))["source_id"]
    store.record_observations([watch(store, source), watch(store, source, origin="youtube_browser_history"),
        watch(store, other, channel=C2), ObservationInput(origin="youtube_takeout", action="youtube.search", actor=ObservationActor.IMPORTED,
            source_id=source, payload={"query": "Creator"}, observed_at=NOW)])
    configure(service)
    assert service.project()["scanned"] == 2
    assert service.project()["scanned"] == 0
    assert service.snapshot()["creators"][0]["total_video_days"] == 1
    assert len(service.snapshot()["creators"]) == 1


def test_current_interest_fades_and_seasonal_relationship_survives(setup):
    store, source, clock, _, service = setup
    configure(service, [rule(relationship="current"), rule(C2, "Seasonal", "seasonal")])
    assert service.snapshot()["creators"][0]["state"] == "monitoring"
    clock.value = NOW + timedelta(days=45)
    states = {item["channel_id"]: item["state"] for item in service.snapshot()["creators"]}
    assert states == {C1: "quiet", C2: "seasonal_quiet"}
    store.record_observations([watch(store, source, video=f"{i:011d}", channel=C2, name="Seasonal", day=clock.value-timedelta(days=i)) for i in range(3)])
    service.project()
    states = {item["channel_id"]: item["state"] for item in service.snapshot()["creators"]}
    assert states[C2] == "monitoring"


def test_explicit_exclusion_and_former_interest_never_auto_reactivate(setup):
    store, source, _, reader, service = setup
    store.record_observations([watch(store, source, video=f"{i:011d}", day=NOW-timedelta(days=i)) for i in range(8)])
    configure(service, [rule(relationship="excluded"), rule(C2, "Former", "former")])
    result = service.refresh()
    assert result["requests"] == 0
    assert reader.calls == []
    assert service.snapshot()["creators"][0]["score"] == 0
    configure(service, [])  # omitted exclusions persist
    assert service.snapshot()["excluded"] == ["Creator"]


def test_exclusion_binds_verified_identity_then_survives_rename(setup):
    store, source, clock, _, service = setup
    configure(service, [{"name": "Brand", "relationship": "excluded"}])
    store.record_observation(watch(store, source, name="Brand"))
    service.refresh()
    clock.value += timedelta(days=1)
    store.record_observation(watch(store, source, video="00000000002", name="Renamed", day=clock.value))
    service.refresh()
    assert service.snapshot()["creators"][0]["state"] == "excluded"


def test_exclusions_invalidate_existing_positive_projection_and_block_rebuild(setup):
    store, source, _, _, service = setup
    store.record_observation(watch(store, source))
    intelligence = YouTubeIntelligenceService(store)
    intelligence.rebuild(now=NOW)
    assert intelligence.snapshot()["channels"]
    configure(service, [rule(relationship="excluded")])
    assert not intelligence.snapshot()["channels"]
    intelligence.rebuild(now=NOW, mode="backfill")
    assert not intelligence.snapshot()["channels"]
    assert store.count_observations(origin="youtube_takeout") == 1


def test_baseline_title_edit_restart_and_delivery_retry_are_idempotent(setup, tmp_path):
    store, _, clock, reader, service = setup
    configure(service, [rule()])
    reader.entries = [upload()]
    calls = []
    service.refresh(deliver=lambda *args: calls.append(args))
    assert not calls
    clock.value += timedelta(hours=1)
    reader.entries = [upload(title="Edited title"), upload("00000000002")]
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json")
    def crash_after_delivery(key, text):
        lifecycle.deliver_automation(delivery_id=key, text=text, name="Upload")
        raise RuntimeError("Simulated crash before outbox acknowledgment")
    with pytest.raises(RuntimeError):
        service.refresh(deliver=crash_after_delivery)
    restarted = YouTubeCreatorTracking(store=KnowledgeStore(store.db_path, store.blobs.root), reader=reader, clock=clock)
    result = restarted.refresh(deliver=lambda key, text: lifecycle.deliver_automation(delivery_id=key, text=text, name="Upload"))
    assert result["delivered"] == 1
    assert len(lifecycle.list()) == 1
    assert len(lifecycle.list()[0]["messages"]) == 1
    assert "00000000002" in lifecycle.list()[0]["messages"][0]["text"]
    assert restarted.refresh(deliver=lambda *args: calls.append(args))["delivered"] == 0
    assert not calls


def test_new_exclusion_suppresses_already_pending_notification(setup):
    _, _, clock, reader, service = setup
    configure(service, [rule()])
    service.refresh()
    reader.entries = [upload()]
    clock.value += timedelta(hours=1)
    service.refresh()
    configure(service, [rule(relationship="excluded")])
    calls = []
    service.refresh(deliver=lambda *args: calls.append(args))
    assert not calls


def test_topic_gate_backoff_budget_and_unchanged_poll(setup):
    _, _, clock, reader, service = setup
    configure(service, [rule(topic_terms=["NBA"])], requests_per_day=2)
    service.refresh()
    clock.value += timedelta(hours=1)
    reader.entries = [upload(title="NFL preview"), upload("00000000002", title="NBA preview")]
    calls = []
    service.refresh(deliver=lambda *args: calls.append(args))
    assert len(calls) == 1 and "NBA preview" in calls[0][1]
    clock.value += timedelta(hours=1)
    assert service.refresh()["requests"] == 0
    clock.value += timedelta(days=1)
    reader.error = {"error": "feed_http_429", "retry_after": "7200"}
    assert service.refresh()["requests"] == 1
    clock.value += timedelta(minutes=30)
    assert service.refresh()["requests"] == 0


def test_missing_attribution_is_resolved_in_batches_and_unavailable_does_not_starve(setup):
    store, source, _, _, service = setup
    configure(service)
    store.record_observations([watch(store, source, channel="", video=f"{i:011d}") for i in range(55)])
    seen = []
    service.metadata_provider = lambda videos: seen.append(videos) or {video: {"channel_id": C1, "name": "Creator"} for video in videos[:2]}
    service.refresh()
    assert len(seen[0]) == 50
    assert service.snapshot()["creators"][0]["total_video_days"] == 2
    assert service.snapshot()["pending_attribution"] == 5
    assert service.snapshot()["unavailable_attribution"] == 48


def test_lease_blocks_overlapping_worker_and_recovers_after_expiration(setup):
    store, _, clock, _, service = setup
    configure(service, [rule()])
    assert store.youtube_tracking_lock("me", "other", NOW.timestamp())
    assert service.refresh()["status"] == "busy"
    clock.value += timedelta(minutes=11)
    assert service.refresh()["status"] == "ready"


def test_atom_identity_entity_and_size_boundaries():
    xml = f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><yt:channelId>{C1}</yt:channelId><entry><yt:channelId>{C1}</yt:channelId><yt:videoId>00000000001</yt:videoId><title>NBA &amp; chess</title><published>2026-10-10T12:00:00Z</published><author><name>Creator</name></author></entry></feed>'.encode()
    assert AtomFeedReader.parse(xml, C1)[0]["title"] == "NBA & chess"
    for raw, channel in [(xml, C2), (b'<!DOCTYPE foo><feed/>', C1), (b'x' * 262145, C1)]:
        with pytest.raises(ValueError):
            AtomFeedReader.parse(raw, channel)


def test_invalid_config_rejects_unverified_monitoring_ids():
    with pytest.raises(ValueError):
        CreatorTrackingConfig(account_id="me", history_accounts=["me"], rules=[{"name": "Creator", "relationship": "current"}])


def test_manual_runs_share_fifteen_minute_request_budget(setup):
    _, _, _, reader, service = setup
    configure(service, [rule(), rule(C2, "Second")], requests_per_run=1)
    result = service.refresh()
    assert result["requests"] == 1 and result["status"] == "baselining"
    assert service.snapshot()["baselined_channels"] == 1
    assert service.snapshot()["monitored_channels"] == 2
    assert service.refresh()["requests"] == 0
    assert len(reader.calls) == 1


def test_rolling_budget_prevents_bursts_across_window_boundary(setup):
    _, _, clock, reader, service = setup
    configure(service, [rule()], requests_per_run=2)
    assert service.refresh()["requests"] == 1
    clock.value += timedelta(minutes=14)
    configure(service, [rule(), rule(C2, "Second")], requests_per_run=2)
    assert service.refresh()["requests"] == 1
    clock.value += timedelta(minutes=1, seconds=1)
    configure(service, [rule(), rule(C2, "Second"), rule("UC"+"c"*22, "Third"),
        rule("UC"+"d"*22, "Fourth")], requests_per_run=2)
    assert service.refresh()["requests"] == 1
    assert service.refresh()["requests"] == 0
    assert len(reader.calls) == 3


def test_configuration_preserves_bounds_and_prunes_old_interest_seeds(setup):
    _, _, _, _, service = setup
    configure(service, [rule(relationship="current")])
    configure(service, [rule(C2, "Second", "current")])
    assert set(service._settings()["seeds"]) == {C2}
    configure(service, [rule(relationship="excluded")])
    before = service._settings()
    replacements = [rule("UC"+f"{i:022d}", f"Creator {i}") for i in range(200)]
    with pytest.raises(ValueError):
        configure(service, replacements, history_accounts=["other"])
    assert service._settings() == before


def test_timezone_and_topic_filter_changes_rebuild_derived_counts(setup):
    store, source, clock, _, service = setup
    clock.value = NOW + timedelta(days=1)
    store.record_observations([watch(store, source, video="00000000001", day=NOW.replace(hour=21), title="NBA game"),
        watch(store, source, video="00000000002", day=NOW.replace(hour=21), title="Golf game")])
    configure(service, [rule()])
    service.project()
    assert service.snapshot()["creators"][0]["total_video_days"] == 2
    configure(service, [rule(topic_terms=["NBA"])], timezone="Asia/Kolkata")
    assert service.project()["scanned"] == 2
    creator = service.snapshot()["creators"][0]
    assert creator["total_video_days"] == 1 and creator["last_watched"] == "2026-10-11"


def test_scope_change_rebuilds_only_selected_accounts(setup):
    store, source, _, _, service = setup
    other = store.upsert_source(SourceItemInput(kind="youtube_takeout_archive", external_id="other", account_id="other"))["source_id"]
    store.record_observations([watch(store, source), watch(store, other, channel=C2)])
    configure(service)
    service.project()
    service.configure({"account_id": "me", "history_accounts": ["other"], "enabled": True})
    service.project()
    assert [item["channel_id"] for item in service.snapshot()["creators"]] == [C2]


def test_seasonal_topic_activity_and_explicit_ads_do_not_activate_other_topics(setup):
    store, source, _, _, service = setup
    configure(service, [rule(relationship="seasonal", topic_terms=["NBA"])])
    store.record_observations([watch(store, source, video=f"{i:011d}", title="NFL recap", day=NOW-timedelta(days=i)) for i in range(5)])
    store.record_observation(watch(store, source, video="00000000009", title="NBA ad", is_ad=True))
    service.project()
    assert service.snapshot()["creators"][0]["state"] == "seasonal_quiet"


def test_feed_error_and_coverage_gap_remain_visible_in_status(setup):
    _, _, clock, reader, service = setup
    configure(service, [rule()])
    service.refresh()
    clock.value += timedelta(days=2)
    reader.error = {"error": "feed_http_500"}
    assert service.refresh()["status"] == "partial"
    assert len(service.snapshot()["warnings"]) == 2


def test_creator_http_contract_and_action_schemas_are_registered(setup, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent.plugins import youtube_api, youtube_creator_tracking
    from agent.plugins.youtube_controls import youtube_plugin_contribution
    store, _, _, _, service = setup
    configure(service, [rule()])
    monkeypatch.setattr(youtube_creator_tracking, "get_knowledge_core", lambda: type("Core", (), {"store": store})())
    app = FastAPI()
    app.include_router(youtube_api.router, prefix="/api")
    with TestClient(app) as client:
        response = client.get("/api/plugins/youtube/creators")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["configured"]
        assert client.get("/api/plugins/youtube/creators?limit=101").status_code == 422
    contribution = youtube_plugin_contribution()
    actions = {item.definition.id: item.definition for item in contribution.actions}
    assert actions["youtube.creators.configure"].required_permissions == ["youtube.creators.configure"]
    assert actions["youtube.creators.refresh"].argument_schema["additionalProperties"] is False


def test_delivery_to_existing_chat_preserves_edits_and_retries(tmp_path):
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json")
    lifecycle.save("chat", {"thread_id": "chat", "title": "Mine", "messages": [{"id": "old", "role": "user", "text": "Keep me"}]})
    assert lifecycle.deliver_automation(delivery_id="upload-1", text="Creator: title", name="Upload", thread_id="chat")
    assert not lifecycle.deliver_automation(delivery_id="upload-1", text="Creator: title", name="Upload", thread_id="chat")
    assert len(lifecycle.get("chat")["messages"]) == 2
    assert lifecycle.get("chat")["title"] == "Mine"
    with pytest.raises(ValueError):
        lifecycle.deliver_automation(delivery_id="upload-2", text="Title", name="Upload", thread_id="missing")


def test_automation_delivers_without_model_and_records_receipt(setup, tmp_path, monkeypatch):
    import asyncio
    from agent.automations import runner, builtins
    from agent.automations.store import AutomationStore
    from agent.plugins import youtube_creator_tracking
    _, _, clock, reader, service = setup
    configure(service, [rule()])
    service.refresh()
    clock.value += timedelta(hours=1)
    reader.entries = [upload()]
    lifecycle = ConversationLifecycle(path=tmp_path / "messages.json")
    monkeypatch.setattr(youtube_creator_tracking, "YouTubeCreatorTracking", lambda: service)
    monkeypatch.setattr(runner, "_deliver_creator_upload", lambda automation, key, text:
        lifecycle.deliver_automation(delivery_id=key, text=text, name="Creator upload"))
    async def no_model(*_):
        raise AssertionError("Creator polling must not call a chat model")
    monkeypatch.setattr(runner, "_execute_reasoning_turn", no_model)
    automations = AutomationStore(tmp_path / "automations")
    builtins.seed_builtins(automations)
    record = next(item for item in automations.list() if item["builtin_key"] == "youtube_creator_tracking")
    result = asyncio.run(runner.run_automation_now(record, automations))
    assert result["status"] == "complete"
    assert "1 delivered uploads" in result["output"]
    assert len(lifecycle.list()) == 1


def test_atom_conditional_requests_and_redirect_rejection(monkeypatch):
    from agent.plugins import youtube_creator_tracking
    seen = []
    class Response:
        status_code = 304
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *_): return False
    response = Response()
    def stream(method, url, **kwargs):
        seen.append((method, url, kwargs))
        return response
    monkeypatch.setattr(youtube_creator_tracking.httpx, "stream", stream)
    assert AtomFeedReader().fetch(C1, {"etag": "saved"})["unchanged"]
    assert seen[0][2]["headers"]["If-None-Match"] == "saved"
    assert seen[0][2]["follow_redirects"] is False
    response.status_code = 302
    assert AtomFeedReader().fetch(C1, {})["error"] == "feed_http_302"


def test_twenty_year_history_has_bounded_stats_and_fast_steady_read(setup):
    store, source, _, _, service = setup
    configure(service)
    events = [watch(store, source, video=f"{i:011d}", day=NOW-timedelta(days=i)) for i in range(7300)]
    store.record_observations(events)
    service.project(max_pages=30)
    stat = store.youtube_tracking_stats("me")[0]
    assert stat["total"] == 7300
    assert len(stat["days"]) <= 367
    start = time.perf_counter()
    assert service.project()["scanned"] == 0
    assert service.snapshot()["creators"][0]["total_video_days"] == 7300
    assert time.perf_counter() - start < 2
