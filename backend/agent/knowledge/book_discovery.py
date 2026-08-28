"""Shadow Discovery orchestration owned by Knowledge Core, not the Book library."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from time import monotonic
from typing import Any

from agent.knowledge.book_catalog import (
    BookCatalog, BookDiscoveryError, OpenLibraryCatalog,
    normalize_catalog_record, normalized_book_identity,
)
from agent.knowledge.book_documents import BookDocumentPipeline
from agent.knowledge.models import BookDiscoveryPolicy, BookDiscoveryRequest, IngestionJobInput
from agent.knowledge.store import IngestionJobLeaseLost, KnowledgeStore
from agent.privacy.classifier import DataClass, classify


DISCOVERY_VERSION = "books-discovery-shadow-v1"
_ERROR_CODES = frozenset({
    "CATALOG_RATE_LIMITED", "CATALOG_UNAVAILABLE", "CATALOG_ENCODING_UNSUPPORTED",
    "CATALOG_INVALID_RESPONSE", "CATALOG_RESPONSE_BUDGET", "DISCOVERY_DEADLINE",
    "DISCOVERY_RETRY_BUDGET", "DISCOVERY_LIBRARY_BUDGET",
})


class BookDiscoveryRuntime:
    def __init__(
        self, store: KnowledgeStore, documents: BookDocumentPipeline, *, catalog: BookCatalog | None = None,
    ) -> None:
        self.store = store
        self.documents = documents
        self.catalog = catalog if catalog is not None else OpenLibraryCatalog()

    def discover(self, request: BookDiscoveryRequest, *, policy: BookDiscoveryPolicy) -> dict[str, Any]:
        request = BookDiscoveryRequest.model_validate(request.model_dump())
        policy = BookDiscoveryPolicy.model_validate(policy.model_dump())
        if policy.local_only or not policy.network_allowed or not policy.public_query_approved:
            return self._result("blocked", error_code="DISCOVERY_NETWORK_NOT_APPROVED")
        try:
            # Only a separately approved public catalog query is accepted. Do not
            # build it from Book text, private learning, conversations, or profiles.
            if re.search(r"[@\\/:<>{}\r\n]", request.query) or classify(request.query)[0] != DataClass.GREEN:
                return self._result("blocked", error_code="DISCOVERY_QUERY_PRIVATE")
        except Exception:
            return self._result("blocked", error_code="DISCOVERY_PRIVACY_UNAVAILABLE")

        identity = {"request": request.model_dump(exclude={"user_id"}),
                    "policy": policy.model_dump(), "version": DISCOVERY_VERSION}
        key = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        job = self.store.start_ingestion_job(IngestionJobInput(
            connector="books.discovery", account_id=self.store.book_tenant_scope(request.user_id),
            job_type="metadata_discovery", idempotency_key=key, requested_by="books.discovery", lease_seconds=90,
        ))
        job_id = job["id"]
        if not job["should_run"]:
            return self._result(
                job["status"], job_id=job_id, replayed=True,
                candidates=self.list_candidates(user_id=request.user_id, objective=request.objective, job_id=job_id)
                if job["status"] == "completed" else [],
            )
        started = monotonic()
        deadline = started + policy.deadline_seconds
        try:
            if job["attempt_count"] > 3:
                raise BookDiscoveryError("DISCOVERY_RETRY_BUDGET")
            installed = self._installed_identities(request.user_id, deadline=deadline)
            raw = self.catalog.search(
                request.query, limit=min(40, request.max_candidates * 3),
                max_bytes=policy.max_response_bytes, deadline=deadline,
            )
            if monotonic() >= deadline:
                raise BookDiscoveryError("DISCOVERY_DEADLINE")
            ranked = self._rank(raw, query=request.query, installed=installed, limit=request.max_candidates)
            candidates = self.store.publish_book_discovery_candidates(
                user_id=request.user_id, objective=request.objective, job_id=job_id,
                candidates=ranked, ttl_days=policy.candidate_ttl_days, capacity=policy.max_retained_candidates,
                expected_attempt=job["attempt_count"],
                stats={
                    "mode": "shadow", "objective": request.objective,
                    "provider": "openlibrary", "version": DISCOVERY_VERSION,
                    "catalog_records": len(raw), "request_limit": 1, "model_tokens": 0, "depth": 0,
                    "duration_ms": max(0, int((monotonic() - started) * 1000)),
                },
            )
            return self._result("completed", job_id=job_id, candidates=candidates)
        except IngestionJobLeaseLost:
            return self._result("superseded", job_id=job_id, error_code="DISCOVERY_LEASE_LOST")
        except BookDiscoveryError as exc:
            code = str(exc) if str(exc) in _ERROR_CODES else "DISCOVERY_FAILED"
        except Exception:
            # Provider/storage errors may contain local paths or a request URL.
            code = "DISCOVERY_FAILED"
        try:
            self.store.fail_ingestion_job(job_id, error_code=code, expected_attempt=job["attempt_count"])
        except IngestionJobLeaseLost:
            return self._result("superseded", job_id=job_id, error_code="DISCOVERY_LEASE_LOST")
        return self._result("failed", job_id=job_id, error_code=code)

    def list_candidates(
        self, *, user_id: str, objective: str, job_id: str = "", limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.store.list_book_discovery_candidates(
            user_id=user_id, objective=objective, job_id=job_id, limit=limit,
        )
        if not rows:
            return []
        installed = self._installed_identities(user_id, deadline=monotonic() + 10)
        return [row for row in rows if row["identity_hash"] not in installed]

    def _installed_identities(self, user_id: str, *, deadline: float) -> set[str]:
        records = self.store.list_active_book_materialization_records(user_id=user_id)
        if len(records) > 200:
            raise BookDiscoveryError("DISCOVERY_LIBRARY_BUDGET")
        result = set()
        bytes_read = 0
        for record in records:
            document_record = self.store.get_book_document_record(user_id=user_id, document_id=record["document_id"])
            path = self.store.blobs.resolve(document_record["blob_path"])
            bytes_read += path.stat().st_size
            if bytes_read > 8 * 1024 * 1024 or monotonic() >= deadline:
                raise BookDiscoveryError("DISCOVERY_LIBRARY_BUDGET")
            document = self.documents.load(user_id=user_id, document_id=record["document_id"])
            result.add(normalized_book_identity(document.metadata.title, document.metadata.creators))
        return result

    @staticmethod
    def _rank(raw: list[Any], *, query: str, installed: set[str], limit: int) -> list[dict[str, Any]]:
        terms = set(re.findall(r"\w+", query.casefold()))
        ranked = []
        for record in raw[:40]:
            item = normalize_catalog_record(record)
            if item is None or item["identity_hash"] in installed:
                continue
            title_terms = set(re.findall(r"\w+", item["title"].casefold()))
            catalog_terms = set(re.findall(r"\w+", " ".join([*item["subjects"], *item["authors"]]).casefold()))
            coverage = len(terms & (title_terms | catalog_terms)) / max(1, len(terms))
            if not terms or coverage < 0.5:
                continue
            item["relevance_score"] = round(0.8 * coverage + 0.2 * len(terms & title_terms) / len(terms), 4)
            item["reason_code"] = "catalog_topic_match"
            item["ranking_version"] = DISCOVERY_VERSION
            ranked.append(item)
        ranked.sort(key=lambda item: (-item["relevance_score"], item["work_id"]))
        seen_ids, seen_works, author_counts = set(), set(), {}
        result = []
        for item in ranked:
            if item["identity_hash"] in seen_ids or item["work_id"] in seen_works:
                continue
            authors = [author.casefold() for author in item["authors"]]
            if any(author_counts.get(author, 0) >= 2 for author in authors):
                continue
            seen_ids.add(item["identity_hash"])
            seen_works.add(item["work_id"])
            for author in authors:
                author_counts[author] = author_counts.get(author, 0) + 1
            result.append(item)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _result(status: str, **fields: Any) -> dict[str, Any]:
        return {"status": status, "mode": "shadow", "candidates": [], "replayed": False, **fields}
