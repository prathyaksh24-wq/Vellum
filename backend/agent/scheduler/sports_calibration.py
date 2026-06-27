"""Self-calibration for the sports curiosity model.

Reads `Agent/Memories/sports_*_fetch_*.md` from the last 14 days and gently
adjusts per-league thresholds in `Library/Sports/.state/curiosity.json`:

- 5+ consecutive unused fetches → raise threshold by 0.05 (cap 0.90)
- User asked a sports question recently but no recent fetch existed → lower threshold by 0.05 (floor 0.40)

This module is invoked from the nightly digest in `agent/scheduler/digest.py`;
it has no scheduler entry of its own. Failures are logged and swallowed so
they never break the digest run.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.config import get_settings

logger = logging.getLogger(__name__)


LEAGUES = (
    "NBA",
    "Formula-One",
    "Premier-League",
    "Champions-League",
    "Boxing",
    "UFC",
    "Ambient",
)
THRESHOLD_FLOOR = 0.40
THRESHOLD_CEILING = 0.90
THRESHOLD_STEP = 0.05
UNUSED_FETCH_LIMIT = 5
LOOKBACK_DAYS = 14


def _vault_root() -> Path:
    return Path(get_settings().obsidian_vault_path).expanduser()


def _sports_state_path() -> Path:
    return _vault_root() / "Library" / "Sports" / ".state" / "curiosity.json"


def _memories_dir() -> Path:
    return _vault_root() / "Agent" / "Memories"


def _queries_dir() -> Path:
    return _vault_root() / "Agent" / "Queries"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("[SPORTS-CAL] malformed JSON at %s", path)
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _parse_memory(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    league_match = re.search(r"^league:\s*(.+)$", text, re.MULTILINE)
    outcome_match = re.search(r"Outcome:\s*(fetched|skipped)", text)
    used_match = re.search(r"## Used in response\s*\n\s*(.+)", text)
    if not league_match:
        return None
    league = league_match.group(1).strip()
    return {
        "league": league,
        "outcome": outcome_match.group(1) if outcome_match else "unknown",
        "used": bool(used_match and "yes" in used_match.group(1).lower()),
        "path": path,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
    }


def _gather_memories(since: datetime) -> dict[str, list[dict[str, Any]]]:
    by_league: dict[str, list[dict[str, Any]]] = defaultdict(list)
    memories = _memories_dir()
    if not memories.exists():
        return by_league
    for path in memories.glob("sports_*_fetch_*.md"):
        if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < since:
            continue
        parsed = _parse_memory(path)
        if parsed is None:
            continue
        by_league[parsed["league"]].append(parsed)
    for league_list in by_league.values():
        league_list.sort(key=lambda item: item["mtime"], reverse=True)
    return by_league


def _recent_query_mentions_league(keywords: list[str], since: datetime) -> bool:
    queries_dir = _queries_dir()
    if not queries_dir.exists() or not keywords:
        return False
    needles = [kw.lower() for kw in keywords]
    for path in queries_dir.glob("*.md"):
        if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < since:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(needle in text for needle in needles):
            return True
    return False


def _adjust_threshold(current: float, delta: float) -> float:
    return max(THRESHOLD_FLOOR, min(THRESHOLD_CEILING, round(current + delta, 4)))


def calibrate(now: datetime | None = None) -> dict[str, Any]:
    """Run a calibration pass. Returns the adjustments made."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=LOOKBACK_DAYS)
    state_path = _sports_state_path()
    state = _read_json(state_path)
    if not state.get("leagues"):
        logger.info("[SPORTS-CAL] curiosity.json missing or empty — nothing to calibrate")
        return {"adjusted": [], "reason": "no_state"}

    memories_by_league = _gather_memories(since)
    adjustments: list[dict[str, Any]] = []

    for league in LEAGUES:
        config = state["leagues"].get(league)
        if not config:
            continue
        threshold = float(config.get("threshold", 0.65))
        keywords = config.get("keywords", [])
        memories = memories_by_league.get(league, [])

        delta = 0.0
        reasons: list[str] = []

        recent_fetches = [m for m in memories if m["outcome"] == "fetched"]
        if len(recent_fetches) >= UNUSED_FETCH_LIMIT and all(not m["used"] for m in recent_fetches[:UNUSED_FETCH_LIMIT]):
            delta += THRESHOLD_STEP
            reasons.append(f"{UNUSED_FETCH_LIMIT}+ consecutive unused fetches → raise")

        user_asked = _recent_query_mentions_league(keywords, since)
        any_recent_fetch = bool(recent_fetches)
        if user_asked and not any_recent_fetch:
            delta -= THRESHOLD_STEP
            reasons.append("user asked about league but no recent fetch → lower")

        if delta == 0.0:
            continue
        new_threshold = _adjust_threshold(threshold, delta)
        if new_threshold == threshold:
            continue
        config["threshold"] = new_threshold
        adjustments.append(
            {
                "league": league,
                "from": threshold,
                "to": new_threshold,
                "delta": round(delta, 4),
                "reasons": reasons,
            }
        )

    if adjustments:
        state["updated"] = now.replace(microsecond=0).isoformat()
        _write_json(state_path, state)
        _log_to_reflection(adjustments, now)
        logger.info("[SPORTS-CAL] adjusted thresholds: %s", adjustments)
    else:
        logger.info("[SPORTS-CAL] no threshold adjustments needed")
    return {"adjusted": adjustments, "lookback_days": LOOKBACK_DAYS}


def _log_to_reflection(adjustments: list[dict[str, Any]], now: datetime) -> None:
    folder = _vault_root() / "Agent" / "Reflections" / "Weekly"
    folder.mkdir(parents=True, exist_ok=True)
    iso_week = now.strftime("%G-W%V")
    path = folder / f"{iso_week}-sports-calibration.md"
    lines = [
        "---",
        "type: agent-reflection",
        f"created: {now.date().isoformat()}",
        "agent_version: vellum-1.0",
        "private: true",
        "subject: sports-curiosity-calibration",
        "tags:",
        "  - sports",
        "  - calibration",
        "  - reflection",
        "---",
        "",
        f"# Sports curiosity calibration — {iso_week}",
        "",
        f"Lookback: last {LOOKBACK_DAYS} days. Adjustments applied:",
        "",
        "| league | from | to | delta | reasons |",
        "|---|---|---|---|---|",
    ]
    for adj in adjustments:
        reasons = "; ".join(adj["reasons"])
        lines.append(f"| {adj['league']} | {adj['from']} | {adj['to']} | {adj['delta']} | {reasons} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def run_safely(now: datetime | None = None) -> dict[str, Any]:
    """Wrapper that swallows exceptions — safe to call from the nightly digest."""
    try:
        return calibrate(now=now)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[SPORTS-CAL] calibration failed: %s", exc)
        return {"adjusted": [], "error": str(exc)}
