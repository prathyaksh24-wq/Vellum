#!/usr/bin/env python3
"""Fetch small no-key sports live snapshots into the Obsidian vault."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


F1_DRIVER_INTERESTS = (
    "Lewis Hamilton",
    "George Russell",
    "Kimi Antonelli",
    "Charles Leclerc",
    "Oscar Piastri",
    "Max Verstappen",
)
ESPN_SOCCER = {
    "Premier League": "eng.1",
    "Champions League": "uefa.champions",
}
SERPAPI_QUERIES = (
    "Champions League final 2026 live score lineups player stats",
    "Arsenal PSG Champions League final 2026 live score",
)


class SportsApiClient:
    def nba_scoreboard(self) -> dict[str, Any]:
        return _get_json("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json")

    def nba_boxscore(self, game_id: str) -> dict[str, Any]:
        return _get_json(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json")

    def openf1_drivers_latest(self) -> list[dict[str, Any]]:
        data = _get_json("https://api.openf1.org/v1/drivers", params={"session_key": "latest"})
        return data if isinstance(data, list) else []

    def espn_scoreboard(self, sport_slug: str) -> dict[str, Any]:
        return _get_json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{sport_slug}/scoreboard")

    def fpl_bootstrap(self) -> dict[str, Any]:
        return _get_json("https://fantasy.premierleague.com/api/bootstrap-static/")

    def fpl_fixtures(self) -> list[dict[str, Any]]:
        data = _get_json("https://fantasy.premierleague.com/api/fixtures/")
        return data if isinstance(data, list) else []

    def fpl_event_live(self, event_id: int) -> dict[str, Any]:
        return _get_json(f"https://fantasy.premierleague.com/api/event/{event_id}/live/")

    def serpapi_search(self, query: str, token: str) -> dict[str, Any]:
        return _get_json(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": token},
        )


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.nba.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


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


def frontmatter(kind: str, captured_at: str) -> list[str]:
    return [
        "---",
        f"type: {kind}",
        f"captured_at: {yaml_quote(captured_at)}",
        "tags:",
        "  - sports",
        "  - api-snapshot",
        "---",
        "",
    ]


def code_block(payload: Any) -> list[str]:
    return ["", "## Raw", "", "```json", json.dumps(payload, ensure_ascii=False, indent=2), "```", ""]


def nba_games(payload: dict[str, Any]) -> list[dict[str, Any]]:
    scoreboard = payload.get("scoreboard") if isinstance(payload, dict) else {}
    games = scoreboard.get("games") if isinstance(scoreboard, dict) else []
    return games if isinstance(games, list) else []


def nba_scoreboard_markdown(payload: dict[str, Any], captured_at: str) -> str:
    lines = [
        *frontmatter("sports_nba_live_scoreboard", captured_at),
        "# NBA Live Scoreboard",
        "",
        "- Source: NBA CDN liveData scoreboard",
        "",
        "## Games",
        "",
    ]
    for game in nba_games(payload):
        home = game.get("homeTeam", {})
        away = game.get("awayTeam", {})
        lines.append(
            f"- `{game.get('gameId', 'unknown')}` {away.get('teamName', 'Away')} {away.get('score', '-')}"
            f" @ {home.get('teamName', 'Home')} {home.get('score', '-')} - {game.get('gameStatusText', '')}"
        )
    lines.extend(code_block(payload))
    return "\n".join(lines)


def nba_boxscore_markdown(game_id: str, payload: dict[str, Any], captured_at: str) -> str:
    lines = [
        *frontmatter("sports_nba_boxscore", captured_at),
        f"# NBA Box Score - {game_id}",
        "",
        "- Source: NBA CDN liveData boxscore",
        "",
        "## Player Stats",
        "",
    ]
    game = payload.get("game") if isinstance(payload, dict) else {}
    for side in ("homeTeam", "awayTeam"):
        team = game.get(side, {}) if isinstance(game, dict) else {}
        players = team.get("players", []) if isinstance(team, dict) else []
        for player in players[:15]:
            name = player.get("name") or player.get("nameI") or player.get("familyName", "unknown")
            points = player.get("points", player.get("pts", "-"))
            rebounds = player.get("reboundsTotal", player.get("reb", "-"))
            assists = player.get("assists", player.get("ast", "-"))
            lines.append(f"- {name}: {points} pts, {rebounds} reb, {assists} ast")
    lines.extend(code_block(payload))
    return "\n".join(lines)


def f1_driver_markdown(name: str, driver: dict[str, Any], captured_at: str) -> str:
    lines = [
        *frontmatter("sports_f1_driver_snapshot", captured_at),
        f"# {name}",
        "",
        "- Source: OpenF1 latest session drivers",
        f"- Driver number: {driver.get('driver_number', 'unknown')}",
        f"- Team: {driver.get('team_name', 'unknown')}",
        "",
        "## Preference Context",
        "",
        "- Mercedes is the favorite F1 team.",
        "- Also track Hamilton and Charles at Ferrari, plus Oscar and Max.",
    ]
    lines.extend(code_block(driver))
    return "\n".join(lines)


def espn_scoreboard_markdown(name: str, payload: dict[str, Any], captured_at: str) -> str:
    lines = [
        *frontmatter("sports_football_live_scoreboard", captured_at),
        f"# {name} Live Scoreboard",
        "",
        "- Source: ESPN public scoreboard",
        "",
        "## Events",
        "",
    ]
    for event in payload.get("events", [])[:20]:
        status = event.get("status", {}).get("type", {}).get("description", "")
        lines.append(f"- {event.get('name', 'unknown')} - {status}")
    lines.extend(code_block(payload))
    return "\n".join(lines)


def fpl_markdown(bootstrap: dict[str, Any], fixtures: list[dict[str, Any]], live: dict[str, Any] | None, captured_at: str) -> str:
    lines = [
        *frontmatter("sports_premier_league_fpl_snapshot", captured_at),
        "# Premier League Fantasy Player Stats",
        "",
        "- Source: official Fantasy Premier League JSON",
        "",
        "## Top Players",
        "",
    ]
    elements = bootstrap.get("elements", []) if isinstance(bootstrap, dict) else []
    top = sorted(elements, key=lambda item: item.get("total_points", 0), reverse=True)[:20]
    for player in top:
        lines.append(f"- {player.get('web_name', 'unknown')}: {player.get('total_points', 0)} pts")
    lines.extend(["", "## Current Fixtures", ""])
    for fixture in fixtures[:12]:
        lines.append(f"- Fixture {fixture.get('id', 'unknown')}: team {fixture.get('team_h')} vs team {fixture.get('team_a')}")
    lines.extend(code_block({"bootstrap": bootstrap, "fixtures": fixtures, "live": live}))
    return "\n".join(lines)


def serpapi_markdown(results: list[dict[str, Any]], captured_at: str) -> str:
    lines = [
        *frontmatter("sports_serpapi_search_snapshot", captured_at),
        "# Champions League Final 2026 Search Snapshot",
        "",
        "- Source: SerpAPI Google Search",
        "- Use as fallback when structured live data is missing or stale.",
    ]
    lines.extend(code_block(results))
    return "\n".join(lines)


def root_index(captured_at: str, records: list[dict[str, Any]], skipped: list[dict[str, str]]) -> str:
    lines = [
        *frontmatter("sports_collection", captured_at),
        "# Sports Archive",
        "",
        "## Start Here",
        "",
        "- [[Sports/NBA/live-scoreboard|NBA Live Scoreboard]]",
        "- [[Sports/Formula One/_index|Formula One]]",
        "- [[Sports/Football/Premier League/live-scoreboard|Premier League Live Scoreboard]]",
        "- [[Sports/Football/Champions League/live-scoreboard|Champions League Live Scoreboard]]",
        "- [[Sports/Football/Champions League/final-2026/serpapi-search|Champions League Final Search Snapshot]]",
        "",
        "## User Preference Model",
        "",
        "- Sports idols: Lewis Hamilton, Steph Curry, LeBron James, Kobe Bryant, Michael Jordan.",
        "- Watch for quotes, work ethic, charisma, leadership, and mentality.",
        "- Favorite F1 team: Mercedes.",
        "- Also track George Russell, Kimi Antonelli, Hamilton and Charles at Ferrari, Oscar Piastri, and Max Verstappen.",
        "",
        "## Latest Snapshot",
        "",
        f"- Captured: {captured_at}",
        f"- Records written: {len(records)}",
        f"- Sources skipped: {len(skipped)}",
        "",
    ]
    return "\n".join(lines)


def simple_index(title: str, links: list[str], captured_at: str) -> str:
    return "\n".join([*frontmatter("sports_index", captured_at), f"# {title}", "", *[f"- {link}" for link in links], ""])


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def current_fpl_event_id(bootstrap: dict[str, Any]) -> int | None:
    events = bootstrap.get("events", []) if isinstance(bootstrap, dict) else []
    for event in events:
        if event.get("is_current"):
            return event.get("id")
    for event in events:
        if event.get("is_next"):
            return event.get("id")
    return None


def run(project_root: Path, dry_run: bool, client: SportsApiClient | Any | None = None, serpapi_token: str | None = None) -> int:
    client = client or SportsApiClient()
    serpapi_token = env_token(project_root, "SERPAPI_API_KEY") if serpapi_token is None else serpapi_token
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    try:
        nba_scoreboard = client.nba_scoreboard()
        records.append({"source": "nba-cdn", "kind": "nba_scoreboard", "name": "NBA Live Scoreboard", "payload": nba_scoreboard})
        for game in nba_games(nba_scoreboard)[:5]:
            game_id = str(game.get("gameId", "")).strip()
            if not game_id:
                continue
            try:
                records.append({"source": "nba-cdn", "kind": "nba_boxscore", "name": game_id, "payload": client.nba_boxscore(game_id)})
            except Exception as exc:
                skipped.append({"source": "nba-cdn", "reason": f"boxscore {game_id}: {exc}"})
    except Exception as exc:
        skipped.append({"source": "nba-cdn", "reason": str(exc)})

    try:
        f1_drivers = client.openf1_drivers_latest()
        by_name = {str(driver.get("full_name", "")).casefold(): driver for driver in f1_drivers}
        for name in F1_DRIVER_INTERESTS:
            driver = by_name.get(name.casefold()) or {"full_name": name, "note": "Not present in latest OpenF1 session driver list."}
            records.append({"source": "openf1", "kind": "f1_driver", "name": name, "payload": driver})
    except Exception as exc:
        skipped.append({"source": "openf1", "reason": str(exc)})

    for competition, slug in ESPN_SOCCER.items():
        try:
            records.append({"source": "espn", "kind": "espn_scoreboard", "name": competition, "payload": client.espn_scoreboard(slug)})
        except Exception as exc:
            skipped.append({"source": "espn", "reason": f"{competition}: {exc}"})

    try:
        fpl_bootstrap = client.fpl_bootstrap()
        fpl_fixtures = client.fpl_fixtures()
        event_id = current_fpl_event_id(fpl_bootstrap)
        fpl_live = client.fpl_event_live(event_id) if event_id is not None else None
        records.append(
            {
                "source": "fpl",
                "kind": "fpl_player_stats",
                "name": "Premier League Fantasy Player Stats",
                "payload": {"bootstrap": fpl_bootstrap, "fixtures": fpl_fixtures, "live": fpl_live},
            }
        )
    except Exception as exc:
        skipped.append({"source": "fpl", "reason": str(exc)})

    if serpapi_token:
        try:
            results = [{"query": query, "result": client.serpapi_search(query, serpapi_token)} for query in SERPAPI_QUERIES]
            records.append({"source": "serpapi", "kind": "serpapi_champions_league_final", "name": "Champions League Final 2026", "payload": results})
        except Exception as exc:
            skipped.append({"source": "serpapi", "reason": str(exc)})
    else:
        skipped.append({"source": "serpapi", "reason": "SERPAPI_API_KEY missing"})

    if dry_run:
        print(json.dumps({"records": len(records), "skipped": skipped}, indent=2))
        return 0

    sports = vault_path(project_root) / "Sports"
    sports.mkdir(parents=True, exist_ok=True)

    for record in records:
        kind = record["kind"]
        name = record["name"]
        payload = record["payload"]
        if kind == "nba_scoreboard":
            write_text(sports / "NBA" / "live-scoreboard.md", nba_scoreboard_markdown(payload, captured_at))
        elif kind == "nba_boxscore":
            write_text(sports / "NBA" / "games" / f"{name}.md", nba_boxscore_markdown(name, payload, captured_at))
        elif kind == "f1_driver":
            write_text(sports / "Formula One" / "drivers" / f"{slugify(name)}.md", f1_driver_markdown(name, payload, captured_at))
        elif kind == "espn_scoreboard":
            write_text(sports / "Football" / name / "live-scoreboard.md", espn_scoreboard_markdown(name, payload, captured_at))
        elif kind == "fpl_player_stats":
            write_text(
                sports / "Football" / "Premier League" / "fantasy-player-stats.md",
                fpl_markdown(payload["bootstrap"], payload["fixtures"], payload["live"], captured_at),
            )
        elif kind == "serpapi_champions_league_final":
            write_text(sports / "Football" / "Champions League" / "final-2026" / "serpapi-search.md", serpapi_markdown(payload, captured_at))

    write_text(sports / "NBA" / "_index.md", simple_index("NBA", ["[[live-scoreboard|Live Scoreboard]]"], captured_at))
    write_text(
        sports / "Formula One" / "_index.md",
        simple_index("Formula One", [f"[[Sports/Formula One/drivers/{slugify(name)}|{name}]]" for name in F1_DRIVER_INTERESTS], captured_at),
    )
    write_text(
        sports / "Football" / "Premier League" / "_index.md",
        simple_index("Premier League", ["[[live-scoreboard|Live Scoreboard]]", "[[fantasy-player-stats|Fantasy Player Stats]]"], captured_at),
    )
    write_text(
        sports / "Football" / "Champions League" / "_index.md",
        simple_index("Champions League", ["[[live-scoreboard|Live Scoreboard]]", "[[final-2026/serpapi-search|Final 2026 Search Snapshot]]"], captured_at),
    )
    write_text(sports / "_index.md", root_index(captured_at, records, skipped))
    write_jsonl(sports / "sports-snapshots.jsonl", records)
    write_text(
        sports / ".state" / "sports_snapshot_state.json",
        json.dumps({"last_run_utc": captured_at, "written_count": len(records), "skipped": skipped}, ensure_ascii=False, indent=2) + "\n",
    )
    print(f"Wrote {len(records)} sports snapshot records to {sports}")
    if skipped:
        print(f"Skipped {len(skipped)} sources; see .state/sports_snapshot_state.json")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    try:
        return run(args.project_root.resolve(), dry_run=args.dry_run)
    except Exception as exc:
        print(f"sports snapshot import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
