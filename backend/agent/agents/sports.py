from __future__ import annotations

from collections.abc import Callable
from typing import Any
from datetime import datetime, timezone
import re
from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse, SpecialistSource
from agent.config import get_settings
from agent.tools.serpapi import SerpApiClient
from agent.tools.web import extract_web_sources, web_search


WebSearchResult = str | dict[str, Any]
WebSearcher = Callable[[str], WebSearchResult]


class SportsAgent:
    name = "SportsAgent"

    _SPORT_TERMS = (
        "nba",
        "basketball",
        "finals",
        "playoffs",
        "knicks",
        "celtics",
        "lakers",
        "f1",
        "formula 1",
        "formula one",
        "grand prix",
        "gp",
        "premier league",
        "arsenal",
        "epl",
        "champions league",
        "ucl",
        "fifa",
        "world cup",
        "fifa world cup",
        "portugal",
        "national team",
        "opening match",
        "football",
        "soccer",
        "nfl",
        "cricket",
        "tennis",
        "ufc",
        "boxing",
        "mma",
        "fight card",
        "race",
        "match",
        "score",
        "scores",
        "standings",
        "fixture",
        "fixtures",
        "injury report",
    )
    _NON_SPORT_GUARDS = (
        "pytest fixture",
        "model score",
        "credit score",
        "insurance policy",
        "x-axis",
        "underscore",
    )
    _LEAGUE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("NBA", ("nba", "basketball", "knicks", "celtics", "lakers", "finals")),
        ("Formula-One", ("f1", "formula 1", "formula one", "grand prix", "gp")),
        ("Premier-League", ("premier league", "arsenal", "epl")),
        ("Champions-League", ("champions league", "ucl")),
        ("FIFA-World-Cup", ("fifa", "world cup", "fifa world cup", "portugal", "national team")),
        ("UFC", ("ufc", "mma", "fight card", "fight night", "octagon")),
        ("Boxing", ("boxing", "title fight", "fight card")),
        ("Cricket", ("cricket", "ipl", "test match", "odi", "t20")),
        ("Tennis", ("tennis", "atp", "wta", "grand slam", "sinner", "alcaraz")),
        ("NFL", ("nfl", "super bowl", "american football")),
    )

    def __init__(self, vault_root: Path, web_searcher: WebSearcher | None = None) -> None:
        self.vault_root = Path(vault_root)
        self.web_searcher = web_searcher or self._default_web_searcher

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        if any(guard in lowered for guard in self._NON_SPORT_GUARDS):
            return False
        return any(self._has_phrase(lowered, term) for term in self._SPORT_TERMS)

    def answer(self, query: str) -> SpecialistResponse:
        if not self.can_handle(query):
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="SportsAgent did not detect a sports intent in this turn.",
                confidence=0.2,
            )

        league = self.resolve_league(query)
        source_budget = self._source_budget(query)
        search_result = self.web_searcher(self._search_query(query, league, source_budget))
        search_output, sources = self._normalize_search_result(search_result)
        if not sources:
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary="SportsAgent could not find fresh web sources for this sports query.",
                analysis=search_output[:500],
                confidence=0.2,
            )

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        selected = sources[:source_budget]
        summary = self._compose_answer(query, selected, search_output)
        saved_path = self._save_response(query=query, answer=summary, league=league, sources=selected, created_at=now)
        relative_path = saved_path.relative_to(self.vault_root).as_posix()

        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis=f"Used on-demand public web research and saved the sports response to {relative_path}.",
            sources=[
                SpecialistSource(
                    kind="web",
                    title=str(source.get("title") or source.get("domain") or "Sports source"),
                    path_or_url=str(source.get("url") or ""),
                    snippet=str(source.get("snippet") or "").strip()[:500],
                    captured_at=now,
                    freshness="live",
                )
                for source in selected
            ],
            confidence=0.78,
            memory_proposals=[
                MemoryProposal(
                    scope="sports",
                    claim=f"User asked SportsAgent for {league} coverage.",
                    evidence=relative_path,
                    confidence=0.6,
                )
            ],
        )

    def resolve_league(self, query: str) -> str:
        lowered = query.lower()
        for league, aliases in self._LEAGUE_ALIASES:
            if any(self._has_phrase(lowered, alias) for alias in aliases):
                return league
        return "Ambient"

    def _default_web_searcher(self, query: str) -> WebSearchResult:
        settings = get_settings()
        if settings.serpapi_api_key:
            try:
                client = SerpApiClient(
                    api_key=settings.serpapi_api_key,
                    log_path=settings.serpapi_log_path,
                )
                if hasattr(client, "fresh_google_search"):
                    min_sources = 5 if "official schedule standings news reports" in query else 3
                    return client.fresh_google_search(query, num=8, min_sources=min_sources)
                return client.fresh_google_search_text(query, num=5)
            except Exception:
                pass
        return web_search.invoke({"query": query})

    def _search_query(self, query: str, league: str, source_budget: int) -> str:
        multi_source_hint = "official schedule standings news reports" if source_budget >= 5 else "official latest"
        return f"{query} latest {league} scores schedule news injuries analysis {multi_source_hint}"

    def _normalize_search_result(self, search_result: WebSearchResult) -> tuple[str, list[dict[str, Any]]]:
        if isinstance(search_result, dict):
            text = str(search_result.get("text") or "")
            raw_sources = search_result.get("sources")
            sources = [dict(source) for source in raw_sources if isinstance(source, dict)] if isinstance(raw_sources, list) else []
            if sources:
                return text, self._dedupe_sources(sources)
            return text, extract_web_sources(text)
        text = str(search_result or "")
        return text, extract_web_sources(text)

    def _source_budget(self, query: str) -> int:
        lowered = query.lower()
        complex_markers = (
            "multiple sources",
            "sources",
            "latest",
            "today",
            "yesterday",
            "news",
            "injuries",
            "analysis",
            "standings",
            "what happened",
            "world cup",
            "fifa",
        )
        return 5 if any(marker in lowered for marker in complex_markers) else 3

    def _dedupe_sources(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for source in sources:
            url = str(source.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(source)
        return out

    def _compose_answer(self, query: str, sources: list[dict], search_output: str) -> str:
        snapshot = self._snapshot_from_search_output(search_output)
        lines = [f"SportsAgent checked fresh public sources for: {query}."]
        if snapshot:
            lines.append(f"Snapshot: {snapshot}")
        for index, source in enumerate(sources, start=1):
            title = str(source.get("title") or source.get("domain") or f"Source {index}").strip()
            snippet = str(source.get("snippet") or "").strip()
            if snippet:
                lines.append(f"[{index}] {title}: {snippet}")
            else:
                lines.append(f"[{index}] {title}.")
        lines.append("Use this as a live update snapshot; exact lineups and injury statuses can still move close to game time.")
        return "\n".join(lines)

    def _snapshot_from_search_output(self, search_output: str) -> str:
        if not search_output:
            return ""
        first_block = search_output.split("\n\n---\n\n", 1)[0]
        clean_lines = [
            line.strip().strip("*").strip()
            for line in first_block.splitlines()
            if line.strip() and not line.strip().startswith(("http://", "https://"))
        ]
        snapshot = " ".join(clean_lines).strip()
        return snapshot[:900]

    def _save_response(self, *, query: str, answer: str, league: str, sources: list[dict], created_at: str) -> Path:
        folder = self.vault_root / "Library" / "Sports" / league
        folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = folder / f"{timestamp}-sports-response.md"
        source_lines = "\n".join(
            f"  - title: {self._yaml_quote(str(source.get('title') or 'Sports source'))}\n"
            f"    url: {self._yaml_quote(str(source.get('url') or ''))}\n"
            f"    domain: {self._yaml_quote(str(source.get('domain') or ''))}"
            for source in sources
        )
        body_sources = "\n".join(
            f"{index}. [{source.get('title') or source.get('domain')}]({source.get('url')})"
            for index, source in enumerate(sources, start=1)
        )
        content = (
            "---\n"
            "type: sports-response\n"
            f"created: {self._yaml_quote(created_at)}\n"
            f"league: {self._yaml_quote(league)}\n"
            "agent_version: sports-agent-web-v1\n"
            "private: false\n"
            "sources:\n"
            f"{source_lines}\n"
            "---\n\n"
            "## Question\n"
            f"{query}\n\n"
            "## Answer\n"
            f"{answer}\n\n"
            "## Sources\n"
            f"{body_sources}\n"
        )
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _yaml_quote(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
