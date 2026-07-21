from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.knowledge.api import router as knowledge_core_router
from agent.knowledge.models import (
    BootstrapRequest,
    ContextPackRequest,
    ExternalPolicy,
    ObservationActor,
    ObservationInput,
    ProjectionInput,
    Sensitivity,
    SourceItemInput,
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
