from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.registry import ToolRegistry


class XAgent:
    name = "XAgent"

    _KEYWORDS = ("twitter", "tweet", "tweets", "latest-50")
    _X_CONTEXT_PATTERNS = (
        r"(?<!\w)post(?:s|ed|ing)?\s+on\s+x(?!\w)",
        r"(?<!\w)x\s+account(?:s)?(?!\w)",
        r"(?<!\w)x\s+feed(?:s)?(?!\w)",
        r"(?<!\w)x\s+post(?:s)?(?!\w)",
        r"(?<!\w)on\s+x(?!\w)",
    )

    def __init__(
        self,
        vault_root: Path,
        x_service: XCapabilityService | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.tool_registry = tool_registry
        self.x_service = x_service or (None if tool_registry is not None else XCapabilityService())

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS) or any(
            re.search(pattern, lowered) is not None for pattern in self._X_CONTEXT_PATTERNS
        )

    def answer(self, query: str) -> SpecialistResponse:
        try:
            result = self._search_posts({"query": query, "max_results": 5})
        except Exception as exc:
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary="XAgent could not fetch X posts right now.",
                analysis=f"X search failed: {self._sanitize_error(exc)}",
                confidence=0.2,
            )
        items = result.get("items", [])
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="XAgent did not find matching X posts.",
                confidence=0.35,
            )
        lines = []
        sources = []
        for index, item in enumerate(items[:5], start=1):
            text = str(item.get("text") or "").strip()
            handle = str(item.get("handle") or "x").strip()
            url = str(item.get("url") or "").strip()
            lines.append(f"[{index}] @{handle}: {text}")
            if url:
                sources.append(
                    SpecialistSource(
                        kind="web",
                        title=f"@{handle} on X",
                        path_or_url=url,
                        captured_at=str(item.get("created_at") or ""),
                        freshness="live",
                    )
                )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used x.search_posts through the shared X capability service.",
            sources=sources,
            confidence=0.75,
        )

    def _search_posts(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.search_posts", payload, agent_name=self.name)
        return self.x_service.search_posts(payload)

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _sanitize_error(self, exc: Exception) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ").strip()
        message = re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|authorization|bearer|client[_-]?secret|password)\s*[:=]\s*\S+",
            r"\1=[redacted]",
            message,
        )
        message = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[redacted]", message)
        if not message:
            message = exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"[:160]
