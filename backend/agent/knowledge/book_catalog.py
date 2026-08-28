"""Bounded, read-only Open Library catalog transport. No acquisition or crawling."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from threading import Lock
from time import monotonic
from typing import Any, Protocol
import unicodedata

import httpx


class BookDiscoveryError(RuntimeError):
    """Content-free error code suitable for the existing job receipts."""


class BookCatalog(Protocol):
    def search(
        self, query: str, *, limit: int, max_bytes: int, deadline: float,
    ) -> list[dict[str, Any]]: ...


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
            "cover_status": "catalog_reference_unverified" if cover_id else "unavailable",
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
    _fields = "key,title,author_name,author_key,first_publish_year,cover_i,language,subject"

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
