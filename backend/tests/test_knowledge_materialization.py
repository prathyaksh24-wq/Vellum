from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.knowledge.api import router as knowledge_core_router
from agent.knowledge.backup import KnowledgeBackupService
from agent.knowledge.materialization import (
    CANARY_CONFIRMATION,
    MaterializationCanary,
    MaterializationCanaryError,
)
from agent.knowledge.models import MaterializationCanaryRequest
from agent.knowledge.runtime import set_knowledge_core
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore


def build_canary_core(tmp_path: Path) -> KnowledgeCore:
    conversations = tmp_path / "data" / "ui" / "conversations.json"
    conversations.parent.mkdir(parents=True)
    conversations.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "chat-canary",
                        "thread_id": "thread-canary",
                        "title": "Canary architecture",
                        "messages": [
                            {"role": "user", "text": "Keep one source of truth."},
                            {"role": "assistant", "text": "Preserve provenance."},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    vault = tmp_path / "Vault"
    note = vault / "Library" / "Notes" / "local-first.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\nid: note-canary\nsource_trust: user_authored\n---\n"
        "# Local-first note\nCanonical data stays local.\n",
        encoding="utf-8",
    )
    x_item = vault / "Library" / "X" / "example" / "post.md"
    x_item.parent.mkdir(parents=True)
    x_item.write_text(
        "---\nstatus_id: 123456\nsource_trust: imported_archive\n---\n"
        "# Attention post\nAttention is scarce.\n",
        encoding="utf-8",
    )
    wiki = vault / "Knowledge" / "Generated" / "canary.md"
    wiki.parent.mkdir(parents=True)
    wiki.write_text(
        "---\ncanonical_id: insight-canary\ngenerated_by: vellum\n"
        "do_not_reingest: true\n---\n# Generated insight\nDerived projection.\n",
        encoding="utf-8",
    )
    return KnowledgeCore(
        KnowledgeStore(
            tmp_path / "data" / "knowledge" / "core.db",
            tmp_path / "data" / "knowledge" / "blobs",
        ),
        conversations_path=conversations,
        vault_root=vault,
    )


def test_materialization_canary_preview_is_read_only_and_bounded(tmp_path: Path) -> None:
    core = build_canary_core(tmp_path)
    before = core.store.status()["counts"]

    result = core.materialize_canary(MaterializationCanaryRequest())

    assert result["mode"] == "preview"
    assert result["status"] == "ready"
    assert result["ready"] is True
    assert result["passed"] is None
    assert set(result["selection"]) == {
        "conversation",
        "obsidian_source",
        "x_item",
        "wiki_projection",
    }
    assert result["selection"]["wiki_projection"]["do_not_reingest"] is True
    assert core.store.status()["counts"] == before
    assert not (core.store.db_path.parent / "backups").exists()


def test_materialization_canary_requires_literal_confirmation(tmp_path: Path) -> None:
    core = build_canary_core(tmp_path)

    with pytest.raises(MaterializationCanaryError, match=CANARY_CONFIRMATION):
        core.materialize_canary(
            MaterializationCanaryRequest(apply=True, confirmation="confirm")
        )

    assert core.store.status()["counts"]["sources"] == 0


def test_materialization_canary_proves_idempotency_citations_and_recovery(tmp_path: Path) -> None:
    core = build_canary_core(tmp_path)

    result = core.materialize_canary(
        MaterializationCanaryRequest(
            apply=True,
            confirmation=CANARY_CONFIRMATION,
        )
    )

    assert result["status"] == "completed"
    assert result["passed"] is True
    assert all(result["reconciliation"]["gates"].values())
    assert result["reconciliation"]["counts"]["after_first"] == {
        "sources": 3,
        "source_versions": 3,
        "observations": 1,
        "projections": 1,
    }
    assert result["reconciliation"]["counts"]["second_pass_delta"] == {
        "sources": 0,
        "source_versions": 0,
        "observations": 0,
        "projections": 0,
    }
    assert result["passes"]["second"]["conversation"]["versions"] == 0
    assert result["passes"]["second"]["obsidian_source"]["versions"] == 0
    assert result["passes"]["second"]["x_item"]["versions"] == 0
    assert all(item["retrieved"] and item["content_hash"] for item in result["reconciliation"]["citations"])
    projection = core.store.list_projections(target="obsidian")[0]
    assert projection["do_not_reingest"] is True
    assert KnowledgeBackupService(core.store).verify(result["backup"]["path"])["valid"] is True

    restored = KnowledgeBackupService(core.store).restore(
        result["backup"]["path"],
        rollback_destination=tmp_path / "post-canary.zip",
    )

    assert restored["integrity"]["ok"] is True
    assert core.store.status()["counts"]["sources"] == 0
    assert core.store.status()["counts"]["projections"] == 0


def test_materialization_canary_restores_backup_when_a_gate_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = build_canary_core(tmp_path)
    monkeypatch.setattr(
        MaterializationCanary,
        "_citation_checks",
        lambda _self, _selection, _identities: [
            {
                "role": "conversation",
                "source_id": "missing",
                "retrieved": False,
                "content_hash": "",
            }
        ],
    )

    result = core.materialize_canary(
        MaterializationCanaryRequest(
            apply=True,
            confirmation=CANARY_CONFIRMATION,
        )
    )

    assert result["status"] == "rolled_back"
    assert result["passed"] is False
    assert result["reconciliation"]["gates"]["citations_retrievable"] is False
    assert result["rollback"]["integrity"]["ok"] is True
    assert result["rollback"]["counts_match_before"] is True
    assert core.store.status()["counts"]["sources"] == 0
    assert core.store.status()["counts"]["projections"] == 0


def test_materialization_canary_api_is_preview_only_and_lists_projections(
    tmp_path: Path,
) -> None:
    core = build_canary_core(tmp_path)
    result = core.materialize_canary(
        MaterializationCanaryRequest(
            apply=True,
            confirmation=CANARY_CONFIRMATION,
        )
    )
    assert result["passed"] is True
    set_knowledge_core(core)
    app = FastAPI()
    app.include_router(knowledge_core_router, prefix="/api/knowledge")
    try:
        with TestClient(app) as client:
            preview = client.post("/api/knowledge/core/materialization-canary", json={})
            denied = client.post(
                "/api/knowledge/core/materialization-canary",
                json={"apply": True, "confirmation": CANARY_CONFIRMATION},
            )
            projections = client.get("/api/knowledge/core/projections?target=obsidian")
    finally:
        set_knowledge_core(None)

    assert preview.status_code == 200
    assert preview.json()["status"] == "ready"
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "canary_apply_offline"
    assert projections.status_code == 200
    assert projections.json()["count"] == 1
    assert projections.json()["projections"][0]["do_not_reingest"] is True
