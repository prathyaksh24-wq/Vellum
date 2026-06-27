#!/usr/bin/env python3
"""Fetch sports snapshots into the Obsidian vault via SerpAPI.

Single-mechanism fetcher: every league (NBA, Formula One, Premier League,
Champions League, Boxing, UFC, and the Ambient tier) is queried through
SerpAPI's Google Search engine. Structured `sports_results`, `knowledge_graph`,
`answer_box`, and `top_stories` blocks are extracted into a readable summary;
the raw JSON is kept below for the agent to inspect.

This script is invoked either manually (CLI) or by the curiosity-driven tool
at backend/agent/tools/sports_curiosity.py — there is no scheduler entry.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


ENABLED_LEAGUES: tuple[str, ...] = (
    "NBA",
    "Formula-One",
    "Premier-League",
    "Champions-League",
    "Ambient",
)

DISABLED_LEAGUES: tuple[str, ...] = (
    "Boxing",
    "UFC",
)

LEAGUES: tuple[str, ...] = ENABLED_LEAGUES
ALL_KNOWN_LEAGUES: tuple[str, ...] = ENABLED_LEAGUES + DISABLED_LEAGUES

QUERY_TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "NBA": {
        "in_season": (
            "NBA games today scores box score",
            "NBA standings playoffs 2026",
            "NBA news today",
        ),
        "playoffs": (
            "NBA playoffs tonight scores box score",
            "NBA conference finals series result",
            "NBA playoffs bracket 2026",
        ),
        "finals": (
            "NBA Finals tonight score box score",
            "NBA Finals series result 2026",
            "NBA Finals MVP race",
        ),
        "offseason": (
            "NBA offseason news trades signings",
            "NBA draft 2026 latest news",
        ),
    },
    "Formula-One": {
        "in_season": (
            "F1 race weekend results qualifying standings",
            "F1 driver standings 2026",
            "F1 constructor standings 2026",
        ),
        "offseason": (
            "F1 driver market news this week",
            "F1 testing news 2026",
        ),
    },
    "Premier-League": {
        "in_season": (
            "Premier League fixtures this week results",
            "Premier League standings 2025-26",
            "Premier League top scorers 2025-26",
        ),
        "finals": (
            "Premier League title race final matchday",
            "Premier League relegation final matchday",
        ),
        "offseason": (
            "Premier League transfer news today",
            "Premier League pre-season fixtures",
        ),
    },
    "Champions-League": {
        "in_season": (
            "Champions League fixtures results this week",
            "Champions League knockout bracket 2026",
        ),
        "finals": (
            "Champions League final 2026 live score lineups player stats",
            "Champions League final 2026 result reaction",
        ),
        "offseason": (
            "Champions League draw news qualifying",
            "Champions League 2026-27 group stage draw",
        ),
    },
    "Boxing": {
        "in_season": (
            "boxing results this week",
            "upcoming boxing fights this month",
            "boxing world title fights schedule",
        ),
        "offseason": (
            "boxing results this week",
            "upcoming boxing fights this month",
        ),
    },
    "UFC": {
        "in_season": (
            "UFC results this week",
            "UFC upcoming fight card",
            "UFC pound for pound rankings",
        ),
        "offseason": (
            "UFC results this week",
            "UFC upcoming fight card",
        ),
    },
    "Ambient": {
        "in_season": (
            "Sinner Alcaraz tennis match this week",
            "Real Madrid Barcelona El Clasico schedule",
            "tennis Grand Slam this week",
            "biggest sports rivalry match this week",
        ),
        "offseason": (
            "Sinner Alcaraz tennis match this week",
            "Real Madrid Barcelona El Clasico schedule",
            "tennis Grand Slam this week",
        ),
    },
}


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


class SportsApiClient:
    def serpapi_search(self, query: str, token: str) -> dict[str, Any]:
        return _get_json(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": token},
        )


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def vault_path(project_root: Path) -> Path:
    env_path = project_root / ".env"
    if not env_path.exists():
        return project_root / "Vault"
    load_dotenv(env_path)
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(configured).expanduser() if configured else project_root / "Vault"


def env_token(project_root: Path, key: str) -> str:
    load_dotenv(project_root / ".env")
    return os.environ.get(key, "").strip()


def slugify(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    return "-".join(words) or "item"


def yaml_quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def date_dd_mm_yyyy(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%d-%m-%Y")


def date_year(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y")


def frontmatter(
    league: str,
    season_state: str,
    queries: Iterable[str],
    extracted: Iterable[str],
    curiosity_reason: str,
    captured_at: str,
) -> list[str]:
    lines = [
        "---",
        f"type: sports_{slugify(league)}_serpapi_snapshot",
        f"captured_at: {yaml_quote(captured_at)}",
        f"league: {league}",
        f"season_state: {season_state}",
        f"curiosity_reason: {yaml_quote(curiosity_reason)}",
        "queries:",
    ]
    for query in queries:
        lines.append(f"  - {yaml_quote(query)}")
    lines.append("extracted:")
    for block in extracted:
        lines.append(f"  - {block}")
    lines += [
        "tags:",
        "  - sports",
        f"  - {slugify(league)}",
        "  - serpapi-snapshot",
        "---",
        "",
    ]
    return lines


def extract_sports_results(payload: dict[str, Any]) -> list[str]:
    """Pull structured live-scores/standings blocks out of a SerpAPI response."""
    results = payload.get("sports_results") or {}
    if not isinstance(results, dict) or not results:
        return []
    lines: list[str] = ["### sports_results"]
    title = results.get("title") or results.get("league") or "(untitled)"
    lines.append(f"- **{title}**")
    games = results.get("games") or results.get("game_spotlight") or []
    if isinstance(games, dict):
        games = [games]
    for game in games[:10]:
        if not isinstance(game, dict):
            continue
        teams = game.get("teams") or []
        if isinstance(teams, list) and len(teams) >= 2:
            a, b = teams[0], teams[1]
            a_name = a.get("name") if isinstance(a, dict) else str(a)
            b_name = b.get("name") if isinstance(b, dict) else str(b)
            a_score = a.get("score") if isinstance(a, dict) else "-"
            b_score = b.get("score") if isinstance(b, dict) else "-"
            status = game.get("status") or game.get("stage") or ""
            lines.append(f"  - {a_name} {a_score} vs {b_name} {b_score} — {status}")
        else:
            lines.append(f"  - {json.dumps(game, ensure_ascii=False)[:160]}")
    rankings = results.get("rankings") or results.get("standings") or []
    if rankings:
        lines.append("- rankings/standings:")
        for row in rankings[:12]:
            if not isinstance(row, dict):
                continue
            name = row.get("team") or row.get("name") or row.get("driver") or "?"
            stat = row.get("points") or row.get("score") or row.get("record") or ""
            lines.append(f"  - {name} — {stat}")
    return lines


def extract_knowledge_graph(payload: dict[str, Any]) -> list[str]:
    kg = payload.get("knowledge_graph") or {}
    if not isinstance(kg, dict) or not kg:
        return []
    lines: list[str] = ["### knowledge_graph"]
    title = kg.get("title") or "(untitled)"
    description = kg.get("description") or kg.get("snippet") or ""
    lines.append(f"- **{title}** — {description}")
    for key in ("date", "venue", "league", "next_event", "winner", "result"):
        val = kg.get(key)
        if val:
            lines.append(f"  - {key}: {val}")
    return lines


def extract_answer_box(payload: dict[str, Any]) -> list[str]:
    box = payload.get("answer_box") or {}
    if not isinstance(box, dict) or not box:
        return []
    lines: list[str] = ["### answer_box"]
    for key in ("title", "answer", "snippet", "result"):
        val = box.get(key)
        if val:
            lines.append(f"- {key}: {val}")
    return lines


def extract_top_stories(payload: dict[str, Any], limit: int = 8) -> list[str]:
    stories = payload.get("top_stories") or payload.get("news_results") or []
    if not isinstance(stories, list) or not stories:
        return []
    lines: list[str] = ["### top_stories"]
    for story in stories[:limit]:
        if not isinstance(story, dict):
            continue
        title = story.get("title") or "(untitled)"
        source = story.get("source") or story.get("source_name") or ""
        when = story.get("date") or story.get("published_date") or ""
        lines.append(f"- {title} — {source} ({when})")
    return lines


def summarize_serpapi(results: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Return (markdown_lines, extracted_block_names)."""
    summary: list[str] = ["## Summary", ""]
    extracted_blocks: set[str] = set()
    for entry in results:
        query = entry.get("query", "")
        payload = entry.get("result") or {}
        summary.append(f"### query: {query}")
        for name, fn in (
            ("sports_results", extract_sports_results),
            ("knowledge_graph", extract_knowledge_graph),
            ("answer_box", extract_answer_box),
            ("top_stories", extract_top_stories),
        ):
            block = fn(payload)
            if block:
                extracted_blocks.add(name)
                summary.extend(block)
                summary.append("")
    return summary, sorted(extracted_blocks)


