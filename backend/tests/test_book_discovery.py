from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from datetime import UTC, datetime, timedelta
import sqlite3

import httpx
import pytest
from pydantic import ValidationError

from agent.knowledge.book_catalog import BookDiscoveryError, OpenLibraryCatalog
from agent.knowledge.models import (
    BookDiscoveryPolicy, BookDiscoveryRequest, BookMaterializationRequest,
    BookQualityRequest, IngestionJobInput, SourceItemInput,
)
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore


@pytest.fixture(autouse=True)
def catalog_clock(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("agent.knowledge.book_catalog.monotonic", lambda: clock[0])
    monkeypatch.setattr("agent.knowledge.book_discovery.monotonic", lambda: clock[0])
    monkeypatch.setattr(OpenLibraryCatalog, "_next_request_at", 0.0)
    return clock


def catalog_record(number: int = 1, **changes) -> dict:
    return {
        "key": f"/works/OL{number}W",
        "title": "Practical philosophy",
        "author_name": ["Catalog Author"],
        "author_key": ["OL12A"],
        "first_publish_year": 2001,
        "cover_i": 1234,
        "language": ["eng"],
        "isbn": ["9780140449334"],
        "subject": ["philosophy", "ethics"],
        **changes,
    }


def build_core(tmp_path: Path, handler) -> KnowledgeCore:
    return KnowledgeCore(
        KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs"),
        conversations_path=tmp_path / "ui" / "conversations.json",
        vault_root=tmp_path / "unused-vault",
        book_catalog=OpenLibraryCatalog(transport=httpx.MockTransport(handler)),
    )


def request(**changes) -> BookDiscoveryRequest:
    return BookDiscoveryRequest(
        **{
            "user_id": "tenant-one",
            "objective": "user_discovery",
            "query": "philosophy",
            "request_key": "request-one",
            **changes,
        }
    )


def approved(**changes) -> BookDiscoveryPolicy:
    return BookDiscoveryPolicy(
        **{"network_allowed": True, "public_query_approved": True, **changes}
    )


def test_discovery_records_catalog_evidence_without_promoting_book_or_user_knowledge(tmp_path):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"docs": [catalog_record()]})

    core = build_core(tmp_path, handler)
    before = core.store.status()["counts"]
    result = core.discover_books(request(), policy=approved())

    assert result["status"] == "completed"
    assert result["mode"] == "shadow"
    assert len(result["candidates"]) == 1
    book = result["candidates"][0]
    assert book["title"] == "Practical philosophy"
    assert book["metadata_trust"] == "catalog_record"
    assert book["state"] == "discovered"
    assert book["verification"] == "catalog_identity_only"
    assert book["content_available"] is False
    assert book["source_url"] == "https://openlibrary.org/works/OL1W"
    assert book["cover_url"] == "https://covers.openlibrary.org/b/id/1234-M.jpg?default=false"
    assert book["reason_code"] == "catalog_topic_match"
    assert 0 < book["relevance_score"] <= 1
    assert book["objective"] == "user_discovery"
    assert len(calls) == 1
    assert calls[0].url.host == "openlibrary.org"
    assert calls[0].url.params["q"] == "philosophy"
    assert "tenant-one" not in str(calls[0].url)
    after = core.store.status()["counts"]
    for table in ("sources", "user_signals", "observations", "user_learning_candidates",
                  "derived_insights", "book_documents", "active_book_materializations"):
        assert after[table] == before[table]
    receipts = core.store.list_ingestion_jobs(connector="books.discovery")
    assert len(receipts) == 1
    serialized = json.dumps(receipts)
    for private in ("tenant-one", "philosophy", "Practical", "Catalog Author", "request-one"):
        assert private not in serialized
    assert receipts[0]["stats"]["model_tokens"] == 0


@pytest.mark.parametrize("policy", [BookDiscoveryPolicy(), approved(local_only=True),
                                     approved(public_query_approved=False)])
def test_disallowed_policy_never_calls_catalog(tmp_path, policy):
    calls = []
    core = build_core(tmp_path, lambda req: calls.append(req))
    assert core.discover_books(request(), policy=policy)["status"] == "blocked"
    assert not calls
    assert not core.store.list_ingestion_jobs(connector="books.discovery")


