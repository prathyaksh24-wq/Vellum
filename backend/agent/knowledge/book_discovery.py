"""Shadow Discovery orchestration owned by Knowledge Core, not the Book library."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from agent.knowledge.book_catalog import (
    BookCatalog, BookDiscoveryError, OpenLibraryCatalog,
    normalize_catalog_record, normalized_book_identity,
)
from agent.knowledge.book_documents import BookDocumentPipeline
from agent.knowledge.models import (
    BookDiscoveryPolicy,
    BookDiscoveryRequest,
    BookDiscoveryVerificationRequest,
    IngestionJobInput,
)
from agent.knowledge.store import BookDiscoveryCandidateChanged, IngestionJobLeaseLost, KnowledgeStore
from agent.privacy.classifier import DataClass, classify


DISCOVERY_VERSION = "books-discovery-shadow-v1"
_ERROR_CODES = frozenset({
    "CATALOG_RATE_LIMITED", "CATALOG_UNAVAILABLE", "CATALOG_ENCODING_UNSUPPORTED",
    "CATALOG_INVALID_RESPONSE", "CATALOG_RESPONSE_BUDGET", "DISCOVERY_DEADLINE",
    "DISCOVERY_RETRY_BUDGET", "DISCOVERY_LIBRARY_BUDGET",
    "DISCOVERY_VERIFICATION_DEADLINE", "DISCOVERY_VERIFICATION_REQUEST_BUDGET",
    "DISCOVERY_VERIFICATION_RESPONSE_BUDGET", "DISCOVERY_VERIFICATION_REDIRECT",
    "DISCOVERY_VERIFICATION_ENCODING_UNSUPPORTED", "DISCOVERY_VERIFICATION_INVALID_RESPONSE",
    "DISCOVERY_VERIFICATION_UNAVAILABLE", "DISCOVERY_VERIFICATION_RATE_LIMITED",
    "DISCOVERY_VERIFICATION_MISMATCH", "DISCOVERY_VERIFICATION_MISSING_DATA",
    "DISCOVERY_VERIFICATION_INVALID_CANDIDATE", "DISCOVERY_VERIFICATION_INVALID_EVIDENCE",
    "DISCOVERY_VERIFICATION_AUTHOR_LIMIT", "DISCOVERY_CANDIDATE_NOT_FOUND",
    "DISCOVERY_CANDIDATE_INELIGIBLE", "DISCOVERY_CANDIDATE_CHANGED", "DISCOVERY_CANDIDATE_EXPIRED",
})
_VERIFICATION_VERSION = "books-discovery-verification-v1"


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

    def verify(
        self,
        request: BookDiscoveryVerificationRequest,
        *,
        policy: BookDiscoveryPolicy,
    ) -> dict[str, Any]:
        request = BookDiscoveryVerificationRequest.model_validate(request.model_dump())
        policy = BookDiscoveryPolicy.model_validate(policy.model_dump())
        if policy.local_only or not policy.network_allowed or not policy.public_query_approved:
            return self._verification_result("blocked", reason_code="DISCOVERY_NETWORK_NOT_APPROVED")

        candidate = self.store.get_book_discovery_candidate(
            user_id=request.user_id,
            candidate_id=request.candidate_id,
            include_internal=True,
        )
        if candidate is None:
            return self._verification_result("unverified", reason_code="DISCOVERY_CANDIDATE_NOT_FOUND")
        if candidate["state"] not in {"discovered", "verified"}:
            return self._verification_result("unverified", reason_code="DISCOVERY_CANDIDATE_INELIGIBLE")
        if self._expired(candidate["expires_at"]):
            return self._verification_result("unverified", reason_code="DISCOVERY_CANDIDATE_EXPIRED")
        if candidate["state"] == "verified":
            metadata = candidate.get("verification_metadata")
            return self._verification_result(
                "completed",
                candidates=[self._public_candidate(candidate)],
                metadata=self._safe_metadata(metadata, reason_code=""),
                replayed=True,
            )
        objective = str(candidate["objective"])
        identity = {
            "candidate_id": request.candidate_id,
            "objective": objective,
            "request_key": request.request_key,
            "policy": policy.model_dump(),
            "version": _VERIFICATION_VERSION,
            "catalog_digest": candidate.get("catalog_record_digest"),
            "expires_at": candidate["expires_at"],
        }
        key = sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
        job = self.store.start_ingestion_job(IngestionJobInput(
            connector="books.discovery",
            account_id=self.store.book_tenant_scope(request.user_id),
            job_type="metadata_verification",
            idempotency_key=key,
            requested_by="books.discovery",
            lease_seconds=90,
        ))
        job_id = job["id"]
        if not job["should_run"]:
            current = self.store.get_book_discovery_candidate(
                user_id=request.user_id, candidate_id=request.candidate_id,
            )
            stats = job.get("stats") or {}
            if (job["status"] == "completed" and stats.get("verification") == "verified"
                    and current and current["state"] == "verified" and not self._expired(current["expires_at"])):
                return self._verification_result(
                    "completed",
                    job_id=job_id,
                    candidates=[self._public_candidate(current)],
                    metadata=self._safe_metadata(current.get("verification_metadata"), reason_code=""),
                    replayed=True,
                )
            if job["status"] == "completed" and stats.get("verification") == "unverified":
                return self._verification_result(
                    "unverified",
                    job_id=job_id,
                    metadata=self._safe_metadata(stats, reason_code=str(stats.get("reason_code", ""))),
                    replayed=True,
                )
            return self._verification_result(
                str(job["status"]), job_id=job_id, replayed=True,
                reason_code="DISCOVERY_VERIFICATION_IN_PROGRESS" if job["status"] == "running" else "DISCOVERY_FAILED",
            )

        current = self.store.get_book_discovery_candidate(
            user_id=request.user_id, candidate_id=request.candidate_id, include_internal=True,
        )
        if current is None or current.get("state") != "discovered":
            return self._finish_verification_change(
                job_id, job["attempt_count"], reason_code="DISCOVERY_CANDIDATE_CHANGED"
            )
        if current.get("_candidate_revision") != candidate.get("_candidate_revision"):
            return self._finish_verification_change(
                job_id, job["attempt_count"], reason_code="DISCOVERY_CANDIDATE_CHANGED"
            )

        started = monotonic()
        deadline = started + policy.deadline_seconds
        safe_candidate = {key: value for key, value in current.items() if not key.startswith("_")}
        try:
            if job["attempt_count"] > 3:
                raise BookDiscoveryError("DISCOVERY_RETRY_BUDGET")
            if monotonic() >= deadline:
                raise BookDiscoveryError("DISCOVERY_VERIFICATION_DEADLINE")
            evidence = self.catalog.verify(safe_candidate, max_bytes=policy.max_response_bytes, deadline=deadline)
            if monotonic() >= deadline:
                raise BookDiscoveryError("DISCOVERY_VERIFICATION_DEADLINE")
            if not isinstance(evidence, dict):
                raise BookDiscoveryError("DISCOVERY_VERIFICATION_INVALID_EVIDENCE")
            reason_code = str(evidence.get("reason_code", ""))
            metadata = self._safe_metadata(evidence.get("metadata"), reason_code=reason_code)
            if evidence.get("verified") is not True:
                self.store.publish_book_discovery_verification(
                    user_id=request.user_id, candidate_id=request.candidate_id,
                    expected_revision=str(current["_candidate_revision"]),
                    job_id=job_id, verified=False, verification_metadata=metadata,
                    stats=self._verification_stats(
                        metadata, outcome="unverified", reason_code=reason_code or "DISCOVERY_VERIFICATION_MISMATCH",
                        started=started,
                    ),
                    expected_attempt=job["attempt_count"],
                )
                return self._verification_result(
                    "unverified", job_id=job_id,
                    metadata=self._safe_metadata(metadata, reason_code=reason_code or "DISCOVERY_VERIFICATION_MISMATCH"),
                )
            if not metadata.get("edition_id") or metadata.get("provider") != "openlibrary":
                raise BookDiscoveryError("DISCOVERY_VERIFICATION_INVALID_EVIDENCE")
            published = self.store.publish_book_discovery_verification(
                user_id=request.user_id,
                candidate_id=request.candidate_id,
                expected_revision=str(current["_candidate_revision"]),
                job_id=job_id,
                expected_attempt=job["attempt_count"],
                verification_metadata=metadata,
                stats=self._verification_stats(metadata, outcome="verified", reason_code="", started=started),
            )
            return self._verification_result(
                "completed", job_id=job_id, candidates=[published], metadata=metadata,
            )
        except BookDiscoveryCandidateChanged as exc:
            return self._finish_verification_change(
                job_id, job["attempt_count"], reason_code=str(exc) or "DISCOVERY_CANDIDATE_CHANGED"
            )
        except IngestionJobLeaseLost:
            return self._verification_result(
                "superseded", job_id=job_id, reason_code="DISCOVERY_LEASE_LOST"
            )
        except BookDiscoveryError as exc:
            code = str(exc) if str(exc) in _ERROR_CODES else "DISCOVERY_VERIFICATION_FAILED"
            try:
                self.store.fail_ingestion_job(job_id, error_code=code, expected_attempt=job["attempt_count"])
            except IngestionJobLeaseLost:
                return self._verification_result(
                    "superseded", job_id=job_id, reason_code="DISCOVERY_LEASE_LOST"
                )
            return self._verification_result(
                "failed", job_id=job_id,
                metadata=self._safe_metadata(getattr(exc, "metadata", None), reason_code=code),
                reason_code=code,
            )
        except Exception:
            try:
                self.store.fail_ingestion_job(
                    job_id, error_code="DISCOVERY_VERIFICATION_FAILED", expected_attempt=job["attempt_count"]
                )
            except IngestionJobLeaseLost:
                return self._verification_result(
                    "superseded", job_id=job_id, reason_code="DISCOVERY_LEASE_LOST"
                )
            return self._verification_result(
                "failed", job_id=job_id, reason_code="DISCOVERY_VERIFICATION_FAILED"
            )

    def _finish_verification_change(self, job_id: str, attempt: int, *, reason_code: str) -> dict[str, Any]:
        try:
            self.store.fail_ingestion_job(job_id, error_code=reason_code, expected_attempt=attempt)
        except IngestionJobLeaseLost:
            return self._verification_result("superseded", job_id=job_id, reason_code="DISCOVERY_LEASE_LOST")
        return self._verification_result("superseded", job_id=job_id, reason_code=reason_code)

    @staticmethod
    def _expired(value: str) -> bool:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            return timestamp <= datetime.now(UTC)
        except ValueError:
            return True

    @staticmethod
    def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in candidate.items() if not key.startswith("_")}

    @staticmethod
    def _safe_metadata(value: Any, *, reason_code: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            value = {}
        metadata: dict[str, Any] = {
            "provider": "openlibrary",
            "verification_version": _VERIFICATION_VERSION,
        }
        for key in ("request_count", "response_bytes", "author_count", "identifier_count"):
            number = value.get(key)
            if type(number) is int and 0 <= number <= 1048576:
                metadata[key] = number
        if isinstance(value.get("work_id"), str) and re.fullmatch(r"OL[1-9][0-9]*W", value["work_id"]):
            metadata["work_id"] = value["work_id"]
        if isinstance(value.get("edition_id"), str) and re.fullmatch(r"OL[1-9][0-9]*M", value["edition_id"]):
            metadata["edition_id"] = value["edition_id"]
        languages = value.get("language_codes")
        if isinstance(languages, list) and len(languages) <= 30 and all(
            isinstance(language, str) and re.fullmatch(r"[a-z]{3}", language) for language in languages
        ):
            metadata["language_codes"] = sorted(set(languages))
        if value.get("cover_status") in {"available", "unavailable"}:
            metadata["cover_status"] = value["cover_status"]
        if type(value.get("cover_id")) is int and 0 < value["cover_id"] < 10**12:
            metadata["cover_id"] = value["cover_id"]
        if type(value.get("cover_checked")) is bool:
            metadata["cover_checked"] = value["cover_checked"]
        if value.get("cover_verification") == "availability_only":
            metadata["cover_verification"] = "availability_only"
        provenance = value.get("provenance")
        if isinstance(provenance, dict):
            allowed_provenance: dict[str, Any] = {}
            work_url = provenance.get("work_url")
            edition_url = provenance.get("edition_url")
            author_urls = provenance.get("author_urls")
            cover_url = provenance.get("cover_url")
            if isinstance(work_url, str) and re.fullmatch(r"https://openlibrary\.org/works/OL[1-9][0-9]*W", work_url):
                allowed_provenance["work_url"] = work_url
            if isinstance(edition_url, str) and re.fullmatch(r"https://openlibrary\.org/books/OL[1-9][0-9]*M", edition_url):
                allowed_provenance["edition_url"] = edition_url
            if isinstance(author_urls, list) and len(author_urls) <= 3 and all(
                isinstance(url, str) and re.fullmatch(r"https://openlibrary\.org/authors/OL[1-9][0-9]*A", url)
                for url in author_urls
            ):
                allowed_provenance["author_urls"] = author_urls
            if isinstance(cover_url, str) and (
                not cover_url or re.fullmatch(
                    r"https://covers\.openlibrary\.org/b/id/[1-9][0-9]*-M\.jpg\?default=false", cover_url
                )
            ):
                allowed_provenance["cover_url"] = cover_url
            if allowed_provenance:
                metadata["provenance"] = allowed_provenance
        if reason_code:
            metadata["reason_code"] = reason_code if reason_code in _ERROR_CODES else "DISCOVERY_VERIFICATION_FAILED"
        return metadata

    @staticmethod
    def _verification_stats(
        metadata: dict[str, Any], *, outcome: str, reason_code: str, started: float,
    ) -> dict[str, Any]:
        stats = {
            "mode": "shadow",
            "provider": "openlibrary",
            "version": _VERIFICATION_VERSION,
            "verification": outcome,
            "request_count": metadata.get("request_count", 0),
            "response_bytes": metadata.get("response_bytes", 0),
            "duration_ms": max(0, int((monotonic() - started) * 1000)),
        }
        if reason_code:
            stats["reason_code"] = reason_code
        return stats

    @staticmethod
    def _verification_result(status: str, **fields: Any) -> dict[str, Any]:
        result = {
            "status": status,
            "mode": "shadow",
            "candidates": [],
            "metadata": {},
            "replayed": False,
        }
        reason_code = fields.pop("reason_code", "")
        if reason_code:
            result["error_code"] = reason_code
            result["metadata"] = {"reason_code": reason_code}
        result.update(fields)
        return result

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