def code_block(payload: Any) -> list[str]:
    return ["", "## Raw", "", "```json", json.dumps(payload, ensure_ascii=False, indent=2), "```", ""]


def serpapi_snapshot_markdown(
    league: str,
    season_state: str,
    queries: list[str],
    results: list[dict[str, Any]],
    curiosity_reason: str,
    captured_at: str,
) -> tuple[str, list[str]]:
    summary, extracted = summarize_serpapi(results)
    fm = frontmatter(
        league=league,
        season_state=season_state,
        queries=queries,
        extracted=extracted,
        curiosity_reason=curiosity_reason,
        captured_at=captured_at,
    )
    body = [
        f"# {league} — SerpAPI Snapshot",
        "",
        f"- Captured (UTC): {captured_at}",
        f"- Season state: {season_state}",
        f"- Reason: {curiosity_reason}",
        "",
        *summary,
    ]
    body.extend(code_block(results))
    return "\n".join(fm + body), extracted


def league_dir(vault: Path, league: str) -> Path:
    return vault / "Library" / "Sports" / league


def snapshot_dir(vault: Path, league: str, now: datetime | None = None) -> Path:
    if league == "Ambient":
        return league_dir(vault, league) / "notable-events" / date_year(now)
    return league_dir(vault, league) / "snapshots" / date_year(now)


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_state(path: Path, data: dict[str, Any]) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def serpapi_budget_check_and_decrement(
    state_path: Path, calls: int, dry_run: bool
) -> tuple[bool, dict[str, Any]]:
    """Return (allowed, reason_or_state). Decrements counters when allowed and not dry-run."""
    state = read_state(state_path)
    budget = state.setdefault("serpapi_budget", {"daily_cap": 40, "monthly_cap": 800})
    counters = state.setdefault("serpapi_counters", {})
    today = date.today().isoformat()
    month = today[:7]
    if counters.get("day") != today:
        counters["day"] = today
        counters["day_used"] = 0
    if counters.get("month") != month:
        counters["month"] = month
        counters["month_used"] = 0
    day_used = counters.get("day_used", 0)
    month_used = counters.get("month_used", 0)
    if day_used + calls > budget["daily_cap"]:
        return False, {"reason": "daily_cap_exhausted", "state": state}
    if month_used + calls > budget["monthly_cap"]:
        return False, {"reason": "monthly_cap_exhausted", "state": state}
    if not dry_run:
        counters["day_used"] = day_used + calls
        counters["month_used"] = month_used + calls
        write_state(state_path, state)
    return True, {"state": state}


