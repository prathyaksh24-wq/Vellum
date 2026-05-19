#!/usr/bin/env python3
"""One-shot bootstrap for Vault/Library/Sports/.

Creates the folder tree, writes _index.md and agent-guide.md per league,
and seeds .state/curiosity.json + .state/snapshot_state.json with sane
defaults (including a SerpAPI budget). Idempotent: re-runs only overwrite
state files when --force is passed; markdown index files are always
overwritten so format drift is fixable by re-running.

Run once after pulling these changes. Not part of runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from import_sports_snapshots import (
    LEAGUES,
    QUERY_TEMPLATES,
    utc_now_iso,
    vault_path,
    write_text,
    yaml_quote,
)


SEASON_DEFAULTS: dict[str, dict[str, str | float]] = {
    "NBA": {"season_state": "playoffs", "season_weight": 0.85, "threshold": 0.65},
    "Formula-One": {"season_state": "in_season", "season_weight": 0.80, "threshold": 0.65},
    "Premier-League": {"season_state": "finals", "season_weight": 0.85, "threshold": 0.65},
    "Champions-League": {"season_state": "finals", "season_weight": 0.85, "threshold": 0.65},
    "Boxing": {"season_state": "in_season", "season_weight": 0.45, "threshold": 0.70},
    "UFC": {"season_state": "in_season", "season_weight": 0.45, "threshold": 0.70},
    "Ambient": {"season_state": "in_season", "season_weight": 0.30, "threshold": 0.80},
}

LEAGUE_KEYWORDS: dict[str, list[str]] = {
    "NBA": ["NBA", "Lakers", "Warriors", "Celtics", "LeBron", "Curry", "Jokic", "Tatum", "playoffs"],
    "Formula-One": ["F1", "Formula 1", "Mercedes", "Ferrari", "Verstappen", "Hamilton", "Leclerc", "Russell", "Piastri", "Antonelli"],
    "Premier-League": ["Premier League", "EPL", "Arsenal", "Liverpool", "Man City", "Manchester", "Chelsea", "Spurs", "Haaland"],
    "Champions-League": ["Champions League", "UCL", "Real Madrid", "PSG", "Bayern", "Barcelona"],
    "Boxing": ["boxing", "title fight", "Fury", "Usyk", "Canelo"],
    "UFC": ["UFC", "MMA", "octagon", "Jon Jones", "Pereira", "Volkanovski"],
    "Ambient": ["Sinner", "Alcaraz", "Djokovic", "El Clasico", "Wimbledon", "Roland Garros", "US Open", "Australian Open"],
}


def init_state_paths(vault: Path) -> dict[str, Path]:
    base = vault / "Library" / "Sports"
    return {
        "curiosity": base / ".state" / "curiosity.json",
        "snapshot": base / ".state" / "snapshot_state.json",
    }


def seed_curiosity(vault: Path, force: bool) -> Path:
    path = init_state_paths(vault)["curiosity"]
    if path.exists() and not force:
        return path
    leagues: dict[str, dict] = {}
    for league in LEAGUES:
        defaults = SEASON_DEFAULTS[league]
        leagues[league] = {
            "season_state": defaults["season_state"],
            "weights": {
                "recency_hunger": 0.25,
                "user_signal": 0.30 if league != "Ambient" else 0.60,
                "season_weight": defaults["season_weight"],
                "cross_feed_signal": 0.15,
                "stochastic_kick": 0.10,
            },
            "threshold": defaults["threshold"],
            "keywords": LEAGUE_KEYWORDS[league],
            "recency_hunger_max_hours": 168 if league not in ("Boxing", "UFC", "Ambient") else 336,
            "notes": "",
        }
    payload = {
        "version": 1,
        "updated": utc_now_iso(),
        "global": {
            "max_fetches_per_agent_turn": 1,
            "stochastic_range": [0.0, 0.15],
        },
        "leagues": leagues,
    }
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def seed_snapshot_state(vault: Path, force: bool) -> Path:
    path = init_state_paths(vault)["snapshot"]
    if path.exists() and not force:
        return path
    payload = {
        "version": 1,
        "serpapi_budget": {"daily_cap": 40, "monthly_cap": 800},
        "serpapi_counters": {"day": None, "day_used": 0, "month": None, "month_used": 0},
        "last_fetched": {},
    }
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def root_index_md(vault: Path) -> str:
    captured_at = utc_now_iso()
    lines = [
        "---",
        "type: sports_collection",
        f"captured_at: {yaml_quote(captured_at)}",
        "tags:",
        "  - sports",
        "  - collection",
        "---",
        "",
        "# Sports",
        "",
        "Live-tracking corpus for the leagues you follow, plus an **Ambient** tier",
        "for notable events in sports you don't normally watch.",
        "",
        "## Leagues",
        "",
    ]
    for league in LEAGUES:
        lines.append(f"- [[Library/Sports/{league}/_index|{league}]]")
    lines += [
        "",
        "## How fetching works",
        "",
        "Snapshots are **not scheduled**. The agent decides when to fetch based on a",
        "curiosity-drive model that combines recency, user signals (Honcho + recent",
        "queries), season state, cross-feed signals (X, YouTube), and a small",
        "stochastic kick. See `agent-guide.md` for details.",
        "",
        "All fetching uses **SerpAPI** as a single uniform mechanism — see",
        "`scripts/import_sports_snapshots.py`.",
        "",
    ]
    return "\n".join(lines) + "\n"


def root_agent_guide_md() -> str:
    captured_at = utc_now_iso()
    lines = [
        "---",
        "type: sports_agent_guide",
        f"captured_at: {yaml_quote(captured_at)}",
        "tags:",
        "  - sports",
        "  - agent-memory",
        "---",
        "",
        "# Sports Agent Guide",
        "",
        "## Retrieval Contract",
        "",
        "- Use `sports-snapshots.jsonl` for precise lookup by league, date, or query.",
        "- Use `<League>/latest.md` when freshness matters — top 10 dated snapshots, wikilinked.",
        "- Use `<League>/snapshots/YYYY/` to read a specific snapshot in full.",
        "- Use `<League>/topics/` (NBA) or `<League>/drivers/` (F1) for cross-cuts.",
        "- Use `Ambient/notable-events/` only for events in sports the user doesn't follow normally.",
        "",
        "## Curiosity Model",
        "",
        "Per-league scores live in `.state/curiosity.json`. Components:",
        "",
        "| Component | Source |",
        "|---|---|",
        "| recency_hunger | now − last_fetch_utc, capped at recency_hunger_max_hours |",
        "| user_signal | Honcho 7-day query, plus keyword scan of recent `Agent/Queries/` |",
        "| season_weight | league's `season_state` in curiosity.json |",
        "| cross_feed_signal | keyword hits in `Library/X/*/latest-*.md` and `Library/Youtube/**/latest-*.md` |",
        "| stochastic_kick | small random component (0.0–0.15) |",
        "",
        "Score crosses `threshold` (default 0.65; Ambient: 0.80) → eligible to fetch.",
        "**Eligibility is only checked opportunistically** during other agent activity.",
        "There is no scheduler entry for Sports.",
        "",
        "A SerpAPI budget guard in `.state/snapshot_state.json` blocks fetches once the",
        "daily or monthly cap is hit — the agent logs a suppression memory and answers",
        "from existing snapshots.",
        "",
        "## Self-Calibration",
        "",
        "After every fetch the agent writes `Agent/Memories/sports_<league>_fetch_<ts>.md`.",
        "The nightly digest reads these and gently adjusts per-league thresholds:",
        "",
        "- 5 consecutive unused fetches → raise threshold by 0.05",
        "- User asked a sports question but no recent fetch → lower threshold by 0.05",
        "",
        "## Freshness Caveat",
        "",
        "SerpAPI returns Google's index of live data. Scores can be ~1 minute stale",
        "vs a direct source feed. Acceptable for the user's 'stay in the loop' use case.",
        "",
    ]
    return "\n".join(lines) + "\n"


def league_index_md(league: str) -> str:
    captured_at = utc_now_iso()
    defaults = SEASON_DEFAULTS[league]
    lines = [
        "---",
        f"type: sports_{league.lower().replace('-', '_')}_collection",
        f"captured_at: {yaml_quote(captured_at)}",
        f"league: {league}",
        f"season_state: {defaults['season_state']}",
        "tags:",
        "  - sports",
        f"  - {league.lower()}",
        "---",
        "",
        f"# {league}",
        "",
        f"- Default season state: **{defaults['season_state']}**",
        f"- Curiosity threshold: **{defaults['threshold']}**",
        "",
        "## Entrypoints",
        "",
        f"- [[Library/Sports/{league}/latest|Latest snapshots]]",
        f"- [[Library/Sports/{league}/agent-guide|Agent guide for {league}]]",
        "",
        "## Subfolders",
        "",
        "- `snapshots/YYYY/` — dated SerpAPI snapshots",
    ]
    if league == "NBA":
        lines += [
            "- `topics/players/` — atomic notes per tracked player",
            "- `topics/storylines/` — running narratives (conference finals, rivalries)",
        ]
    elif league == "Formula-One":
        lines += [
            "- `drivers/` — one note per tracked driver",
            "- `standings/` — driver + constructor standings snapshots",
        ]
    elif league == "Premier-League":
        lines += [
            "- `fixtures.md` — rolling near-term fixtures",
            "- `standings.md` — current table snapshot",
        ]
    elif league == "Champions-League":
        lines += [
            "- `final-2026/` — Champions League final 2026 collection",
        ]
    elif league == "Ambient":
        lines = [line for line in lines if "snapshots/YYYY/" not in line]
        lines += [
            "- `notable-events/YYYY/` — significant events from sports the user doesn't normally follow",
        ]
    lines.append("")
    return "\n".join(lines) + "\n"


def league_agent_guide_md(league: str) -> str:
    captured_at = utc_now_iso()
    defaults = SEASON_DEFAULTS[league]
    templates = QUERY_TEMPLATES.get(league, {})
    lines = [
        "---",
        f"type: sports_{league.lower().replace('-', '_')}_agent_guide",
        f"captured_at: {yaml_quote(captured_at)}",
        f"league: {league}",
        "tags:",
        "  - sports",
        f"  - {league.lower()}",
        "  - agent-memory",
        "---",
        "",
        f"# {league} Agent Guide",
        "",
        "## Retrieval Contract",
        "",
        f"- Use `Library/Sports/{league}/latest.md` when freshness matters.",
        f"- Use `Library/Sports/{league}/snapshots/YYYY/` to read specific dated snapshots in full.",
        f"- Use `Library/Sports/sports-snapshots.jsonl` for cross-league lookup with `league: \"{league}\"`.",
        "",
        "## SerpAPI Query Templates",
        "",
    ]
    for state, queries in templates.items():
        lines.append(f"**{state}:**")
        for query in queries:
            lines.append(f"- `{query}`")
        lines.append("")
    lines += [
        "## Curiosity Notes",
        "",
        f"- Default season state: `{defaults['season_state']}`",
        f"- Default threshold: `{defaults['threshold']}`",
        f"- Default season_weight: `{defaults['season_weight']}`",
        "",
        "## Freshness Caveat",
        "",
        "Snapshots are SerpAPI-backed and can be ~1 minute stale on live in-play scores.",
        "",
    ]
    if league == "Ambient":
        lines += [
            "## What counts as 'notable' for Ambient",
            "",
            "Only fetch when there is a strong signal that the user might care:",
            "",
            "- Tennis: rivalry meetings (Sinner vs Alcaraz, Djokovic vs Alcaraz), Grand Slam finals.",
            "- Football outside Premier League / Champions League: El Clasico, World Cup, Euro finals.",
            "- Other sports: world records, historic firsts, major controversies.",
            "",
            "user_signal weight is doubled here — without a recent user mention, fetches are rare.",
            "",
        ]
    return "\n".join(lines) + "\n"


def seed_folder_tree(vault: Path) -> list[Path]:
    base = vault / "Library" / "Sports"
    base.mkdir(parents=True, exist_ok=True)
    (base / ".state").mkdir(exist_ok=True)
    written: list[Path] = []
    written.append(write_and_return(base / "_index.md", root_index_md(vault)))
    written.append(write_and_return(base / "agent-guide.md", root_agent_guide_md()))

    for league in LEAGUES:
        league_path = base / league
        league_path.mkdir(exist_ok=True)
        if league == "Ambient":
            (league_path / "notable-events").mkdir(exist_ok=True)
        else:
            (league_path / "snapshots").mkdir(exist_ok=True)
        if league == "NBA":
            (league_path / "topics" / "players").mkdir(parents=True, exist_ok=True)
            (league_path / "topics" / "storylines").mkdir(parents=True, exist_ok=True)
        elif league == "Formula-One":
            (league_path / "drivers").mkdir(exist_ok=True)
            (league_path / "standings").mkdir(exist_ok=True)
        written.append(write_and_return(league_path / "_index.md", league_index_md(league)))
        written.append(write_and_return(league_path / "agent-guide.md", league_agent_guide_md(league)))
        # Empty latest.md placeholder so retrieval doesn't 404 before first fetch.
        latest_path = league_path / "latest.md"
        if not latest_path.exists():
            written.append(
                write_and_return(
                    latest_path,
                    "\n".join(
                        [
                            "---",
                            f"type: sports_{league.lower().replace('-', '_')}_latest",
                            f"captured_at: {yaml_quote(utc_now_iso())}",
                            f"league: {league}",
                            "tags:",
                            "  - sports",
                            f"  - {league.lower()}",
                            "  - latest-feed",
                            "---",
                            "",
                            f"# {league} — Latest Snapshots",
                            "",
                            "_No snapshots yet._",
                            "",
                        ]
                    ),
                )
            )

    # Per-league extras
    pl_path = base / "Premier-League"
    fixtures = pl_path / "fixtures.md"
    if not fixtures.exists():
        written.append(write_and_return(fixtures, _placeholder_md("Premier-League", "fixtures", "rolling near-term fixtures")))
    standings = pl_path / "standings.md"
    if not standings.exists():
        written.append(write_and_return(standings, _placeholder_md("Premier-League", "standings", "current table snapshot")))

    ucl_final = base / "Champions-League" / "final-2026"
    ucl_final.mkdir(parents=True, exist_ok=True)
    return written


def _placeholder_md(league: str, kind: str, description: str) -> str:
    return "\n".join(
        [
            "---",
            f"type: sports_{league.lower().replace('-', '_')}_{kind}",
            f"captured_at: {yaml_quote(utc_now_iso())}",
            f"league: {league}",
            "tags:",
            "  - sports",
            f"  - {league.lower()}",
            f"  - {kind}",
            "---",
            "",
            f"# {league} — {kind}",
            "",
            f"_{description.capitalize()} will populate here after the first fetch._",
            "",
        ]
    )


def write_and_return(path: Path, text: str) -> Path:
    write_text(path, text)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--force", action="store_true", help="Overwrite existing .state JSON files")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    vault = vault_path(project_root)
    if not vault.exists():
        print(f"vault path missing: {vault}", file=sys.stderr)
        return 1

    written = seed_folder_tree(vault)
    curiosity = seed_curiosity(vault, args.force)
    snapshot = seed_snapshot_state(vault, args.force)

    print(f"vault: {vault}")
    print(f"wrote {len(written)} markdown files under Library/Sports/")
    print(f"curiosity state: {curiosity}")
    print(f"snapshot state: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
