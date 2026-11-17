import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.provider_extensions import MemoryProviderExtensionManager
from agent.memory.resolved import ResolvedQuestionsCache
from agent.memory.retention import growth_view, run_retention, snapshot_growth
from agent.tools.capabilities.memory_service import MemoryCapabilityService

T0 = datetime(2026, 8, 1, 12, tzinfo=UTC)


class FakeHindsight:
    id = "hindsight"
    name = "Hindsight"
    provider_type = "knowledge_graph"
    optional = True
    capabilities: list[str] = []

    def __init__(self) -> None:
        self.forgotten: list[str] = []

    def is_enabled(self):
        return True

    def is_configured(self):
        return True

    def health(self):
        return True

    def setup_notes(self):
        return ""

    def prefetch(self, *a, **k):
        return ""

    def sync_turn(self, *a, **k):
        return None

    def retain_memory(self, memory):
        return f"vellum-memory-{memory['id']}"

    def forget_document(self, doc_id):
        self.forgotten.append(doc_id)

    def shutdown(self):
        return None


@pytest.fixture
def world(tmp_path: Path):
    provider = FakeHindsight()
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    fts = FTS5Memory(tmp_path / "fts5.db")
    orchestrator = MemoryOrchestrator(
        fts5=fts,
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
        provider_extensions=MemoryProviderExtensionManager([provider]),
    )

    def backdate(memory_id: int, when: datetime) -> None:
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("UPDATE memory_items SET created_at = ?, updated_at = ? WHERE id = ?",
                         (when.isoformat(), when.isoformat(), memory_id))

    return orchestrator, store, fts, provider, backdate


def _add(store, text, *, origin, kind="fact", pinned=False):
    memory_id = store.add_pending(kind=kind, text=text, source_thread_id="t", confidence=0.7, origin=origin)
    store.promote(memory_id)
    if pinned:
        store.pin(memory_id)
    return memory_id


def test_inferred_memories_archive_at_30_days_and_stay_recallable(world):
    orchestrator, store, _fts, _provider, backdate = world
    inferred = _add(store, "Seems to follow Formula 1 closely.", origin="inferred")
    stated = _add(store, "Prefers concise answers.", origin="stated", kind="preference")
    backdate(inferred, T0)
    backdate(stated, T0)

    assert run_retention(orchestrator, now=T0 + timedelta(days=29))["archived"] == 0
    result = run_retention(orchestrator, now=T0 + timedelta(days=31))
    assert result["archived"] == 1
    assert store.get_memory(inferred)["status"] == "archived"
    assert store.get_memory(stated)["status"] == "saved"


def test_memories_in_use_are_not_archived(world):
    orchestrator, store, _fts, _provider, backdate = world
    inferred = _add(store, "Often asks about chess openings.", origin="inferred")
    backdate(inferred, T0)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE memory_items SET last_used_at = ? WHERE id = ?",
                     ((T0 + timedelta(days=20)).isoformat(), inferred))
    assert run_retention(orchestrator, now=T0 + timedelta(days=31))["archived"] == 0


def test_at_90_days_inferred_memories_are_distilled_then_gone_everywhere(world):
    orchestrator, store, fts, provider, backdate = world
    old = [_add(store, f"Watched {name} documentaries.", origin="inferred") for name in ("space", "ocean")]
    pinned = _add(store, "Watched a nature documentary series.", origin="inferred", pinned=True)
    correction = _add(store, "Check the source before quoting a statistic.", origin="inferred", kind="correction")
    for memory_id in [*old, pinned, correction]:
        backdate(memory_id, T0)
        store.sync_mark(memory_id, "hindsight", state="synced")
        fts.add_document(content=f"Saved memory {memory_id}", thread_id="t", source_paths=[f"memory:{memory_id}"])
    fts.add_document(content="old turn about documentaries", thread_id="t", created=T0.isoformat())
    fts.add_document(content="recent turn", thread_id="t", created=(T0 + timedelta(days=85)).isoformat())
    store.record_provider_doc("vellum-turn-old", "hindsight", "turn")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE memory_provider_docs SET created_at = ?", (T0.isoformat(),))

    run_retention(orchestrator, now=T0 + timedelta(days=31), distiller=lambda topic, facts: "You like documentaries.")
    assert run_retention(orchestrator, now=T0 + timedelta(days=89))["deleted"] == 0
    result = run_retention(orchestrator, now=T0 + timedelta(days=91),
                           distiller=lambda topic, facts: "You like documentaries.")

    assert result["deleted"] == 2 and result["digests"] == 1
    for memory_id in old:
        with pytest.raises(KeyError):
            store.get_memory(memory_id)
    assert store.get_memory(pinned)["status"] == "saved"
    assert store.get_memory(correction)["status"] == "saved"
    digest = next(item for item in store.list_saved() if item["origin"] == "digest")
    assert digest["text"] == "Earlier (Aug 2026): You like documentaries."

    audit = " ".join(row["detail"] for row in store.audit_log(limit=200))
    assert "space documentaries" not in audit and "ocean documentaries" not in audit
    contents = " ".join(doc["content"] for doc in fts.recent_documents(limit=50))
    assert "old turn" not in contents and "recent turn" in contents
    assert f"Saved memory {old[0]}" not in contents and f"Saved memory {pinned}" in contents

    assert orchestrator.flush_provider_sync()["forgotten"] == 2
    assert sorted(provider.forgotten) == sorted(["vellum-turn-old", *(f"vellum-memory-{i}" for i in old)])


def test_retention_switch_off_changes_nothing(world):
    orchestrator, store, _fts, _provider, backdate = world
    inferred = _add(store, "Seems to like hiking trails.", origin="inferred")
    backdate(inferred, T0)
    store.update_settings({"auto_archive_enabled": False})
    assert run_retention(orchestrator, now=T0 + timedelta(days=200))["skipped"] == "retention_off"
    assert store.get_memory(inferred)["status"] == "saved"


def test_growth_tracks_day_number_known_facts_and_milestones(world):
    _orchestrator, store, _fts, _provider, backdate = world
    first = _add(store, "Prefers concise answers.", origin="stated", kind="preference")
    backdate(first, T0)
    day1 = snapshot_growth(store, now=T0)
    assert day1["counts"]["known"] == 1
    assert {m["kind"] for m in day1["milestones"]} >= {"count", "topic"}

    later = _add(store, "Check logs before guessing a cause.", origin="stated", kind="correction")
    backdate(later, T0 + timedelta(days=3))
    day4 = snapshot_growth(store, now=T0 + timedelta(days=3))
    assert "Took your first correction on board" in [m["text"] for m in day4["milestones"]]

    view = growth_view(store, now=T0 + timedelta(days=3))
    assert view["day_number"] == 4 and view["first_day"] == "2026-08-01"
    assert [point["known"] for point in view["series"]] == [1, 2]
    assert view["milestones"][0]["day_number"] == 4
