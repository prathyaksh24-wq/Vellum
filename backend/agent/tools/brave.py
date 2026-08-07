from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request

from agent.config import get_settings

logger = logging.getLogger(__name__)

WEB_RESULT_SEPARATOR = "\n\n---\n\n"


class BraveClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        log_path: Path | str | None = None,
        timeout_seconds: int = 45,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.brave_api_key
        self.base_url = base_url or settings.brave_base_url
        self.log_path = Path(log_path if log_path is not None else settings.brave_log_path)
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, count: int = 5, extra_snippets: bool = False) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("BRAVE_API_KEY is not configured.")

        params = {"q": query, "count": count}
        if extra_snippets:
            params["extra_snippets"] = "true"
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self._log_search(query=query, payload=payload)
        return payload

    def web_search_text(self, query: str, *, num: int = 5) -> str:
        payload = self.search(query, count=num, extra_snippets=True)
        return _brave_payload_text(payload, num=num)

    def _log_search(self, *, query: str, payload: dict[str, Any]) -> None:
        web = payload.get("web") if isinstance(payload, dict) else {}
        results = web.get("results") if isinstance(web, dict) else []
        query_info = payload.get("query") if isinstance(payload, dict) else {}
        record = {
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "provider": "brave",
            "num_results": len(results) if isinstance(results, list) else 0,
            "more_results_available": bool(
                query_info.get("more_results_available") if isinstance(query_info, dict) else False
            ),
            "query_hashed": hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


def _brave_payload_text(payload: dict[str, Any], *, num: int) -> str:
    web = payload.get("web")
    results = web.get("results") if isinstance(web, dict) else []
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
        snippet = _brave_snippet(item)
        blocks.append(f"**{title}**\n{snippet}\n{url}")
    return WEB_RESULT_SEPARATOR.join(block for block in blocks if block.strip()) or "No web results found."


def _brave_snippet(item: dict[str, Any]) -> str:
    description = _string(item.get("description"))
    if description:
        return description[:700]
    extra_snippets = item.get("extra_snippets")
    if isinstance(extra_snippets, list) and extra_snippets:
        return " ".join(str(s) for s in extra_snippets if s)[:700]
    return ""


def _string(value: Any) -> str:
    return "" if value is None else str(value)