@pytest.mark.parametrize("query", ["password=not-for-catalog", "me@example.com", "@privatehandle",
                                   "D:\\Books\\private.epub", "https://private.example/books", "<private>",
                                   "my address is 123 Main Street"])
def test_private_query_never_leaves_machine(tmp_path, query):
    calls = []
    core = build_core(tmp_path, lambda req: calls.append(req))
    assert core.discover_books(request(query=query), policy=approved())["status"] == "blocked"
    assert not calls


def test_classifier_failure_blocks_request(tmp_path, monkeypatch):
    def broken(_):
        raise RuntimeError("private classifier details")
    monkeypatch.setattr("agent.knowledge.book_discovery.classify", broken)
    core = build_core(tmp_path, lambda req: pytest.fail("Unexpected HTTP request"))
    result = core.discover_books(request(), policy=approved())
    assert result["error_code"] == "DISCOVERY_PRIVACY_UNAVAILABLE"
    assert "private classifier" not in json.dumps(result)


def test_successful_replay_does_not_repeat_network_and_survives_restart(tmp_path):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"docs": [catalog_record()]})
    core = build_core(tmp_path, handler)
    first = core.discover_books(request(), policy=approved())
    restarted = build_core(tmp_path, handler)
    again = restarted.discover_books(request(), policy=approved())
    assert again["replayed"] is True
    assert again["candidates"] == first["candidates"]
    assert len(calls) == 1


def test_objectives_and_tenants_are_separate_without_becoming_user_signals(tmp_path, catalog_clock):
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": [catalog_record()]}))
    results = []
    for user, objective in [("one", "user_discovery"), ("one", "vellum_exploration"), ("two", "user_discovery")]:
        catalog_clock[0] += 2
        results.append(core.discover_books(request(user_id=user, objective=objective), policy=approved()))
    assert len({r["job_id"] for r in results}) == 3
    assert len({r["candidates"][0]["candidate_id"] for r in results}) == 3
    assert not core.list_book_discovery_candidates(user_id="two", objective="vellum_exploration")
    assert core.store.status()["counts"]["user_signals"] == 0


def test_dismissal_is_tenant_wide_survives_refresh_and_does_not_reject_topic(tmp_path, catalog_clock):
    records = [catalog_record()]
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": records}))
    first = core.discover_books(request(), policy=approved())
    candidate_id = first["candidates"][0]["candidate_id"]
    assert not core.dismiss_book_discovery_candidate(user_id="other", candidate_id=candidate_id)
    assert core.dismiss_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)
    assert not core.discover_books(request(), policy=approved())["candidates"]
    records.append(catalog_record(2, title="Philosophy of science"))
    for objective in ("user_discovery", "vellum_exploration"):
        catalog_clock[0] += 2
        result = core.discover_books(request(objective=objective, request_key="new"), policy=approved())
        assert [item["work_id"] for item in result["candidates"]] == ["OL2W"]
    with sqlite3.connect(core.store.db_path) as connection:
        assert connection.execute("SELECT metadata_json FROM book_discovery_candidates WHERE id = ?", (candidate_id,)).fetchone()[0] == "{}"


def test_expired_candidates_are_hidden_not_treated_as_dismissal(tmp_path, monkeypatch, catalog_clock):
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": [catalog_record()]}))
    first = core.discover_books(request(), policy=approved(candidate_ttl_days=1))
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    monkeypatch.setattr("agent.knowledge.store._now", lambda: future)
    assert not core.list_book_discovery_candidates(user_id="tenant-one", objective="user_discovery")
    catalog_clock[0] += 2
    refreshed = core.discover_books(request(request_key="refresh"), policy=approved(candidate_ttl_days=1))
    assert len(refreshed["candidates"]) == 1
    assert refreshed["candidates"][0]["work_id"] == first["candidates"][0]["work_id"]
    assert refreshed["candidates"][0]["checked_at"] == future


