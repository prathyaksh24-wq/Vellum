from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.knowledge.api import router as knowledge_core_router
from agent.knowledge.ingestion import IngestionCoordinator, IngestionResult
from agent.knowledge.models import (
    BootstrapRequest,
    ContentAnnotationInput,
    ContentStance,
    ContextPackRequest,
    EvidenceClass,
    ExternalPolicy,
    IngestionJobInput,
    ObservationActor,
    ObservationInput,
    ProjectionInput,
    Sensitivity,
    SourceItemInput,
    UserSignalInput,
)
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore
from agent.knowledge.runtime import set_knowledge_core
from agent.knowledge.tool_observer import KnowledgeToolObserver
from agent.tools.registry import CapabilityAccess, ToolInvocation


def build_core(tmp_path: Path) -> KnowledgeCore:
    vault = tmp_path / "Vault"
    vault.mkdir()
    conversations = tmp_path / "data" / "ui" / "conversations.json"
    conversations.parent.mkdir(parents=True)
    conversations.write_text('{"conversations": []}\n', encoding="utf-8")
    return KnowledgeCore(
        KnowledgeStore(tmp_path / "data" / "knowledge" / "core.db", tmp_path / "data" / "knowledge" / "blobs"),
        conversations_path=conversations,
        vault_root=vault,
    )


