from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import re
from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse, SpecialistSource
from agent.config import get_settings
from agent.tools.serpapi import SerpApiClient
from agent.tools.web import extract_web_sources, web_search


WebSearcher = Callable[[str], str]


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
        search_output = self.web_searcher(self._search_query(query, league))
        sources = extract_web_sources(search_output)
        if not sources:
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary="SportsAgent could not find fresh web sources for this sports query.",
                analysis=search_output[:500],
                confidence=0.2,
            )

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        selected = sources[:3]
        summary = self._compose_answer(query, selected)
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

    def _default_web_searcher(self, query: str) -> str:
        settings = get_settings()
        if settings.serpapi_api_key:
            try:
                return SerpApiClient(
                    api_key=settings.serpapi_api_key,
                    log_path=settings.serpapi_log_path,
                ).google_search_text(query, num=5)
            except Exception:
                pass
        return web_search.invoke({"query": query})

    def _search_query(self, query: str, league: str) -> str:
        return f"{query} latest {league} scores news injuries analysis"

    def _compose_answer(self, query: str, sources: list[dict]) -> str:
        lines = [f"SportsAgent checked fresh public sources for: {query}."]
        for index, source in enumerate(sources, start=1):
            title = str(source.get("title") or source.get("domain") or f"Source {index}").strip()
            snippet = str(source.get("snippet") or "").strip()
            if snippet:
                lines.append(f"[{index}] {title}: {snippet}")
            else:
                lines.append(f"[{index}] {title}.")
        lines.append("Use this as a live update snapshot; exact lineups and injury statuses can still move close to game time.")
        return "\n".join(lines)

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
