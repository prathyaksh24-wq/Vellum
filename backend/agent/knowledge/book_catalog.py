"""Bounded, read-only Open Library catalog transport. No acquisition or crawling."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from threading import Lock
from time import monotonic, sleep
from typing import Any, Protocol
import unicodedata

import httpx


class BookDiscoveryError(RuntimeError):
    """Content-free error code suitable for the existing job receipts."""

    def __init__(self, code: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.metadata = metadata or {}


class BookCatalog(Protocol):
    def search(
        self, query: str, *, limit: int, max_bytes: int, deadline: float,
    ) -> list[dict[str, Any]]: ...

    def verify(
        self, candidate: dict[str, Any], *, max_bytes: int, deadline: float,
    ) -> dict[str, Any]: ...


def normalized_book_identity(title: str, authors: list[str]) -> str:
    def normalize(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(re.findall(r"\w+", value))

    identity = [normalize(title), *sorted({normalize(author) for author in authors})]
    return sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Invalid catalog text")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("Invalid catalog text")
    if "<" in value or ">" in value:
        raise ValueError("Invalid catalog text")
    return value.strip()


def _identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip().replace(" ", "").replace("-", "")
    if len(clean) not in {10, 13} or not re.fullmatch(r"[0-9Xx]+", clean):
        return None
    if len(clean) == 13:
        if not clean.isdigit() or sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(clean)) % 10:
            return None
    elif not clean[:9].isdigit() or sum((10 - i) * (10 if c.upper() == "X" else int(c)) for i, c in enumerate(clean)) % 11:
        return None
    return clean.upper()


def _record_identifiers(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("isbn", "isbn_10", "isbn_13"):
        raw = record.get(field, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            continue
        for value in raw[:20]:
            clean = _identifier(value)
            if clean is not None:
                values.append(clean)
    return sorted(set(values))


def _record_edition_ids(record: dict[str, Any]) -> list[str]:
    raw = record.get("edition_key", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    values = {
        value.rsplit("/", 1)[-1]
        for value in raw[:20]
        if isinstance(value, str) and re.fullmatch(r"(?:/books/)?OL[1-9][0-9]*M", value)
    }
    return sorted(values)


def normalize_catalog_record(record: Any) -> dict[str, Any] | None:
    """Allowlist catalog fields; never retain provider snippets, links, or instructions."""
    try:
        if not isinstance(record, dict):
            return None
        key = record.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(r"(?:/works/)?OL[1-9][0-9]*W", key):
            return None
        work_id = key.rsplit("/", 1)[-1]
        title = _text(record.get("title"), 500)
        authors = record.get("author_name")
        author_ids = record.get("author_key")
        if not isinstance(authors, list) or not 1 <= len(authors) <= 12:
            return None
        if not isinstance(author_ids, list) or len(author_ids) != len(authors):
            return None
        authors = [_text(author, 160) for author in authors]
        if any(not isinstance(key, str) or not re.fullmatch(r"OL[1-9][0-9]*A", key) for key in author_ids):
            return None
        subjects = record.get("subject", [])
        if not isinstance(subjects, list):
            return None
        subjects = [_text(subject, 200) for subject in subjects[:20]]
        languages = record.get("language", [])
        if not isinstance(languages, list):
            return None
        languages = sorted({value for value in languages[:30]
                            if isinstance(value, str) and re.fullmatch(r"[a-z]{3}", value)})
        year = record.get("first_publish_year")
        year = year if type(year) is int and 1 <= year <= 2100 else None
        cover_id = record.get("cover_i")
        cover_id = cover_id if type(cover_id) is int and 0 < cover_id < 10**12 else None
        identifiers = _record_identifiers(record)
        edition_ids = _record_edition_ids(record)
        item = {
            "work_id": work_id,
            "identity_hash": normalized_book_identity(title, authors),
            "title": title,
            "authors": authors,
            "author_ids": author_ids,
            "languages": languages,
            "first_publish_year": year,
            "subjects": subjects,
            "source_url": f"https://openlibrary.org/works/{work_id}",
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg?default=false" if cover_id else "",
            "cover_id": cover_id,
            "cover_status": "catalog_reference_unverified" if cover_id else "unavailable",
            "edition_ids": edition_ids,
            "identifiers": identifiers,
            "metadata_trust": "catalog_record",
            "verification": "catalog_identity_only",
            "content_available": False,
        }
        item["catalog_record_digest"] = sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        return item
    except (TypeError, ValueError):
        return None


class OpenLibraryCatalog:
    _lock = Lock()
    _next_request_at = 0.0
    _fields = (
        "key,title,author_name,author_key,first_publish_year,cover_i,language,subject,"
        "edition_key,isbn,isbn_10,isbn_13"
    )

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    @classmethod
    def _reserve_request(cls) -> None:
        # Process-wide throttle also covers separately constructed KnowledgeCore instances.
        with cls._lock:
            now = monotonic()
            if now < cls._next_request_at:
                raise BookDiscoveryError("CATALOG_RATE_LIMITED")
            cls._next_request_at = now + 1.1

    def search(self, query: str, *, limit: int, max_bytes: int, deadline: float) -> list[dict[str, Any]]:
        self._reserve_request()
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise BookDiscoveryError("DISCOVERY_DEADLINE")
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=min(remaining, 5.0),
                follow_redirects=False,
                trust_env=False,
                headers={
                    "User-Agent": "Vellum-BooksDiscovery/1.0 (https://github.com/prathyaksh24-wq/Vellum)",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as client:
                with client.stream(
                    "GET", "https://openlibrary.org/search.json",
                    params={"q": query, "limit": min(40, limit), "fields": self._fields},
                ) as response:
                    if response.status_code in {429, 503}:
                        raise BookDiscoveryError("CATALOG_RATE_LIMITED")
                    if response.status_code != 200:
                        raise BookDiscoveryError("CATALOG_UNAVAILABLE")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise BookDiscoveryError("CATALOG_ENCODING_UNSUPPORTED")
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise BookDiscoveryError("CATALOG_INVALID_RESPONSE")
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=4096):
                        if monotonic() >= deadline:
                            raise BookDiscoveryError("DISCOVERY_DEADLINE")
                        if len(body) + len(chunk) > max_bytes:
                            raise BookDiscoveryError("CATALOG_RESPONSE_BUDGET")
                        body.extend(chunk)
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("docs"), list):
                raise BookDiscoveryError("CATALOG_INVALID_RESPONSE")
            return payload["docs"][:min(40, limit)]
        except (httpx.HTTPError, OSError):
            raise BookDiscoveryError("CATALOG_UNAVAILABLE") from None
        except (ValueError, RecursionError):
            raise BookDiscoveryError("CATALOG_INVALID_RESPONSE") from None

    @classmethod
    def _reserve_verification_request(cls, deadline: float) -> None:
        with cls._lock:
            now = monotonic()
            wait_for = max(0.0, cls._next_request_at - now)
            if now + wait_for >= deadline:
                raise BookDiscoveryError("DISCOVERY_VERIFICATION_DEADLINE")
            if wait_for:
                sleep(wait_for)
                now = monotonic()
            if now >= deadline:
                raise BookDiscoveryError("DISCOVERY_VERIFICATION_DEADLINE")
            cls._next_request_at = now + 1.1

    @staticmethod
    def _verification_metadata(budget: "_VerificationBudget", *, reason_code: str = "") -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider": "openlibrary",
            "verification_version": "books-discovery-verification-v1",
            "request_count": budget.requests,
            "response_bytes": budget.response_bytes,
        }
        if reason_code:
            metadata["reason_code"] = reason_code
        return metadata

    def verify(self, candidate: dict[str, Any], *, max_bytes: int, deadline: float) -> dict[str, Any]:
        budget = _VerificationBudget(max_bytes=max_bytes, deadline=deadline)
        safe = self._safe_candidate(candidate)
        if safe is None:
            return {
                "verified": False,
                "reason_code": "DISCOVERY_VERIFICATION_INVALID_CANDIDATE",
                "metadata": self._verification_metadata(
                    budget, reason_code="DISCOVERY_VERIFICATION_INVALID_CANDIDATE"
                ),
            }
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=min(max(0.1, deadline - monotonic()), 5.0),
                follow_redirects=False,
                trust_env=False,
                headers={
                    "User-Agent": "Vellum-BooksDiscovery/1.0 (https://github.com/prathyaksh24-wq/Vellum)",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as client:
                work = self._get_json(client, f"/works/{safe['work_id']}.json", {}, budget)
                if not self._work_matches(work, safe):
                    return self._unverified(budget, "DISCOVERY_VERIFICATION_MISMATCH")

                edition_ids = safe["edition_ids"]
                if edition_ids:
                    edition = self._get_json(client, f"/books/{edition_ids[0]}.json", {}, budget)
                else:
                    payload = self._get_json(
                        client,
                        f"/works/{safe['work_id']}/editions.json",
                        {"limit": "1"},
                        budget,
                    )
                    entries = payload.get("entries")
                    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
                        return self._unverified(budget, "DISCOVERY_VERIFICATION_MISSING_DATA")
                    edition = entries[0]
                edition_result = self._edition_match(edition, safe)
                if edition_result is None:
                    return self._unverified(budget, "DISCOVERY_VERIFICATION_MISMATCH")
                edition_id, language_codes, identifiers, cover_id = edition_result

                for author_id, author_name in zip(safe["author_ids"], safe["authors"]):
                    author = self._get_json(client, f"/authors/{author_id}.json", {}, budget)
                    if not self._author_matches(author, author_id, author_name):
                        return self._unverified(budget, "DISCOVERY_VERIFICATION_MISMATCH")

                cover_status = "unavailable"
                cover_checked = False
                if cover_id is not None:
                    cover_status = self._head_cover(client, cover_id, budget)
                    cover_checked = True
                metadata = self._verification_metadata(budget)
                metadata.update({
                    "work_id": safe["work_id"],
                    "edition_id": edition_id,
                    "author_count": len(safe["author_ids"]),
                    "language_codes": language_codes,
                    "identifier_count": len(identifiers),
                    "cover_status": cover_status,
                    "cover_id": cover_id,
                    "cover_checked": cover_checked,
                    "cover_verification": "availability_only",
                    "provenance": {
                        "work_url": f"https://openlibrary.org/works/{safe['work_id']}",
                        "edition_url": f"https://openlibrary.org/books/{edition_id}",
                        "author_urls": [f"https://openlibrary.org/authors/{author_id}" for author_id in safe["author_ids"]],
                        "cover_url": (
                            f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg?default=false"
                            if cover_id is not None else ""
                        ),
                    },
                })
                return {"verified": True, "metadata": metadata}
        except BookDiscoveryError:
            raise
        except (httpx.HTTPError, OSError):
            raise BookDiscoveryError(
                "DISCOVERY_VERIFICATION_UNAVAILABLE",
                metadata=self._verification_metadata(budget, reason_code="DISCOVERY_VERIFICATION_UNAVAILABLE"),
            ) from None

    @staticmethod
    def _safe_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
        try:
            if not isinstance(candidate, dict):
                return None
            work_id = candidate.get("work_id")
            identity_hash = candidate.get("identity_hash")
            title = _text(candidate.get("title"), 500)
            authors = candidate.get("authors")
            author_ids = candidate.get("author_ids")
            if (
                not isinstance(work_id, str)
                or not re.fullmatch(r"OL[1-9][0-9]*W", work_id)
                or not isinstance(identity_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", identity_hash)
                or not isinstance(authors, list)
                or not 1 <= len(authors) <= 3
                or not isinstance(author_ids, list)
                or len(authors) != len(author_ids)
            ):
                return None
            authors = [_text(author, 160) for author in authors]
            if any(not isinstance(author_id, str) or not re.fullmatch(r"OL[1-9][0-9]*A", author_id) for author_id in author_ids):
                return None
            if normalized_book_identity(title, authors) != identity_hash:
                return None
            edition_ids = candidate.get("edition_ids", [])
            if not isinstance(edition_ids, list) or len(edition_ids) > 20:
                return None
            edition_ids = [
                edition_id for edition_id in edition_ids
                if isinstance(edition_id, str) and re.fullmatch(r"OL[1-9][0-9]*M", edition_id)
            ]
            identifiers = candidate.get("identifiers", [])
            if not isinstance(identifiers, list) or len(identifiers) > 20:
                return None
            identifiers = [identifier for identifier in identifiers if _identifier(identifier) is not None]
            languages = candidate.get("languages", [])
            if not isinstance(languages, list) or any(
                not isinstance(language, str) or not re.fullmatch(r"[a-z]{3}", language) for language in languages
            ):
                return None
            return {
                "work_id": work_id,
                "identity_hash": identity_hash,
                "title": title,
                "authors": authors,
                "author_ids": list(author_ids),
                "edition_ids": sorted(set(edition_ids)),
                "identifiers": sorted(set(identifiers)),
                "languages": sorted(set(languages)),
            }
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _work_matches(work: dict[str, Any], candidate: dict[str, Any]) -> bool:
        if not isinstance(work, dict):
            return False
        key = work.get("key")
        title = work.get("title")
        authors = work.get("authors")
        if key != f"/works/{candidate['work_id']}" or not isinstance(title, str):
            return False
        if _title_identity(title) != _title_identity(candidate["title"]):
            return False
        links = _author_links(authors)
        return links == set(candidate["author_ids"])

    @staticmethod
    def _edition_match(edition: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, list[str], list[str], int | None] | None:
        if not isinstance(edition, dict):
            return None
        key = edition.get("key")
        title = edition.get("title")
        if not isinstance(key, str) or not re.fullmatch(r"/books/OL[1-9][0-9]*M", key) or not isinstance(title, str):
            return None
        edition_id = key.rsplit("/", 1)[-1]
        if candidate["edition_ids"] and edition_id not in candidate["edition_ids"]:
            return None
        if _title_identity(title) != _title_identity(candidate["title"]):
            return None
        if edition.get("works") != [{"key": f"/works/{candidate['work_id']}"}]:
            return None
        if _author_links(edition.get("authors")) != set(candidate["author_ids"]):
            return None
        languages = edition.get("languages")
        if not isinstance(languages, list):
            return None
        language_codes = sorted({
            language["key"].rsplit("/", 1)[-1]
            for language in languages
            if isinstance(language, dict)
            and isinstance(language.get("key"), str)
            and re.fullmatch(r"/languages/[a-z]{3}", language["key"])
        })
        if not language_codes or candidate["languages"] and not set(language_codes) & set(candidate["languages"]):
            return None
        identifiers = _record_identifiers(edition)
        if not identifiers or candidate["identifiers"] and not set(identifiers) & set(candidate["identifiers"]):
            return None
        covers = edition.get("covers", [])
        if not isinstance(covers, list):
            return None
        cover_id = next((value for value in covers if type(value) is int and 0 < value < 10**12), None)
        return edition_id, language_codes, identifiers, cover_id

    @staticmethod
    def _author_matches(author: dict[str, Any], author_id: str, expected_name: str) -> bool:
        if not isinstance(author, dict):
            return False
        key = author.get("key")
        name = author.get("name")
        return (
            key == f"/authors/{author_id}"
            and isinstance(name, str)
            and _title_identity(name) == _title_identity(expected_name)
        )

    @staticmethod
    def _unverified(budget: "_VerificationBudget", reason_code: str) -> dict[str, Any]:
        return {
            "verified": False,
            "reason_code": reason_code,
            "metadata": OpenLibraryCatalog._verification_metadata(budget, reason_code=reason_code),
        }

    @staticmethod
    def _get_json(
        client: httpx.Client,
        path: str,
        params: dict[str, str],
        budget: "_VerificationBudget",
    ) -> dict[str, Any]:
        budget.reserve()
        try:
            with client.stream(
                "GET", f"https://openlibrary.org{path}", params=params,
                timeout=budget.timeout(),
            ) as response:
                budget.validate_response(response, json_response=True)
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    budget.consume(len(chunk))
                    body.extend(chunk)
            payload = json.loads(body)
        except BookDiscoveryError:
            raise
        except (httpx.HTTPError, OSError):
            raise BookDiscoveryError(
                "DISCOVERY_VERIFICATION_UNAVAILABLE",
                metadata=OpenLibraryCatalog._verification_metadata(
                    budget, reason_code="DISCOVERY_VERIFICATION_UNAVAILABLE"
                ),
            ) from None
        except (TypeError, ValueError, RecursionError):
            raise BookDiscoveryError(
                "DISCOVERY_VERIFICATION_INVALID_RESPONSE",
                metadata=OpenLibraryCatalog._verification_metadata(
                    budget, reason_code="DISCOVERY_VERIFICATION_INVALID_RESPONSE"
                ),
            ) from None
        if not isinstance(payload, dict):
            raise BookDiscoveryError(
                "DISCOVERY_VERIFICATION_INVALID_RESPONSE",
                metadata=OpenLibraryCatalog._verification_metadata(
                    budget, reason_code="DISCOVERY_VERIFICATION_INVALID_RESPONSE"
                ),
            )
        return payload

    @staticmethod
    def _head_cover(client: httpx.Client, cover_id: int, budget: "_VerificationBudget") -> str:
        budget.reserve()
        try:
            with client.stream(
                "HEAD",
                f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg",
                params={"default": "false"},
                timeout=budget.timeout(),
            ) as response:
                budget.validate_response(response, json_response=False)
                if response.status_code in {404, 410}:
                    return "unavailable"
                if response.status_code != 200:
                    raise BookDiscoveryError(
                        "DISCOVERY_VERIFICATION_UNAVAILABLE",
                        metadata=OpenLibraryCatalog._verification_metadata(
                            budget, reason_code="DISCOVERY_VERIFICATION_UNAVAILABLE"
                        ),
                    )
                content_type = response.headers.get("content-type", "")
                if not content_type.lower().startswith("image/"):
                    raise BookDiscoveryError(
                        "DISCOVERY_VERIFICATION_INVALID_RESPONSE",
                        metadata=OpenLibraryCatalog._verification_metadata(
                            budget, reason_code="DISCOVERY_VERIFICATION_INVALID_RESPONSE"
                        ),
                    )
                return "available"
        except BookDiscoveryError:
            raise
        except (httpx.HTTPError, OSError):
            raise BookDiscoveryError(
                "DISCOVERY_VERIFICATION_UNAVAILABLE",
                metadata=OpenLibraryCatalog._verification_metadata(
                    budget, reason_code="DISCOVERY_VERIFICATION_UNAVAILABLE"
                ),
            ) from None


class _VerificationBudget:
    def __init__(self, *, max_bytes: int, deadline: float) -> None:
        self.max_bytes = max_bytes
        self.deadline = deadline
        self.response_bytes = 0
        self.requests = 0

    def reserve(self) -> None:
        if self.requests >= 6:
            raise BookDiscoveryError(
                "DISCOVERY_VERIFICATION_REQUEST_BUDGET",
                metadata=OpenLibraryCatalog._verification_metadata(
                    self, reason_code="DISCOVERY_VERIFICATION_REQUEST_BUDGET"
                ),
            )
        if monotonic() >= self.deadline:
            raise BookDiscoveryError(
                "DISCOVERY_VERIFICATION_DEADLINE",
                metadata=OpenLibraryCatalog._verification_metadata(
                    self, reason_code="DISCOVERY_VERIFICATION_DEADLINE"
                ),
            )
        OpenLibraryCatalog._reserve_verification_request(self.deadline)
        self.requests += 1

    def timeout(self) -> float:
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            self._raise("DISCOVERY_VERIFICATION_DEADLINE")
        return min(remaining, 5.0)

    def validate_response(self, response: httpx.Response, *, json_response: bool) -> None:
        self.consume(0)
        if 300 <= response.status_code < 400:
            self._raise("DISCOVERY_VERIFICATION_REDIRECT")
        if response.status_code in {429, 503}:
            self._raise("DISCOVERY_VERIFICATION_RATE_LIMITED")
        if json_response and response.status_code != 200:
            self._raise("DISCOVERY_VERIFICATION_UNAVAILABLE")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            self._raise("DISCOVERY_VERIFICATION_ENCODING_UNSUPPORTED")
        content_length = response.headers.get("content-length")
        if json_response and content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                self._raise("DISCOVERY_VERIFICATION_INVALID_RESPONSE")
            if declared < 0 or self.response_bytes + declared > self.max_bytes:
                self._raise("DISCOVERY_VERIFICATION_RESPONSE_BUDGET")
        if json_response and "application/json" not in response.headers.get("content-type", "").lower():
            self._raise("DISCOVERY_VERIFICATION_INVALID_RESPONSE")

    def consume(self, amount: int) -> None:
        if monotonic() >= self.deadline:
            self._raise("DISCOVERY_VERIFICATION_DEADLINE")
        if amount < 0 or self.response_bytes + amount > self.max_bytes:
            self._raise("DISCOVERY_VERIFICATION_RESPONSE_BUDGET")
        self.response_bytes += amount

    def _raise(self, code: str) -> None:
        raise BookDiscoveryError(
            code,
            metadata=OpenLibraryCatalog._verification_metadata(self, reason_code=code),
        )


def _title_identity(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", value))


def _author_links(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    result: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return set()
        nested = item.get("author") if isinstance(item.get("author"), dict) else item
        key = nested.get("key") if isinstance(nested, dict) else None
        if not isinstance(key, str) or not re.fullmatch(r"/authors/OL[1-9][0-9]*A", key):
            return set()
        result.add(key.rsplit("/", 1)[-1])
    return result
