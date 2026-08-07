from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.request

from agent.config import get_settings

logger = logging.getLogger(__name__)

WEB_RESULT_SEPARATOR = "\n\n---\n\n"


class ExaClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        contents_url: str | None = None,
        log_path: Path | str | None = None,
        timeout_seconds: int = 45,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.exa_api_key
        self.base_url = base_url or settings.exa_base_url
        self.contents_url = contents_url or settings.exa_contents_url
        self.log_path = Path(log_path if log_path is not None else settings.exa_log_path)
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        query: str,
        *,
        num_results: int = 5,
        search_type: str = "auto",
        contents: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("EXA_API_KEY is not configured.")

        body: dict[str, Any] = {
            "query": query,
            "numResults": num_results,
            "type": search_type,
            "contents": contents if contents is not None else {"highlights": True},
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self._log_search(query=query, payload=payload)
        return payload

    def web_search_text(self, query: str, *, num: int = 5) -> str:
        payload = self.search(query, num_results=num)
        return _exa_payload_text(payload, num=num)

    def get_contents(self, urls: list[str], *, max_characters: int = 15000) -> dict[str, Any]:
        """Fetch clean page content for one or more URLs (Exa /contents)."""
        if not self.api_key:
            raise RuntimeError("EXA_API_KEY is not configured.")

        body: dict[str, Any] = {
            "urls": urls,
            "text": {"max_characters": max_characters},
        }
        request = urllib.request.Request(
            self.contents_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self._log_contents(urls=urls, payload=payload)
        return payload

    def _log_contents(self, *, urls: list[str], payload: dict[str, Any]) -> None:
        results = payload.get("results") if isinstance(payload, dict) else []
        record = {
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "provider": "exa",
            "num_urls": len(urls),
            "num_results": len(results) if isinstance(results, list) else 0,
            "urls_hashed": [_hash_query(u) for u in urls],
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def _log_search(self, *, query: str, payload: dict[str, Any]) -> None:
        results = payload.get("results") if isinstance(payload, dict) else []
        record = {
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "provider": "exa",
            "request_id": payload.get("requestId") if isinstance(payload, dict) else "",
            "num_results": len(results) if isinstance(results, list) else 0,
            "search_type": payload.get("resolvedSearchType") if isinstance(payload, dict) else "",
            "query_hashed": _hash_query(query),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


def _exa_payload_text(payload: dict[str, Any], *, num: int) -> str:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return "No web results found."

    blocks: list[str] = []
    for item in results[:num]:
        if not isinstance(item, dict):
            continue
        url = _string(item.get("url"))
        if not url:
            continue
        title = _string(item.get("title") or url)
        snippet = _exa_snippet(item)
        blocks.append(f"**{title}**\n{snippet}\n{url}")
    return WEB_RESULT_SEPARATOR.join(block for block in blocks if block.strip()) or "No web results found."


def _exa_snippet(item: dict[str, Any]) -> str:
    highlights = item.get("highlights")
    if isinstance(highlights, list) and highlights:
        return " ".join(str(h) for h in highlights if h)[:700]
    text = _string(item.get("text"))
    if text:
        return text[:700]
    return ""


def _hash_query(query: str) -> str:
    import hashlib

    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _string(value: Any) -> str:
    return "" if value is None else str(value)
