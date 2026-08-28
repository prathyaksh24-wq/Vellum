from __future__ import annotations

from pathlib import Path
import json
import sqlite3

import httpx
import pytest

from agent.knowledge.book_catalog import BookDiscoveryError, OpenLibraryCatalog, normalize_catalog_record
from agent.knowledge.models import (
    BookDiscoveryPolicy,
    BookDiscoveryRequest,
    BookDiscoveryVerificationRequest,
)
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore


@pytest.fixture(autouse=True)
def catalog_clock(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("agent.knowledge.book_catalog.monotonic", lambda: clock[0])
    monkeypatch.setattr("agent.knowledge.book_discovery.monotonic", lambda: clock[0])
    monkeypatch.setattr("agent.knowledge.book_catalog.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(OpenLibraryCatalog, "_next_request_at", 0.0)
    return clock


def _catalog_record() -> dict:
    return {
        "key": "/works/OL1W",
        "title": "Practical philosophy",
        "author_name": ["Catalog Author"],
        "author_key": ["OL12A"],
        "language": ["eng"],
        "cover_i": 1234,
        "subject": ["philosophy"],
    }


def _core(tmp_path: Path, handler) -> KnowledgeCore:
    return KnowledgeCore(
        KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs"),
        conversations_path=tmp_path / "ui" / "conversations.json",
        vault_root=tmp_path / "vault",
        book_catalog=OpenLibraryCatalog(transport=httpx.MockTransport(handler)),
    )


def test_verification_publishes_verified_shadow_candidate(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search.json":
            return httpx.Response(200, json={"docs": [_catalog_record()]})
        if request.url.path == "/works/OL1W.json":
            return httpx.Response(
                200,
                json={
                    "key": "/works/OL1W",
                    "title": "Practical philosophy",
                    "authors": [{"author": {"key": "/authors/OL12A"}}],
                },
            )
        if request.url.path == "/works/OL1W/editions.json":
            return httpx.Response(
                200,
                json={
                    "entries": [{
                        "key": "/books/OL2M",
                        "title": "Practical philosophy",
                        "authors": [{"key": "/authors/OL12A"}],
                        "works": [{"key": "/works/OL1W"}],
                        "languages": [{"key": "/languages/eng"}],
                        "isbn_13": ["9780140449334"],
                        "covers": [4321],
                    }],
                },
            )
        if request.url.path == "/authors/OL12A.json":
            return httpx.Response(200, json={"key": "/authors/OL12A", "name": "Catalog Author"})
        if request.url.host == "covers.openlibrary.org":
            assert request.method == "HEAD"
            return httpx.Response(200, headers={"content-type": "image/jpeg"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    core = _core(tmp_path, handler)
    discovered = core.discover_books(
        BookDiscoveryRequest(
            user_id="tenant-one",
            objective="user_discovery",
            query="philosophy",
            request_key="discover-one",
        ),
        policy=BookDiscoveryPolicy(network_allowed=True, public_query_approved=True),
    )
    candidate_id = discovered["candidates"][0]["candidate_id"]

    result = core.verify_book_discovery_candidate(
        BookDiscoveryVerificationRequest(
            user_id="tenant-one",
            candidate_id=candidate_id,
            request_key="verify-one",
        ),
        policy=BookDiscoveryPolicy(network_allowed=True, public_query_approved=True),
    )

    assert result["status"] == "completed", result
    assert result["mode"] == "shadow"
    assert result["candidates"][0]["state"] == "verified"
    assert result["candidates"][0]["verification"] == "verified"
    assert result["metadata"]["cover_status"] == "available"


def _documents():
    return {
        "/search.json": {"docs": [_catalog_record()]},
        "/works/OL1W.json": {
            "key": "/works/OL1W", "title": "Practical philosophy",
            "authors": [{"author": {"key": "/authors/OL12A"}}],
        },
        "/works/OL1W/editions.json": {"entries": [{
            "key": "/books/OL2M", "title": "Practical philosophy",
            "works": [{"key": "/works/OL1W"}],
            "authors": [{"key": "/authors/OL12A"}],
            "languages": [{"key": "/languages/eng"}],
            "isbn_13": ["9780140449334"], "covers": [4321],
        }]},
        "/authors/OL12A.json": {"key": "/authors/OL12A", "name": "Catalog Author"},
    }


def _handler(documents, calls):
    def handle(request):
        calls.append(request)
        assert request.url.host in {"openlibrary.org", "covers.openlibrary.org"}
        if request.url.host == "covers.openlibrary.org":
            assert request.method == "HEAD"
            # HEAD describes the image size; it does not download the body.
            return httpx.Response(200, headers={"content-type": "image/jpeg", "content-length": "900000"})
        value = documents[request.url.path]
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    return handle


def _discovered(core):
    result = core.discover_books(BookDiscoveryRequest(
        user_id="tenant-one", objective="user_discovery", query="philosophy", request_key="discover-one",
    ), policy=_approved())
    assert result["status"] == "completed", result
    return result["candidates"][0]["candidate_id"]


def _approved(**changes):
    return BookDiscoveryPolicy(**{"network_allowed": True, "public_query_approved": True, **changes})


def _verify(core, candidate_id, **changes):
    request = BookDiscoveryVerificationRequest(**{
        "user_id": "tenant-one", "candidate_id": candidate_id, "request_key": "verify-one", **changes,
    })
    return core.verify_book_discovery_candidate(request, policy=_approved())


def test_verified_result_survives_restart_without_network_or_learning(tmp_path):
    calls = []
    handle = _handler(_documents(), calls)
    core = _core(tmp_path, handle)
    candidate_id = _discovered(core)
    before = core.store.status()["counts"]
    result = _verify(core, candidate_id)
    assert result["status"] == "completed", result
    book = result["candidates"][0]
    assert book["cover_url"].endswith("4321-M.jpg?default=false")
    assert book["cover_id"] == 4321
    assert book["content_available"] is False
    assert result["metadata"]["cover_verification"] == "availability_only"
    assert len(core.list_book_discovery_candidates(user_id="tenant-one", objective="user_discovery")) == 1
    assert len(calls) == 5
    assert _verify(_core(tmp_path, handle), candidate_id)["replayed"] is True
    assert len(calls) == 5
    after = core.store.status()["counts"]
    for table in ("sources", "observations", "user_signals", "user_learning_candidates", "derived_insights", "book_documents"):
        assert after[table] == before[table]
    receipts = json.dumps(core.store.list_ingestion_jobs(connector="books.discovery"))
    for private in ("tenant-one", "philosophy", "Catalog Author", candidate_id):
        assert private not in receipts


@pytest.mark.parametrize("field,value", [
    ("title", "Different book"), ("works", [{"key": "/works/OL999W"}]),
    ("authors", [{"key": "/authors/OL99A"}]), ("languages", []),
    ("isbn_13", ["9780140449335"]), ("key", "/books/../../secrets"),
])
def test_edition_conflicts_remain_unverified_with_durable_reason(tmp_path, field, value):
    docs, calls = _documents(), []
    docs["/works/OL1W/editions.json"]["entries"][0][field] = value
    core = _core(tmp_path, _handler(docs, calls))
    candidate_id = _discovered(core)
    result = _verify(core, candidate_id)
    assert result["status"] == "unverified", result
    item = core.store.get_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)
    assert item["state"] == "discovered"
    assert item["verification_metadata"]["reason_code"] == "DISCOVERY_VERIFICATION_MISMATCH"
    assert _verify(core, candidate_id)["replayed"] is True
    assert len(calls) == 3


@pytest.mark.parametrize("response,code", [
    (httpx.Response(302, headers={"location": "http://127.0.0.1/private"}), "REDIRECT"),
    (httpx.Response(429, json={}), "RATE_LIMITED"),
    (httpx.Response(404, json={}), "UNAVAILABLE"),
    (httpx.Response(500, json={}), "UNAVAILABLE"),
    (httpx.Response(200, content=b"not json", headers={"content-type": "application/json"}), "INVALID_RESPONSE"),
    (httpx.Response(200, stream=httpx.ByteStream(b""), headers={"content-encoding": "gzip"}), "ENCODING_UNSUPPORTED"),
    (httpx.Response(200, json={}, headers={"content-length": "999999"}), "RESPONSE_BUDGET"),
])
def test_provider_errors_fail_closed_without_following_urls(tmp_path, response, code):
    docs, calls = _documents(), []
    docs["/works/OL1W.json"] = response
    core = _core(tmp_path, _handler(docs, calls))
    candidate_id = _discovered(core)
    result = _verify(core, candidate_id)
    assert result["error_code"] == "DISCOVERY_VERIFICATION_" + code, result
    assert len(calls) == 2
    assert core.store.get_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)["state"] == "discovered"


@pytest.mark.parametrize("change", ["dismiss", "expire", "refresh", "lease"])
def test_inflight_verification_cannot_overwrite_changed_candidate(tmp_path, change):
    calls = []
    handle = _handler(_documents(), calls)
    candidate_id = ""
    def intercept(request):
        if request.method == "HEAD":
            if change == "dismiss":
                core.dismiss_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)
            else:
                with sqlite3.connect(tmp_path / "core.db") as db:
                    if change == "expire":
                        db.execute("UPDATE book_discovery_candidates SET expires_at = '2000-01-01T00:00:00+00:00'")
                    elif change == "refresh":
                        db.execute("UPDATE book_discovery_candidates SET checked_at = '2090-01-01T00:00:00+00:00'")
                    else:
                        db.execute("UPDATE ingestion_jobs SET attempt_count = attempt_count + 1 WHERE job_type = 'metadata_verification'")
        return handle(request)
    core = _core(tmp_path, intercept)
    candidate_id = _discovered(core)
    result = _verify(core, candidate_id)
    assert result["status"] == "superseded", result
    assert core.store.get_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)["state"] != "verified"


def test_expired_verified_and_dismissed_candidates_are_not_replayed(tmp_path):
    calls = []
    core = _core(tmp_path, _handler(_documents(), calls))
    candidate_id = _discovered(core)
    assert _verify(core, candidate_id)["status"] == "completed"
    assert _verify(core, candidate_id, user_id="another-user")["error_code"] == "DISCOVERY_CANDIDATE_NOT_FOUND"
    with sqlite3.connect(tmp_path / "core.db") as db:
        db.execute("UPDATE book_discovery_candidates SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert _verify(core, candidate_id)["error_code"] == "DISCOVERY_CANDIDATE_EXPIRED"
    assert core.dismiss_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)
    assert _verify(core, candidate_id)["error_code"] == "DISCOVERY_CANDIDATE_INELIGIBLE"
    assert len(calls) == 5


@pytest.mark.parametrize("policy", [BookDiscoveryPolicy(), _approved(local_only=True), _approved(public_query_approved=False)])
def test_verification_permission_is_required_before_candidate_lookup(tmp_path, policy):
    core = _core(tmp_path, lambda _: pytest.fail("Network denied"))
    result = core.verify_book_discovery_candidate(BookDiscoveryVerificationRequest(
        user_id="tenant-one", candidate_id="book-discovery_" + "0" * 32, request_key="verify-one",
    ), policy=policy)
    assert result["status"] == "blocked"
    assert core.store.list_ingestion_jobs(connector="books.discovery") == []


def test_total_response_and_pacing_deadline_are_bounded(catalog_clock):
    calls = []
    catalog = OpenLibraryCatalog(transport=httpx.MockTransport(_handler(_documents(), calls)))
    candidate = normalize_catalog_record(_catalog_record())
    with pytest.raises(BookDiscoveryError, match="RESPONSE_BUDGET"):
        catalog.verify(candidate, max_bytes=300, deadline=catalog_clock[0] + 20)
    OpenLibraryCatalog._next_request_at = catalog_clock[0] + 10
    count = len(calls)
    with pytest.raises(BookDiscoveryError, match="DEADLINE"):
        catalog.verify(candidate, max_bytes=262144, deadline=catalog_clock[0] + 1)
    assert len(calls) == count


@pytest.mark.parametrize("count", [3, 4])
def test_author_verification_has_a_six_request_ceiling(catalog_clock, count):
    docs, calls = _documents(), []
    record = _catalog_record()
    record["author_key"] = [f"OL{i}A" for i in range(1, count + 1)]
    record["author_name"] = [f"Author {i}" for i in range(1, count + 1)]
    links = [{"key": f"/authors/{key}"} for key in record["author_key"]]
    docs["/works/OL1W.json"]["authors"] = links
    docs["/works/OL1W/editions.json"]["entries"][0]["authors"] = links
    for link, name in zip(links, record["author_name"]):
        docs[link["key"] + ".json"] = {**link, "name": name}
    catalog = OpenLibraryCatalog(transport=httpx.MockTransport(_handler(docs, calls)))
    result = catalog.verify(normalize_catalog_record(record), max_bytes=262144, deadline=catalog_clock[0] + 20)
    assert result["verified"] is (count == 3)
    assert len(calls) == (6 if count == 3 else 0)


def test_retry_budget_stops_network_after_three_explicit_failures(tmp_path):
    docs, calls = _documents(), []
    docs["/works/OL1W.json"] = httpx.Response(503, json={})
    core = _core(tmp_path, _handler(docs, calls))
    candidate_id = _discovered(core)
    for _ in range(3):
        assert _verify(core, candidate_id)["error_code"] == "DISCOVERY_VERIFICATION_RATE_LIMITED"
    assert _verify(core, candidate_id)["error_code"] == "DISCOVERY_RETRY_BUDGET"
    assert len(calls) == 4


def test_candidate_and_receipt_publication_roll_back_together(tmp_path, monkeypatch):
    core = _core(tmp_path, _handler(_documents(), []))
    candidate_id = _discovered(core)
    def fail_receipt(*args, **kwargs):
        raise RuntimeError("private transaction details")
    monkeypatch.setattr(core.store, "_complete_ingestion_job", fail_receipt)
    result = _verify(core, candidate_id)
    assert result["error_code"] == "DISCOVERY_VERIFICATION_FAILED"
    assert "private" not in json.dumps(result)
    assert core.store.get_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)["state"] == "discovered"


