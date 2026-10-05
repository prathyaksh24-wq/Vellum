from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo
import re
from pathlib import Path
from typing import Any

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.config import get_settings
from agent.tools.serpapi import SerpApiClient
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry
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
        "ronaldo",
        "cristiano ronaldo",
        "messi",
        "lionel messi",
        "mbappe",
        "mbappé",
        "haaland",
    )
    _NFL_TEAM_TERMS = (
        "chiefs", "cheifs", "kansas city chiefs", "kc chiefs", "bills", "ravens",
        "bengals", "browns", "steelers", "texans", "colts", "jaguars", "titans",
        "broncos", "raiders", "chargers", "cowboys", "eagles", "giants", "commanders",
        "bears", "lions", "packers", "vikings", "falcons", "panthers", "saints",
        "buccaneers", "cardinals", "rams", "49ers", "niners", "seahawks", "patriots",
        "jets", "dolphins",
    )
    _TEAM_EVENT_TERMS = (
        "game", "games", "match", "matches", "schedule", "score", "scores",
        "fixture", "fixtures", "next", "upcoming", "when is", "when do",
    )
    _ATHLETE_CONTEXT_TERMS = (
        "performance",
        "played",
        "goals",
        "assists",
        "match",
        "game",
        "yesterday",
        "today",
        "last night",
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
        ("Football", ("ronaldo", "cristiano ronaldo", "messi", "lionel messi", "mbappe", "mbappé", "haaland")),
        ("UFC", ("ufc", "mma", "fight card", "fight night", "octagon")),
        ("Boxing", ("boxing", "title fight", "fight card")),
        ("Cricket", ("cricket", "ipl", "test match", "odi", "t20")),
        ("Tennis", ("tennis", "atp", "wta", "grand slam", "sinner", "alcaraz")),
        ("NFL", ("nfl", "super bowl", "american football") + _NFL_TEAM_TERMS),
    )

    def __init__(
        self,
        vault_root: Path,
        web_searcher: WebSearcher | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.web_searcher = web_searcher or self._default_web_searcher
        self.tool_registry = tool_registry or ToolRegistry()
        if "sports.web_search" not in self.tool_registry.names():
            self.tool_registry.register(
                CapabilityRecord(
                    name="sports.web_search",
                    namespace="sports",
                    access=CapabilityAccess.READ,
                    allowed_agents=frozenset({self.name}),
                    stream_label="Searching sports",
                    adapter=lambda payload: self.web_searcher(str(payload.get("query") or "")),
                    input_schema={"type":"object","properties":{"query":{"type":"string"}},"required":["query"],"additionalProperties":False},
                )
            )

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        if any(guard in lowered for guard in self._NON_SPORT_GUARDS):
            return False
        team_schedule = any(self._has_phrase(lowered, term) for term in self._NFL_TEAM_TERMS) and any(
            self._has_phrase(lowered, marker) for marker in self._TEAM_EVENT_TERMS
        )
        if team_schedule:
            return True
        athlete_terms = ("ronaldo", "cristiano ronaldo", "messi", "lionel messi", "mbappe", "mbappé", "haaland")
        if any(self._has_phrase(lowered, term) for term in athlete_terms):
            return any(self._has_phrase(lowered, term) for term in self._ATHLETE_CONTEXT_TERMS)
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
        search_result = self.tool_registry.invoke(
            "sports.web_search",
            {"query": self._search_query(query, league, source_budget)},
            agent_name=self.name,
        )
        provider = str(search_result.get("provider") or "") if isinstance(search_result, dict) else ""
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
        selected = self._rank_sources(query, sources)[:source_budget]
        summary = self._compose_answer(query, selected, search_output)

        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis=(
                "Used on-demand public web research"
                + (" via SerpAPI" if provider.casefold() == "serpapi" else "")
                + "."
            ),
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
                min_sources = 5 if "official schedule standings news reports" in query else 3
                if hasattr(client, "fresh_google_search"):
                    result = client.fresh_google_search(query, num=8, min_sources=min_sources)
                    return {**result, "provider": "serpapi"} if isinstance(result, dict) else result
                return {
                    "text": client.fresh_google_search_text(query, num=5),
                    "sources": [],
                    "provider": "serpapi",
                }
            except Exception:
                pass
        return web_search.invoke({"query": query})

    def _search_query(self, query: str, league: str, source_budget: int) -> str:
        if self._schedule_intent(query):
            year = datetime.now(timezone.utc).year
            if league == "Formula-One":
                return f"{query} {year} official Formula 1 calendar next Grand Prix race date schedule"
            if league == "NBA":
                return f"{query} {year} official NBA schedule next game date fixtures"
            if league in {"FIFA-World-Cup", "Football", "Champions-League", "Premier-League"}:
                return f"{query} {year} official fixtures next match schedule date"
            return f"{query} {year} official schedule next match game race date fixtures"
        multi_source_hint = "official schedule standings news reports" if source_budget >= 5 else "official latest"
        return f"{query} latest {league} scores schedule news injuries analysis {multi_source_hint}"

    def _schedule_intent(self, query: str) -> bool:
        lowered = query.lower()
        has_next = any(marker in lowered for marker in ("next", "upcoming", "when is", "fixture", "fixtures", "schedule"))
        has_event = any(
            marker in lowered
            for marker in (
                "race",
                "grand prix",
                "match",
                "game",
                "fixture",
                "fixtures",
                "schedule",
                "vs",
            )
        )
        return has_next and has_event

    def _normalize_search_result(self, search_result: WebSearchResult) -> tuple[str, list[dict[str, Any]]]:
        if isinstance(search_result, dict):
            text = str(search_result.get("text") or "")
            raw_facts = search_result.get("facts")
            facts = [str(item) for item in raw_facts if str(item).strip()] if isinstance(raw_facts, list) else []
            if facts:
                text = "\n".join(facts)
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
            "performance",
            "career",
            "all time",
            "all-time",
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

    def _rank_sources(self, query: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lowered_query = query.lower()
        query_terms = [
            term
            for term in re.findall(r"[a-z0-9]+", lowered_query)
            if len(term) > 3 and term not in {"latest", "yesterday", "today", "performance", "official"}
        ]
        now = datetime.now(timezone.utc).date()
        yesterday = now.fromordinal(now.toordinal() - 1)
        short_month = yesterday.strftime("%b")
        long_month = yesterday.strftime("%B")
        yesterday_markers = {
            yesterday.strftime("%Y-%m-%d").lower(),
            f"{short_month} {yesterday.day}, {yesterday.year}".lower(),
            f"{long_month} {yesterday.day}, {yesterday.year}".lower(),
        }
        current_month = now.strftime("%b").lower()
        current_month_full = now.strftime("%B").lower()

        schedule_intent = self._schedule_intent(query)
        official_schedule_domains = {
            "formula1.com",
            "fifa.com",
            "nba.com",
            "uefa.com",
            "premierleague.com",
        }
        schedule_terms = ("schedule", "calendar", "fixture", "fixtures", "race date", "grand prix", "next", "match")
        low_value_domains = {
            "support.google.com",
            "vividseats.com",
            "stubhub.com",
            "seatgeek.com",
            "ticketmaster.com",
            "sportbusy.com",
        }

        recency_intent = any(term in lowered_query for term in ("yesterday", "today", "latest", "performance"))

        def source_date(text: str) -> int:
            dates = []
            for pattern, formats in (
                (r"\b\d{4}-\d{2}-\d{2}\b", ("%Y-%m-%d",)),
                (r"\b[a-z]+\s+\d{1,2},\s+\d{4}\b", ("%b %d, %Y", "%B %d, %Y")),
            ):
                for match in re.findall(pattern, text):
                    for date_format in formats:
                        try:
                            parsed = datetime.strptime(match, date_format).date()
                        except ValueError:
                            continue
                        if parsed <= now:
                            dates.append(parsed.toordinal())
                        break
            return max(dates, default=0)

        def score(source: dict[str, Any]) -> tuple[float, int]:
            text = " ".join(
                str(source.get(key) or "")
                for key in ("title", "snippet", "domain", "provider_label", "url")
            ).lower()
            value = sum(2 for term in query_terms if term in text)
            domain = str(source.get("domain") or "").lower().removeprefix("www.")
            if schedule_intent:
                value += sum(5 for term in schedule_terms if term in text)
                if domain in official_schedule_domains:
                    value += 14
                if "official" in text:
                    value += 6
                if any(noise in text for noise in ("standings", "rumours", "rumors", "gossip", "regulations", "beginner's guide")):
                    value -= 8
            if any(marker and marker in text for marker in yesterday_markers):
                value += 12
            if "yesterday" in lowered_query or "today" in lowered_query or "latest" in lowered_query:
                if str(now.year) in text and (current_month in text or current_month_full in text):
                    value += 6
            if domain in low_value_domains:
                value -= 50
            if any(noise in text for noise in ("buy tickets", "ticket prices", "tickets for sale", "coupon", "promo code")):
                value -= 30
            published = source_date(text) if recency_intent else 0
            if published:
                # Let actual dated freshness outweigh minor wording differences
                # such as "Cristiano Ronaldo" versus "Portugal's Ronaldo".
                value -= (now.toordinal() - published) / 30
            return value, published

        return sorted(sources, key=score, reverse=True)

    def _compose_answer(self, query: str, sources: list[dict], search_output: str) -> str:
        ranked_source_snapshot = (
            self._snapshot_from_sources(query, sources)
            if self._should_prioritize_ranked_source_snapshot(query)
            else ""
        )
        snapshot = (
            self._snapshot_from_search_output(search_output)
            if self._looks_like_rich_markdown(search_output)
            else self._formula_one_schedule_answer(query, sources, search_output)
        )
        snapshot = (
            snapshot
            or ranked_source_snapshot
            or self._snapshot_from_search_output(search_output)
            or self._snapshot_from_sources(query, sources)
        )
        if self._schedule_intent(query) and re.search(r"\bnext\b", query, re.I) and not re.search(r"\b(?:full|all|season|fixtures|schedule|calendar)\b", query, re.I):
            snapshot = self._next_event_snapshot(snapshot)
        lines: list[str] = []
        if snapshot:
            lines.append(snapshot)
        else:
            lines.append(f"Here is the live sports snapshot for: {query}.")

        table = self._world_cup_goals_table(query, search_output, sources)
        if table:
            lines.append(table)
        return "\n\n".join(line for line in lines if line.strip())

    @staticmethod
    def _next_event_snapshot(snapshot: str) -> str:
        if snapshot.startswith("Official Formula 1 calendar excerpt:"):
            return snapshot[:600]
        # Keep a singular next-game request singular. Convert the actual dated
        # source time with DST rules, rather than guessing a US/India offset.
        sentence = re.split(r"(?<=[.!?])\s+", snapshot.split("\n", 1)[0], maxsplit=1)[0]
        match = re.search(
            r"(?P<date>(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}),?\s+(?:at\s+)?"
            r"(?P<clock>\d{1,2}:\d{2}\s*[AP]M)\s+(?P<zone>EDT|EST|ET|CDT|CST|CT|MDT|MST|MT|PDT|PST|PT)\b",
            sentence, re.I,
        )
        if not match:
            return sentence
        zones={label:zone for labels,zone in [(('EDT','EST','ET'),'America/New_York'),(('CDT','CST','CT'),'America/Chicago'),(('MDT','MST','MT'),'America/Denver'),(('PDT','PST','PT'),'America/Los_Angeles')] for label in labels}
        try:
            date_text=re.sub(r"^[A-Za-z]+,?\s+(?=[A-Za-z]+\s+\d)","",match.group('date'))
            source=datetime.strptime(date_text+' '+match.group('clock').upper(),'%B %d, %Y %I:%M %p').replace(tzinfo=ZoneInfo(zones[match.group('zone').upper()]))
            local=source.astimezone(ZoneInfo(os.getenv('VELLUM_USER_TIMEZONE','Asia/Kolkata')))
            label='IST' if local.tzinfo.key in {'Asia/Kolkata','Asia/Calcutta'} else local.tzname()
            clock=local.strftime('%I:%M %p').lstrip('0')
            replacement=f"{local.strftime('%A, %B %d, %Y')} at {clock} {label} ({match.group('clock')} {match.group('zone').upper()})"
            return sentence[:match.start()]+replacement+sentence[match.end():]
        except (KeyError, ValueError):
            return sentence

    def _should_prioritize_ranked_source_snapshot(self, query: str) -> bool:
        lowered = query.lower()
        return any(marker in lowered for marker in ("yesterday", "today", "performance"))

    def _formula_one_schedule_answer(self, query: str, sources: list[dict], search_output: str) -> str:
        lowered = query.lower()
        if not self._schedule_intent(query) or not any(marker in lowered for marker in ("f1", "formula 1", "formula one", "grand prix")):
            return ""
        if re.search(r"\bthe next formula 1 race is\b", search_output, re.I):
            return self._snapshot_from_search_output(search_output)

        # A country mentioned in an annual calendar does not establish the next
        # race. Preserve the official excerpt rather than inventing a fixed GP,
        # venue or year from unrelated search fragments.
        for source in sources:
            domain = str(source.get("domain") or "").lower().removeprefix("www.")
            snippet = str(source.get("snippet") or "").strip()
            if domain == "formula1.com" and snippet and re.search(r"\bnext\b", snippet, re.I):
                return f"Official Formula 1 calendar excerpt: {snippet}"
        return ""

    def _snapshot_from_search_output(self, search_output: str) -> str:
        if not search_output:
            return ""
        search_output = self._clean_search_output(search_output)
        if self._looks_like_rich_markdown(search_output):
            return search_output
        first_block = search_output.split("\n\n---\n\n", 1)[0]
        clean_lines = [
            line.strip().strip("*").strip()
            for line in first_block.splitlines()
            if line.strip() and not line.strip().startswith(("http://", "https://"))
        ]
        snapshot = " ".join(clean_lines).strip()
        if self._is_low_value_snapshot(snapshot):
            return ""
        return snapshot[:1200]

    def _clean_search_output(self, search_output: str) -> str:
        visible = re.split(
            r"(?im)^\s{0,3}#{1,6}\s+(?:references|sources|sources checked|evidence)\s*$",
            search_output,
            maxsplit=1,
        )[0]
        visible = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", visible)
        visible = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", visible)
        visible = re.sub(r"(?<!\w)\[(?:\d+)\](?!\w)", "", visible)
        visible = visible.replace(r"\(", "").replace(r"\)", "")
        visible = visible.replace(r"\-", "-").replace(r"\|", "|")
        return re.sub(r"\n{3,}", "\n\n", visible).strip()

    def _looks_like_rich_markdown(self, text: str) -> bool:
        return bool(
            re.search(r"(?m)^#{1,6}\s+\S", text)
            or re.search(r"(?m)^\|.+\|$", text)
            or re.search(r"(?m)^-\s+\S", text)
        )

    def _is_low_value_snapshot(self, snapshot: str) -> bool:
        lowered = snapshot.lower()
        low_value_markers = (
            "google sports data",
            "this response uses data provided by google sports",
            "no web results found",
        )
        return any(marker in lowered for marker in low_value_markers)

    def _snapshot_from_sources(self, query: str, sources: list[dict]) -> str:
        lowered = query.lower()
        if not (
            any(marker in lowered for marker in ("yesterday", "today", "latest", "performance"))
            or self._schedule_intent(query)
        ):
            return ""
        for source in sources:
            title = str(source.get("title") or "").strip()
            snippet = str(source.get("snippet") or "").strip()
            if snippet:
                return f"{title}: {snippet}"[:1200]
        return ""

    def _world_cup_goals_table(self, query: str, search_output: str, sources: list[dict]) -> str:
        lowered = query.lower()
        if "world cup" not in lowered or "goal" not in lowered:
            return ""
        combined = " ".join(
            [search_output, *(str(source.get("snippet") or "") for source in sources)]
        )
        candidates = [
            ("Lionel Messi", "Argentina"),
            ("Miroslav Klose", "Germany"),
            ("Ronaldo", "Brazil"),
            ("Kylian Mbappé", "France"),
            ("Kylian Mbappe", "France"),
            ("Gerd Müller", "Germany"),
            ("Gerd Muller", "Germany"),
            ("Just Fontaine", "France"),
            ("Pelé", "Brazil"),
            ("Pele", "Brazil"),
        ]
        rows: list[tuple[str, str, int]] = []
        for player, country in candidates:
            pattern = re.compile(rf"{re.escape(player)}[^0-9]{{0,80}}(\d{{1,2}})|(\d{{1,2}})[^A-Za-z]{{0,20}}{re.escape(player)}", re.I)
            match = pattern.search(combined)
            if not match:
                continue
            goals = int(next(group for group in match.groups() if group))
            display = (
                player.replace("Mbappe", "Mbappé")
                .replace("Muller", "Müller")
                .replace("Pele", "Pelé")
            )
            if (display, country, goals) not in rows:
                rows.append((display, country, goals))
        if not rows:
            return ""
        rows.sort(key=lambda row: (-row[2], row[0]))
        table_lines = [
            "FIFA World Cup all-time goals table from the retrieved sources:",
            "",
            "| Rank | Player | Country | Goals |",
            "| --- | --- | --- | ---: |",
        ]
        previous_goals: int | None = None
        previous_rank = 0
        for index, (player, country, goals) in enumerate(rows[:8], start=1):
            rank = previous_rank if previous_goals == goals else index
            previous_rank = rank
            previous_goals = goals
            rank_text = f"T{rank}" if any(other_goals == goals for other_player, _, other_goals in rows if other_player != player) else str(rank)
            table_lines.append(f"| {rank_text} | {player} | {country} | {goals} |")
        return "\n".join(table_lines)

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None