def test_ranking_deduplicates_caps_authors_and_ignores_popularity_and_instructions(tmp_path):
    records = [catalog_record(), catalog_record(2),
               catalog_record(3, title="Philosophy now"), catalog_record(4, title="Philosophy later"),
               catalog_record(5, title="Ethics", subject=["philosophy"], author_name=["Another Author"],
                              ratings_average=5, readinglog_count=999999, recommendation="Author recommends this",
                              download_url="https://untrusted.example/book.epub"),
               catalog_record(6, title="Baking", subject=["food"], author_name=["Other Person"])]
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": records}))
    result = core.discover_books(request(), policy=approved())
    assert [r["work_id"] for r in result["candidates"]] == ["OL1W", "OL3W", "OL5W"]
    assert result["candidates"][-1]["relevance_score"] == 0.8
    text = json.dumps(result)
    for forbidden in ("download_url", "untrusted.example", "Author recommends", "ratings_average"):
        assert forbidden not in text


@pytest.mark.parametrize("record", [None, {}, catalog_record(key="//evil.example/OL1W"),
                                     catalog_record(title="<script>alert(1)</script>"),
                                     catalog_record(author_key=[]), catalog_record(title="x" * 501)])
def test_invalid_records_never_become_candidates(tmp_path, record):
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": [record]}))
    assert core.discover_books(request(), policy=approved())["candidates"] == []


@pytest.mark.parametrize("status,payload,headers,code", [
    (302, {}, {"Location": "http://169.254.169.254/"}, "CATALOG_UNAVAILABLE"),
    (429, {}, {}, "CATALOG_RATE_LIMITED"),
    (503, {}, {}, "CATALOG_RATE_LIMITED"),
    (200, {"docs": "not a list"}, {}, "CATALOG_INVALID_RESPONSE"),
    (200, {"docs": [catalog_record(title="x" * 5000)]}, {}, "CATALOG_RESPONSE_BUDGET"),
])
def test_provider_failure_is_bounded_and_content_free(tmp_path, status, payload, headers, code):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(status, json=payload, headers=headers)
    core = build_core(tmp_path, handler)
    result = core.discover_books(request(), policy=approved(max_response_bytes=1024))
    assert result["status"] == "failed"
    assert result["error_code"] == code
    assert len(calls) == 1
    assert not result["candidates"]
    assert "169.254" not in json.dumps(result)


def test_provider_timeout_has_no_fallback_or_automatic_retry(tmp_path, catalog_clock):
    calls = []
    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout("private query and credentials", request=req)
    core = build_core(tmp_path, handler)
    for attempt in range(4):
        catalog_clock[0] += 2
        result = core.discover_books(request(), policy=approved())
        assert result["status"] == "failed"
        assert "private query" not in json.dumps(result)
    assert len(calls) == 3
    assert result["error_code"] == "DISCOVERY_RETRY_BUDGET"


def test_deadline_exhaustion_publishes_nothing(tmp_path, catalog_clock):
    def handler(_):
        catalog_clock[0] += 20
        return httpx.Response(200, json={"docs": [catalog_record()]} )
    core = build_core(tmp_path, handler)
    result = core.discover_books(request(), policy=approved())
    assert result["error_code"] == "DISCOVERY_DEADLINE"
    assert core.store.status()["counts"]["book_discovery_candidates"] == 0


def test_rate_limit_is_shared_between_core_instances(tmp_path):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"docs": [catalog_record()]})
    first = build_core(tmp_path / "one", handler)
    second = build_core(tmp_path / "two", handler)
    assert first.discover_books(request(), policy=approved())["status"] == "completed"
    assert second.discover_books(request(), policy=approved())["error_code"] == "CATALOG_RATE_LIMITED"
    assert len(calls) == 1


def test_storage_cap_includes_dismissal_tombstones(tmp_path, catalog_clock):
    records = [catalog_record()]
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": records}))
    first = core.discover_books(request(), policy=approved(max_retained_candidates=1))
    core.dismiss_book_discovery_candidate(user_id="tenant-one", candidate_id=first["candidates"][0]["candidate_id"])
    records[:] = [catalog_record(2, title="Another philosophy")]
    catalog_clock[0] += 2
    assert not core.discover_books(request(request_key="new"), policy=approved(max_retained_candidates=1))["candidates"]
    assert core.store.status()["counts"]["book_discovery_candidates"] == 1