def test_source_versions_are_content_addressed_and_idempotent(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    source = SourceItemInput(
        kind="book_page",
        external_id="book-1:page-1",
        title="Page one",
        content="A private page.",
        sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
        external_policy=ExternalPolicy.DENY_RAW,
    )

    first = core.store.upsert_source(source)
    second = core.store.upsert_source(source)
    revised = core.store.upsert_source(source.model_copy(update={"content": "A revised private page."}))

    assert first["created"] is True
    assert first["version_created"] is True
    assert second["created"] is False
    assert second["version_created"] is False
    assert revised["version_created"] is True
    assert core.store.status()["counts"]["sources"] == 1
    assert core.store.status()["counts"]["source_versions"] == 2
    assert list((tmp_path / "data" / "knowledge" / "blobs").rglob("*.txt.gz"))


def test_observations_and_projections_dedupe_by_stable_identity(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    observation = ObservationInput(
        origin="x.search_posts",
        actor=ObservationActor.AGENT,
        trigger="agent_research",
        action="tool.result_observed",
        event_key="x-search:naval:2026-07-21",
        payload={"count": 5},
    )
    projection = ProjectionInput(
        canonical_type="conversation",
        canonical_id="chat-1",
        target="obsidian",
        target_ref="Agent/Conversations/chat-1.md",
    )

    assert core.store.record_observation(observation)["created"] is True
    assert core.store.record_observation(observation)["created"] is False
    assert core.store.register_projection(projection)["created"] is True
    assert core.store.register_projection(projection)["created"] is False
    status = core.store.status()["counts"]
    assert status["observations"] == 1
    assert status["projections"] == 1


def test_external_context_pack_never_contains_deny_raw_content(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    result = core.store.upsert_source(
        SourceItemInput(
            kind="book_page",
            external_id="meditations:4",
            title="Meditations book four",
            content="Raw copyrighted and private book text.",
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            external_policy=ExternalPolicy.DENY_RAW,
        )
    )

    external = core.create_context_pack(
        ContextPackRequest(query="Meditations", destination="external", include_raw_content=True)
    )
    local = core.create_context_pack(
        ContextPackRequest(query="Meditations", destination="local", include_raw_content=True)
    )

    assert external["evidence"][0]["source_id"] == result["source_id"]
    assert external["evidence"][0]["content_withheld"] is True
    assert "content" not in external["evidence"][0]
    assert local["evidence"][0]["content"] == "Raw copyrighted and private book text."


def test_bootstrap_preview_is_read_only_and_apply_is_repeatable(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    core.conversations_path.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "chat-1",
                        "thread_id": "thread-1",
                        "title": "Architecture",
                        "messages": [
                            {"role": "user", "text": "Design Vellum."},
                            {"role": "assistant", "text": "Use one canonical store."},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    source = core.vault_root / "Library" / "X" / "naval"
    source.mkdir(parents=True)
    (source / "post.md").write_text(
        "---\nstatus_id: 123\nsource_trust: imported_archive\n---\n# Attention\nAttention is scarce.\n",
        encoding="utf-8",
    )
    projection = core.vault_root / "Agent" / "Conversations"
    projection.mkdir(parents=True)
    (projection / "chat.md").write_text(
        "---\nconversation_id: chat-1\ngenerated_by: vellum\n---\n# Architecture\n",
        encoding="utf-8",
    )

    preview = core.bootstrap(BootstrapRequest(apply=False))
    assert preview["mode"] == "preview"
    assert preview["conversations"]["scanned"] == 1
    assert core.store.status()["counts"]["sources"] == 0

    first = core.bootstrap(BootstrapRequest(apply=True))
    second = core.bootstrap(BootstrapRequest(apply=True))
    assert first["conversations"]["versions"] == 1
    assert first["vault"]["projections"] == 1
    assert first["vault"]["versions"] == 1
    assert second["conversations"]["versions"] == 0
    assert second["vault"]["versions"] == 0
    counts = core.store.status()["counts"]
    assert counts["sources"] == 2
    assert counts["source_versions"] == 2
    assert counts["projections"] == 1


def test_shadow_turn_learning_does_not_treat_agent_tools_as_user_interest(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    result = core.record_turn(
        thread_id="thread-1",
        query="What did Naval post?",
        answer="A sourced answer.",
        tools=[{"name": "x.search_posts"}],
        sources=["https://x.com/naval/status/1"],
    )

    assert result["stored"] is True
    observation = core.store.list_observations()[0]
    assert observation["actor"] == "user"
    assert observation["action"] == "conversation.turn_recorded"
    assert core.store.status()["counts"]["user_signals"] == 0


def test_core_api_stays_under_existing_knowledge_namespace(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    set_knowledge_core(core)
    app = FastAPI()
    app.include_router(knowledge_core_router, prefix="/api/knowledge")
    client = TestClient(app)
    try:
        status = client.get("/api/knowledge/core/status")
        preview = client.post("/api/knowledge/core/bootstrap", json={"apply": False})
        unconfirmed_apply = client.post("/api/knowledge/core/bootstrap", json={"apply": True})
        signal = client.post(
            "/api/knowledge/core/signals",
            json={
                "subject_key": "youtube:channel:test",
                "category": "youtube_channel",
                "signal_type": "completed_video",
                "event_key": "youtube:test:completion:1",
                "value": 0.9,
                "actor": "user",
            },
        )
        spoofed_connector = client.post(
            "/api/knowledge/core/signals",
            json={
                "subject_key": "youtube:channel:test",
                "category": "youtube_channel",
                "signal_type": "completed_video",
                "event_key": "youtube:test:completion:2",
                "value": 0.9,
                "actor": "connector",
            },
        )
        preferences = client.get("/api/knowledge/core/preferences?category=youtube_channel")
        ingestion_jobs = client.get("/api/knowledge/core/ingestion-jobs")
        sync_cursors = client.get("/api/knowledge/core/sync-cursors")
        annotations = client.get("/api/knowledge/core/annotations?requires_review=true")
        context = client.post(
            "/api/knowledge/core/context-packs",
            json={"query": "anything", "destination": "external"},
        )
    finally:
        set_knowledge_core(None)

    assert status.status_code == 200
    assert status.json()["mode"] == "shadow"
    assert preview.status_code == 200
    assert preview.json()["mode"] == "preview"
    assert unconfirmed_apply.status_code == 409
    assert signal.status_code == 200
    assert signal.json()["eligible"] is True
    assert spoofed_connector.status_code == 422
    assert preferences.status_code == 200
    assert preferences.json()["count"] == 1
    assert ingestion_jobs.status_code == 200
    assert sync_cursors.status_code == 200
    assert annotations.status_code == 200
    assert context.status_code == 200
    assert context.json()["policy"]["raw_private_content"] == "withheld"


def test_tool_observer_records_evidence_but_not_preferences(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    core.tool_learning_enabled = True
    observer = KnowledgeToolObserver(core)

    observer(
        ToolInvocation(
            name="x.likes",
            namespace="x",
            access=CapabilityAccess.READ,
            agent_name="XAgent",
            payload={"handle": "me", "max_results": 5},
            result={
                "items": [
                    {
                        "text": "An interesting post",
                        "url": "https://x.com/example/status/123",
                        "handle": "example",
                    }
                ],
                "provider": "agent-reach",
            },
        )
    )

    sources = core.store.list_sources(kind="x_post")
    observations = core.store.list_observations(origin="x.likes")
    assert len(sources) == 1
    assert sources[0]["external_id"] == "123"
    assert sources[0]["sensitivity"] == "private"
    assert len(observations) == 1
    assert observations[0]["actor"] == "agent"
    assert core.store.status()["counts"]["user_signals"] == 0
    annotations = core.store.list_content_annotations(target_id=sources[0]["id"])
    assert annotations[0]["labels"] == ["ambiguous_engagement"]
    assert annotations[0]["stance"] == "unknown"
    assert annotations[0]["eligible_for_preference"] is False
    assert annotations[0]["eligible_for_style"] is False
    assert annotations[0]["requires_review"] is True


def test_tool_observer_withholds_transcript_raw_content_from_external_context(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    core.tool_learning_enabled = True
    KnowledgeToolObserver(core)(
        ToolInvocation(
            name="youtube.fetch_transcript",
            namespace="youtube",
            access=CapabilityAccess.READ,
            agent_name="YoutubeAgent",
            payload={"video_id": "abc123"},
            result={"video_id": "abc123", "transcript": "Full transcript text."},
        )
    )

    context = core.create_context_pack(
        ContextPackRequest(query="YouTube transcript abc123", destination="external", include_raw_content=True)
    )
    assert context["evidence"][0]["external_policy"] == "deny_raw"
    assert context["evidence"][0]["content_withheld"] is True
    assert "content" not in context["evidence"][0]


def test_preference_state_preserves_historical_peak_and_detects_waning_interest(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    now = datetime.now(UTC)
    for index, days_ago in enumerate((240, 220, 200, 180)):
        core.store.record_user_signal(
            UserSignalInput(
                subject_key="youtube:channel:sidemen",
                category="youtube_channel",
                signal_type="completed_video",
                event_key=f"youtube:history:old:{index}",
                value=1.0,
                weight=1.0,
                actor=ObservationActor.IMPORTED,
                evidence_class=EvidenceClass.IMPORTED,
                observed_at=now - timedelta(days=days_ago),
            )
        )
    core.store.record_user_signal(
        UserSignalInput(
            subject_key="youtube:channel:sidemen",
            category="youtube_channel",
            signal_type="partial_view",
            event_key="youtube:history:recent:1",
            value=0.2,
            weight=1.0,
            actor=ObservationActor.CONNECTOR,
            observed_at=now - timedelta(days=8),
        )
    )

    state = core.store.recompute_preference("youtube:channel:sidemen", now=now)

    assert state is not None
    assert state["historical_peak"] == 1.0
    assert state["current_score"] < state["historical_peak"]
    assert state["trend"] == "falling"
    assert state["lifecycle"] == "waning"
    assert state["windows"]["recent_30d"]["count"] == 1
    assert state["windows"]["prior_30_to_180d"]["count"] == 0


def test_agent_selected_tool_signal_cannot_change_preferences(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    result = core.store.record_user_signal(
        UserSignalInput(
            subject_key="x:topic:philosophy",
            category="topic",
            signal_type="agent_search",
            event_key="tool:x.search:1",
            value=1.0,
            actor=ObservationActor.AGENT,
            preference_evidence=True,
        )
    )

    assert result["eligible"] is False
    assert result["preference"] is None
    assert core.store.list_preferences() == []


def test_schema_v1_database_migrates_without_data_loss(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "knowledge" / "core.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as connection:
        KnowledgeStore._create_schema(connection)
        connection.execute(
            """
            INSERT INTO sources (
                id, kind, external_id, account_id, title, uri, source_path,
                sensitivity, external_policy, trust, status, metadata_json,
                first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, '', '', '', '', 'private', 'allow_scrubbed',
                      'test', 'active', '{}', ?, ?, ?, ?)
            """,
            ("src_v1", "test", "source-1", "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01"),
        )
        connection.execute("PRAGMA user_version = 1")

    migrated = KnowledgeStore(db_path, tmp_path / "data" / "knowledge" / "blobs")

    assert migrated.status()["schema_version"] == 4
    assert migrated.list_sources()[0]["id"] == "src_v1"
    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(user_signals)")}
    assert {"subject_key", "category", "evidence_class", "eligible", "event_key", "sensitivity"} <= columns


def test_sensitive_annotation_requires_trusted_review_for_learning(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    annotation = ContentAnnotationInput(
        target_type="source",
        target_id="src-sensitive",
        labels=["Politics", "ambiguous engagement"],
        context="liked_post",
        stance=ContentStance.SATIRE,
        confidence=0.8,
        eligible_for_preference=True,
        eligible_for_style=True,
    )

    automatic = core.store.upsert_content_annotation(annotation)
    reviewed = core.store.upsert_content_annotation(annotation, trusted_user_review=True)

    assert automatic["labels"] == ["ambiguous_engagement", "politics"]
    assert automatic["eligible_for_preference"] is False
    assert automatic["eligible_for_style"] is False
    assert automatic["requires_review"] is True
    assert reviewed["eligible_for_preference"] is True
    assert reviewed["eligible_for_style"] is True
    assert reviewed["requires_review"] is False


def test_passive_signal_weight_is_capped(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    result = core.store.record_user_signal(
        UserSignalInput(
            subject_key="x:topic:politics",
            category="topic",
            signal_type="liked_post",
            event_key="x:like:123",
            value=1.0,
            weight=10.0,
            actor=ObservationActor.CONNECTOR,
            evidence_class=EvidenceClass.PASSIVE,
        )
    )

    assert result["effective_weight"] == 0.25
    with sqlite3.connect(core.store.db_path) as connection:
        stored_weight = connection.execute(
            "SELECT weight FROM user_signals WHERE id = ?",
            (result["signal_id"],),
        ).fetchone()[0]
    assert stored_weight == 0.25


def test_ingestion_coordinator_is_resumable_and_idempotent_per_account(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    coordinator = IngestionCoordinator(core.store)
    calls = []
    request = IngestionJobInput(
        connector="youtube",
        account_id="primary",
        job_type="activity_sync",
        idempotency_key="window:2026-07-21T12",
        requested_by="scheduler",
    )

    def operation(cursor):
        calls.append(cursor)
        return IngestionResult(stats={"items": 3}, cursor="next-page", cursor_state={"etag": "abc"})

    first = coordinator.run(request, operation=operation)
    duplicate = coordinator.run(request, operation=operation)
    second_account = coordinator.run(
        request.model_copy(update={"account_id": "secondary"}),
        operation=operation,
    )

    assert first["status"] == "completed"
    assert first["stats"] == {"items": 3}
    assert duplicate["deduplicated"] is True
    assert duplicate["should_run"] is False
    assert second_account["status"] == "completed"
    assert len(calls) == 2
    cursor = core.store.get_sync_cursor("youtube", "primary")
    assert cursor is not None
    assert cursor["cursor"] == "next-page"
    assert cursor["state"] == {"etag": "abc"}


def test_failed_ingestion_records_health_without_advancing_cursor(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    coordinator = IngestionCoordinator(core.store)
    initial = IngestionJobInput(
        connector="x",
        account_id="primary",
        job_type="archive_sync",
        idempotency_key="initial",
        requested_by="user",
    )
    coordinator.run(initial, operation=lambda _cursor: IngestionResult(cursor="cursor-1"))

    failing = initial.model_copy(update={"idempotency_key": "next"})
    with pytest.raises(RuntimeError, match="provider unavailable"):
        coordinator.run(
            failing,
            operation=lambda _cursor: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
        )

    cursor = core.store.get_sync_cursor("x", "primary")
    jobs = core.store.list_ingestion_jobs(connector="x")
    assert cursor is not None
    assert cursor["cursor"] == "cursor-1"
    assert cursor["last_error_code"] == "RUNTIMEERROR"
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["error_code"] == "RUNTIMEERROR"

    retried = coordinator.run(
        failing,
        operation=lambda previous: IngestionResult(
            stats={"resumed_from": previous["cursor"]},
            cursor="cursor-2",
        ),
    )
    recovered_cursor = core.store.get_sync_cursor("x", "primary")
    assert retried["status"] == "completed"
    assert retried["attempt_count"] == 2
    assert recovered_cursor is not None
    assert recovered_cursor["cursor"] == "cursor-2"
    assert recovered_cursor["last_error_code"] == ""