def queries_for(league: str, season_state: str, sample: int | None = None) -> list[str]:
    templates = QUERY_TEMPLATES.get(league, {})
    pool = templates.get(season_state) or templates.get("in_season") or ()
    if not pool:
        return []
    if sample is None or sample >= len(pool):
        return list(pool)
    return random.sample(list(pool), sample)


def regenerate_latest(vault: Path, league: str, limit: int = 10) -> None:
    folder = snapshot_dir(vault, league)
    parent = folder.parent  # snapshots/ or notable-events/
    if not parent.exists():
        return
    files: list[Path] = []
    for year_dir in sorted(parent.iterdir(), reverse=True):
        if not year_dir.is_dir():
            continue
        files.extend(sorted(year_dir.glob("*.md"), reverse=True))
        if len(files) >= limit:
            break
    files = files[:limit]
    captured_at = utc_now_iso()
    lines = [
        "---",
        f"type: sports_{slugify(league)}_latest",
        f"captured_at: {yaml_quote(captured_at)}",
        f"league: {league}",
        "tags:",
        "  - sports",
        f"  - {slugify(league)}",
        "  - latest-feed",
        "---",
        "",
        f"# {league} — Latest Snapshots",
        "",
    ]
    if not files:
        lines.append("_No snapshots yet._")
    else:
        for path in files:
            rel = path.relative_to(league_dir(vault, league))
            link_target = str(rel).replace("\\", "/").rsplit(".md", 1)[0]
            display = path.stem
            lines.append(f"- [[Library/Sports/{league}/{link_target}|{display}]]")
    write_text(league_dir(vault, league) / "latest.md", "\n".join(lines) + "\n")