def test_concurrent_duplicate_runs_execute_only_once(tmp_path):
    entered, release = Event(), Event()
    calls = []
    def handler(req):
        calls.append(req)
        entered.set()
        assert release.wait(10)
        return httpx.Response(200, json={"docs": [catalog_record()]})
    core = build_core(tmp_path, handler)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(core.discover_books, request(), policy=approved())
        try:
            assert entered.wait(10)
            second = core.discover_books(request(), policy=approved())
            assert second["status"] == "running"
            assert second["replayed"]
        finally:
            release.set()
        assert first.result()["status"] == "completed"
    assert len(calls) == 1


def test_candidate_publication_and_job_completion_are_atomic(tmp_path, monkeypatch):
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": [catalog_record()]}))
    def fail(*args, **kwargs):
        raise RuntimeError("private storage error")
    monkeypatch.setattr(core.store, "_complete_ingestion_job", fail, raising=False)
    result = core.discover_books(request(), policy=approved())
    assert result["status"] == "failed"
    assert core.store.status()["counts"]["book_discovery_candidates"] == 0


def test_invalid_policy_and_unknown_objective_are_rejected():
    with pytest.raises(ValidationError):
        BookDiscoveryPolicy(network_allowed="true")
    with pytest.raises(ValidationError):
        request(objective="acquire")
    with pytest.raises(ValidationError):
        request(max_candidates=100000)


def test_ready_library_books_are_excluded_on_discovery_and_later_reads(tmp_path, catalog_clock):
    from test_book_documents import (
        CleanScanner, FixedBookEmbedder, RecordingBookIndex, import_and_construct, structured_epub_bytes,
    )
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"docs": [catalog_record(
            title="Structured Fixture", author_name=["Example Author"],
        )]})
    core = KnowledgeCore(
        KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs"),
        conversations_path=tmp_path / "ui" / "conversations.json", vault_root=tmp_path / "unused",
        book_catalog=OpenLibraryCatalog(transport=httpx.MockTransport(handler)),
        book_malware_scanner=CleanScanner(), book_embedding_provider=FixedBookEmbedder(),
        book_retrieval_index=RecordingBookIndex(),
    )
    assert len(core.discover_books(request(), policy=approved())["candidates"]) == 1
    imported, document = import_and_construct(core, structured_epub_bytes(), user_id="tenant-one", local_only=True)
    fields = {"user_id": "tenant-one", "import_id": imported.import_id,
              "run_id": imported.run_id, "document_id": document.document_id}
    core.evaluate_book_document_quality(BookQualityRequest(**fields))
    core.materialize_book_document(BookMaterializationRequest(**fields))
    assert core.store.list_active_book_materialization_records(user_id="tenant-one")
    assert not core.list_book_discovery_candidates(user_id="tenant-one", objective="user_discovery")
    assert not core.discover_books(request(), policy=approved())["candidates"]
    catalog_clock[0] += 2
    assert not core.discover_books(request(request_key="refresh"), policy=approved())["candidates"]
    catalog_clock[0] += 2
    other = core.discover_books(request(user_id="other"), policy=approved())
    assert len(other["candidates"]) == 1
    assert all(req.url.params["q"] == "philosophy" for req in calls)
    assert all("Structured" not in str(req.url) and "Example" not in str(req.url) for req in calls)


def test_v12_upgrade_preserves_existing_knowledge(tmp_path):
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    source = store.upsert_source(SourceItemInput(kind="test", external_id="existing", content="existing knowledge"))
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("DROP TABLE book_discovery_candidates")
        connection.execute("PRAGMA user_version = 12")
    upgraded = KnowledgeStore(store.db_path, tmp_path / "blobs")
    assert upgraded.status()["schema_version"] == 13
    assert upgraded.status()["counts"]["sources"] == 1
    assert upgraded.status()["counts"]["book_discovery_candidates"] == 0
    assert upgraded.integrity_check()["ok"]
    assert source["source_id"]


def test_simultaneous_job_claims_have_one_owner(tmp_path):
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    gate = Barrier(6)
    def claim(_):
        gate.wait(timeout=10)
        return store.start_ingestion_job(IngestionJobInput(
            connector="books.discovery", account_id="tenant-hash", job_type="metadata_discovery",
            idempotency_key="same-request", requested_by="books.discovery",
        ))
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(claim, range(6)))
    assert sum(result["should_run"] for result in results) == 1
    assert len({result["id"] for result in results}) == 1