def test_migration_failure_rolls_back_original_table(tmp_path):
    core = _core(tmp_path, _handler(_documents(), []))
    candidate_id = _discovered(core)
    with sqlite3.connect(tmp_path / "core.db") as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'book_discovery_candidates'").fetchone()[0]
        db.execute("DROP INDEX book_discovery_scope_state")
        db.execute("ALTER TABLE book_discovery_candidates RENAME TO preserved")
        db.execute(sql.replace("'discovered', 'verified',", "'discovered',"))
        db.execute("INSERT INTO book_discovery_candidates SELECT * FROM preserved")
        db.execute("DROP TABLE preserved")
        db.execute("PRAGMA user_version = 13")
    class InterruptedMigration(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql == "DROP TABLE book_discovery_candidates":
                raise sqlite3.OperationalError("simulated interruption")
            return super().execute(sql, parameters)
    db = sqlite3.connect(tmp_path / "core.db", factory=InterruptedMigration)
    try:
        with pytest.raises(sqlite3.OperationalError, match="simulated interruption"):
            KnowledgeStore._migrate_v14(db)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 13
        assert db.execute("SELECT id FROM book_discovery_candidates").fetchone()[0] == candidate_id
        assert not db.execute("SELECT name FROM sqlite_master WHERE name = 'book_discovery_candidates_v14'").fetchall()
    finally:
        db.close()
    assert _core(tmp_path, _handler(_documents(), [])).store.integrity_check()["ok"] is True


def test_migration_preserves_v13_candidates_and_dismissals(tmp_path):
    core = _core(tmp_path, _handler(_documents(), []))
    candidate_id = _discovered(core)
    core.dismiss_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)
    with sqlite3.connect(tmp_path / "core.db") as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'book_discovery_candidates'").fetchone()[0]
        db.execute("DROP INDEX book_discovery_scope_state")
        db.execute("ALTER TABLE book_discovery_candidates RENAME TO preserved")
        db.execute(sql.replace("'discovered', 'verified',", "'discovered',"))
        db.execute("INSERT INTO book_discovery_candidates SELECT * FROM preserved")
        db.execute("DROP TABLE preserved")
        db.execute("PRAGMA user_version = 13")
    upgraded = _core(tmp_path, _handler(_documents(), []))
    assert upgraded.store.status()["schema_version"] == 14
    assert upgraded.store.get_book_discovery_candidate(user_id="tenant-one", candidate_id=candidate_id)["state"] == "dismissed"
    assert upgraded.store.integrity_check()["ok"] is True
    assert _core(tmp_path, _handler(_documents(), [])).store.status()["schema_version"] == 14