def fetch_league(
    league: str,
    season_state: str,
    vault: Path,
    project_root: Path,
    client: SportsApiClient,
    serpapi_token: str,
    curiosity_reason: str,
    queries: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not serpapi_token:
        return {"league": league, "skipped": True, "reason": "SERPAPI_API_KEY missing"}
    queries = queries or queries_for(league, season_state)
    if not queries:
        return {"league": league, "skipped": True, "reason": f"no queries for {league}/{season_state}"}

    state_path = vault / "Library" / "Sports" / ".state" / "snapshot_state.json"
    allowed, info = serpapi_budget_check_and_decrement(state_path, len(queries), dry_run)
    if not allowed:
        return {"league": league, "skipped": True, "reason": info["reason"]}

    captured_at = utc_now_iso()
    slug = slugify(queries[0])[:48] or "snapshot"
    filename = f"{date_dd_mm_yyyy()}-{slug}.md"
    out_path = snapshot_dir(vault, league) / filename

    if dry_run:
        # Don't hit the network on dry-run — that would waste SerpAPI credits
        # for a verification command.
        return {
            "league": league,
            "queries": queries,
            "extracted": [],
            "would_write": str(out_path),
            "captured_at": captured_at,
            "dry_run": True,
        }

    results: list[dict[str, Any]] = []
    for query in queries:
        try:
            results.append({"query": query, "result": client.serpapi_search(query, serpapi_token)})
        except Exception as exc:  # noqa: BLE001
            results.append({"query": query, "result": {"error": str(exc)}})

    markdown, extracted = serpapi_snapshot_markdown(
        league=league,
        season_state=season_state,
        queries=queries,
        results=results,
        curiosity_reason=curiosity_reason,
        captured_at=captured_at,
    )

    write_text(out_path, markdown)
    record = {
        "league": league,
        "season_state": season_state,
        "captured_at": captured_at,
        "queries": queries,
        "curiosity_reason": curiosity_reason,
        "extracted": extracted,
        "path": str(out_path.relative_to(vault)),
    }
    append_jsonl(vault / "Library" / "Sports" / "sports-snapshots.jsonl", record)
    regenerate_latest(vault, league)
    update_last_fetched(state_path, league, captured_at)
    return record


def update_last_fetched(state_path: Path, league: str, captured_at: str) -> None:
    state = read_state(state_path)
    last = state.setdefault("last_fetched", {})
    last[league] = captured_at
    write_state(state_path, state)


def load_curiosity(vault: Path) -> dict[str, Any]:
    return read_state(vault / "Library" / "Sports" / ".state" / "curiosity.json")


def season_state_for(curiosity: dict[str, Any], league: str) -> str:
    leagues = curiosity.get("leagues", {}) if isinstance(curiosity, dict) else {}
    entry = leagues.get(league, {}) if isinstance(leagues, dict) else {}
    return entry.get("season_state", "in_season")


FETCHERS: dict[str, Callable[..., dict[str, Any]]] = {}


def register_fetcher(league: str) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    def decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        FETCHERS[league] = fn
        return fn

    return decorator


def _league_fetcher(league: str) -> Callable[..., dict[str, Any]]:
    def fetch(
        vault: Path,
        project_root: Path,
        client: SportsApiClient,
        serpapi_token: str,
        curiosity_reason: str = "manual run",
        queries: list[str] | None = None,
        dry_run: bool = False,
        season_state: str | None = None,
    ) -> dict[str, Any]:
        curiosity = load_curiosity(vault)
        state = season_state or season_state_for(curiosity, league)
        return fetch_league(
            league=league,
            season_state=state,
            vault=vault,
            project_root=project_root,
            client=client,
            serpapi_token=serpapi_token,
            curiosity_reason=curiosity_reason,
            queries=queries,
            dry_run=dry_run,
        )

    fetch.__name__ = f"fetch_{slugify(league).replace('-', '_')}"
    FETCHERS[league] = fetch
    return fetch


fetch_nba = _league_fetcher("NBA")
fetch_formula_one = _league_fetcher("Formula-One")
fetch_premier_league = _league_fetcher("Premier-League")
fetch_champions_league = _league_fetcher("Champions-League")
fetch_boxing = _league_fetcher("Boxing")
fetch_ufc = _league_fetcher("UFC")
fetch_ambient = _league_fetcher("Ambient")


def run(
    project_root: Path,
    leagues: list[str] | None,
    dry_run: bool,
    curiosity_reason: str,
    client: SportsApiClient | None = None,
    serpapi_token: str | None = None,
) -> int:
    client = client or SportsApiClient()
    serpapi_token = env_token(project_root, "SERPAPI_API_KEY") if serpapi_token is None else serpapi_token
    vault = vault_path(project_root)
    targets = leagues or list(ENABLED_LEAGUES)

    results: list[dict[str, Any]] = []
    for league in targets:
        if league in DISABLED_LEAGUES:
            results.append({"league": league, "skipped": True, "reason": "disabled"})
            continue
        if league not in FETCHERS:
            results.append({"league": league, "skipped": True, "reason": "unknown league"})
            continue
        results.append(
            FETCHERS[league](
                vault=vault,
                project_root=project_root,
                client=client,
                serpapi_token=serpapi_token,
                curiosity_reason=curiosity_reason,
                dry_run=dry_run,
            )
        )

    if dry_run:
        print(json.dumps({"dry_run": True, "results": results}, indent=2, ensure_ascii=False))
        return 0

    written = sum(1 for r in results if not r.get("skipped"))
    skipped = [r for r in results if r.get("skipped")]
    print(f"Wrote {written} sports snapshot records to {vault / 'Library' / 'Sports'}")
    if skipped:
        for entry in skipped:
            print(f"  skipped {entry['league']}: {entry.get('reason', 'unknown')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--league",
        action="append",
        choices=ALL_KNOWN_LEAGUES,
        help="Restrict to one or more leagues (repeatable). Default: all.",
    )
    parser.add_argument(
        "--reason",
        default="manual CLI run",
        help="curiosity_reason value written into each snapshot's frontmatter",
    )
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    try:
        return run(
            project_root=args.project_root.resolve(),
            leagues=args.league,
            dry_run=args.dry_run,
            curiosity_reason=args.reason,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"sports snapshot import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