def test_untrusted_provider_error_details_are_not_receipts(tmp_path):
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": []}))
    class BrokenProvider:
        def search(self, *args, **kwargs):
            raise BookDiscoveryError("private@example.com D:\\Private\\book.epub")
    core.book_discovery.catalog = BrokenProvider()
    result = core.discover_books(request(), policy=approved())
    assert result["error_code"] == "DISCOVERY_FAILED"
    text = json.dumps(core.store.list_ingestion_jobs(connector="books.discovery"))
    assert "PRIVATE" not in text and "private" not in text


def test_catalog_identity_refresh_keeps_deduplication_and_dismissal_consistent(tmp_path, catalog_clock):
    records = [catalog_record()]
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": records}))
    first = core.discover_books(request(), policy=approved())["candidates"][0]
    records[:] = [catalog_record(title="Updated philosophy")]
    catalog_clock[0] += 2
    refreshed = core.discover_books(request(request_key="refresh-title"), policy=approved())["candidates"][0]
    assert refreshed["candidate_id"] == first["candidate_id"]
    records[:] = [catalog_record(2, title="Updated philosophy")]
    catalog_clock[0] += 2
    moved = core.discover_books(request(request_key="refresh-work"), policy=approved())["candidates"][0]
    assert moved["candidate_id"] == first["candidate_id"]
    assert core.store.status()["counts"]["book_discovery_candidates"] == 1
    core.dismiss_book_discovery_candidate(user_id="tenant-one", candidate_id=moved["candidate_id"])
    records[:] = [catalog_record(2, title="Renamed philosophy")]
    catalog_clock[0] += 2
    assert not core.discover_books(request(request_key="after-dismiss"), policy=approved())["candidates"]


def test_v13_migration_recovers_if_ddl_exists_before_version_marker(tmp_path):
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("PRAGMA user_version = 12")
    resumed = KnowledgeStore(store.db_path, tmp_path / "blobs")
    assert resumed.status()["schema_version"] == 13
    assert resumed.integrity_check()["ok"]


def test_old_identity_can_be_reused_without_colliding_with_refreshed_candidate_id(tmp_path, catalog_clock):
    records = [catalog_record()]
    core = build_core(tmp_path, lambda _: httpx.Response(200, json={"docs": records}))
    first = core.discover_books(request(), policy=approved())["candidates"][0]
    records[:] = [catalog_record(title="Corrected philosophy")]
    catalog_clock[0] += 2
    core.discover_books(request(request_key="correction"), policy=approved())
    records[:] = [catalog_record(2)]
    catalog_clock[0] += 2
    other = core.discover_books(request(request_key="distinct-work"), policy=approved())
    assert other["status"] == "completed"
    assert other["candidates"][0]["candidate_id"] != first["candidate_id"]
    assert core.store.status()["counts"]["book_discovery_candidates"] == 2


@pytest.mark.parametrize("provider_fails", [False, True])
def test_reclaimed_attempt_cannot_publish_or_fail_new_owner(tmp_path, monkeypatch, provider_fails):
    claims = []
    def handler(req):
        job = core.store.list_ingestion_jobs(connector="books.discovery")[0]
        with sqlite3.connect(core.store.db_path) as connection:
            connection.execute("UPDATE ingestion_jobs SET lease_expires_at = ? WHERE id = ?",
                               ("2000-01-01T00:00:00+00:00", job["id"]))
        reclaimed = original_start(claims[0])
        assert reclaimed["should_run"] and reclaimed["attempt_count"] == 2
        if provider_fails:
            raise httpx.ReadTimeout("private provider failure", request=req)
        return httpx.Response(200, json={"docs": [catalog_record()]})
    core = build_core(tmp_path, handler)
    original_start = core.store.start_ingestion_job
    def capture(item):
        claims.append(item)
        return original_start(item)
    monkeypatch.setattr(core.store, "start_ingestion_job", capture)
    result = core.discover_books(request(), policy=approved())
    assert result["status"] == "superseded"
    assert result["error_code"] == "DISCOVERY_LEASE_LOST"
    job = core.store.list_ingestion_jobs(connector="books.discovery")[0]
    assert job["status"] == "running" and job["attempt_count"] == 2
    assert core.store.status()["counts"]["book_discovery_candidates"] == 0
