"""Sports curiosity tool — opportunistic, no-schedule fetching.

The agent calls `should_fetch_sports(league)` to score how strongly it 'feels'
like fetching, and `fetch_sports_if_curious(league)` to actually trigger the
SerpAPI snapshot via scripts/import_sports_snapshots.py when the score crosses
the league's threshold.

There is no scheduler entry for sports. Eligibility is checked only when the
agent is already running for another reason — handling a user turn, processing
nightly digest, etc. This is the user's "fetch when it feels like it" model.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

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


# --------------------------------------------------------------------------- #
# Lazy import of scripts/import_sports_snapshots.py
# --------------------------------------------------------------------------- #


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _import_snapshots_module():
    """Load scripts/import_sports_snapshots.py without polluting sys.path globally."""
    module_name = "import_sports_snapshots"
    if module_name in sys.modules:
        return sys.modules[module_name]
    script_path = _project_root() / "scripts" / "import_sports_snapshots.py"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# State + utilities
# --------------------------------------------------------------------------- #


def _vault_root() -> Path:
    settings = get_settings()
    return Path(settings.obsidian_vault_path).expanduser()


def _sports_root() -> Path:
    return _vault_root() / "Library" / "Sports"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("[SPORTS] malformed JSON at %s", path)
        return {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Component scoring
# --------------------------------------------------------------------------- #


def _recency_hunger(last_fetched: str | None, max_hours: float) -> float:
    if not last_fetched:
        return 1.0
    parsed = _parse_iso(last_fetched)
    if parsed is None:
        return 1.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = (_utc_now() - parsed).total_seconds() / 3600.0
    if delta <= 0:
        return 0.0
    return min(delta / max(max_hours, 1.0), 1.0)


def _scan_text_for_keywords(text: str, keywords: list[str]) -> int:
    if not text or not keywords:
        return 0
    haystack = text.lower()
    hits = 0
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw.lower())}\b", haystack):
            hits += 1
    return hits


def _user_signal(keywords: list[str]) -> float:
    """Scan the 30 most recent Agent/Queries/ files for keyword hits."""
    queries_dir = _vault_root() / "Agent" / "Queries"
    if not queries_dir.exists():
        return 0.0
    try:
        files = sorted(queries_dir.glob("*.md"), reverse=True)[:30]
    except OSError:
        return 0.0
    hits = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits += min(_scan_text_for_keywords(text, keywords), 3)
    return min(hits / 6.0, 1.0)


def _cross_feed_signal(keywords: list[str]) -> float:
    """Scan latest-N feeds in X and YouTube libraries for keyword hits."""
    library = _vault_root() / "Library"
    targets: list[Path] = []
    for pattern in ("X/*/latest-*.md", "Youtube/channels/*/latest-*.md"):
        targets.extend(library.glob(pattern))
    if not targets:
        return 0.0
    hits = 0
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits += min(_scan_text_for_keywords(text, keywords), 4)
    return min(hits / 8.0, 1.0)


def _stochastic_kick(low: float = 0.0, high: float = 0.15) -> float:
    return random.uniform(low, high)


def _season_signal(season_state: str) -> float:
    return {
        "finals": 1.0,
        "playoffs": 0.9,
        "in_season": 0.7,
        "offseason": 0.2,
    }.get(season_state, 0.5)


# --------------------------------------------------------------------------- #
# Budget guard
# --------------------------------------------------------------------------- #


def _budget_remaining() -> dict[str, int]:
    state = _read_json(_sports_root() / ".state" / "snapshot_state.json")
    budget = state.get("serpapi_budget") or {"daily_cap": 40, "monthly_cap": 800}
    counters = state.get("serpapi_counters") or {}
    today = _utc_now().date().isoformat()
    month = today[:7]
    day_used = counters.get("day_used", 0) if counters.get("day") == today else 0
    month_used = counters.get("month_used", 0) if counters.get("month") == month else 0
    return {
        "daily_remaining": max(budget["daily_cap"] - day_used, 0),
        "monthly_remaining": max(budget["monthly_cap"] - month_used, 0),
    }


# --------------------------------------------------------------------------- #
# Score assembly
# --------------------------------------------------------------------------- #


def _compute_score(league: str, curiosity: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    leagues = curiosity.get("leagues", {})
    config = leagues.get(league, {})
    weights = config.get("weights", {})
    threshold = float(config.get("threshold", 0.65))
    season_state = config.get("season_state", "in_season")
    keywords = config.get("keywords", [])
    max_hours = float(config.get("recency_hunger_max_hours", 168))

    last_fetched = (snapshot.get("last_fetched") or {}).get(league)

    components_raw = {
        "recency_hunger": _recency_hunger(last_fetched, max_hours),
        "user_signal": _user_signal(keywords),
        "season_weight": _season_signal(season_state),
        "cross_feed_signal": _cross_feed_signal(keywords),
        "stochastic_kick": _stochastic_kick(),
    }
    weighted = {key: components_raw[key] * float(weights.get(key, 0.0)) for key in components_raw}
    total = sum(weighted.values()) / max(sum(float(w) for w in weights.values()) or 1.0, 1.0)

    return {
        "league": league,
        "season_state": season_state,
        "score": round(total, 4),
        "threshold": threshold,
        "components_raw": {k: round(v, 4) for k, v in components_raw.items()},
        "components_weighted": {k: round(v, 4) for k, v in weighted.items()},
        "weights": weights,
        "last_fetched": last_fetched,
    }


# --------------------------------------------------------------------------- #
# Memory writer
# --------------------------------------------------------------------------- #


def _write_fetch_memory(score_info: dict[str, Any], fetch_result: dict[str, Any], skipped_reason: str | None) -> Path:
    memories = _vault_root() / "Agent" / "Memories"
    memories.mkdir(parents=True, exist_ok=True)
    ts = _utc_now().strftime("%Y%m%d_%H%M%S")
    league = score_info["league"]
    path = memories / f"sports_{league.lower().replace('-', '_')}_fetch_{ts}.md"
    summary = "(skipped: " + skipped_reason + ")" if skipped_reason else _summarize_fetch(fetch_result)
    lines = [
        "---",
        "type: agent-memory",
        f"created: {_utc_now().date().isoformat()}",
        "agent_version: vellum-1.0",
        "private: true",
        "subject: sports-curiosity-fetch",
        f"league: {league}",
        "tags:",
        "  - sports",
        f"  - {league.lower()}",
        "  - curiosity-fetch",
        "---",
        "",
        f"# Sports curiosity decision — {league} @ {_utc_now().isoformat()}",
        "",
        f"- Score: **{score_info['score']}** (threshold {score_info['threshold']})",
        f"- Season state: {score_info['season_state']}",
        f"- Last fetched: {score_info.get('last_fetched') or 'never'}",
        f"- Outcome: {'fetched' if not skipped_reason else 'skipped'}",
        "",
        "## Component breakdown",
        "",
        "| component | raw | weighted |",
        "|---|---|---|",
    ]
    for key, raw in score_info["components_raw"].items():
        weighted = score_info["components_weighted"].get(key, 0.0)
        lines.append(f"| {key} | {raw} | {weighted} |")
    lines += [
        "",
        "## Summary of fetched data",
        "",
        summary,
        "",
        "## Used in response",
        "",
        "_To be updated by the calibration pass if a later user query draws on this fetch._",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def _summarize_fetch(fetch_result: dict[str, Any]) -> str:
    if not fetch_result or fetch_result.get("skipped"):
        return f"_No data — {fetch_result.get('reason', 'unknown')}_"
    extracted = fetch_result.get("extracted") or []
    path = fetch_result.get("path") or fetch_result.get("would_write") or "(unwritten)"
    queries = fetch_result.get("queries") or []
    bullets = [
        f"- Path: `{path}`",
        f"- Extracted blocks: {', '.join(extracted) if extracted else '(none)'}",
        f"- Queries: {len(queries)}",
    ]
    return "\n".join(bullets)


# --------------------------------------------------------------------------- #
# Public tool surface
# --------------------------------------------------------------------------- #


def _gate(league: str) -> dict[str, Any]:
    if league not in LEAGUES:
        return {"error": f"unknown league {league!r}; choose from {list(LEAGUES)}"}
    curiosity = _read_json(_sports_root() / ".state" / "curiosity.json")
    snapshot = _read_json(_sports_root() / ".state" / "snapshot_state.json")
    score = _compute_score(league, curiosity, snapshot)
    remaining = _budget_remaining()
    score["budget_remaining"] = remaining
    over_threshold = score["score"] >= score["threshold"]
    budget_ok = remaining["daily_remaining"] > 0 and remaining["monthly_remaining"] > 0
    score["would_fetch"] = over_threshold and budget_ok
    if not budget_ok:
        score["reason"] = "budget_exhausted"
    elif not over_threshold:
        score["reason"] = "below_threshold"
    else:
        score["reason"] = "above_threshold"
    return score


@tool
def should_fetch_sports(league: str) -> dict[str, Any]:
    """Compute the curiosity score for a sports league without fetching.

    Returns a dict with the component breakdown, the threshold, the SerpAPI
    budget remaining, and `would_fetch` (bool). Pure compute — no side effects,
    no network. Use this when the user asks whether you should check on a sport,
    or before calling `fetch_sports_if_curious` to inspect the decision.

    Args:
        league: One of NBA, Formula-One, Premier-League, Champions-League,
                Boxing, UFC, Ambient.
    """
    return _gate(league)


@tool
def fetch_sports_if_curious(league: str = "", curiosity_reason: str = "") -> dict[str, Any]:
    """Maybe fetch a SerpAPI snapshot for a sports league, gated by curiosity.

    If `league` is empty, evaluate every league and fetch the highest-scoring
    one above its threshold (at most one fetch per call). Otherwise evaluate
    just that league.

    Always writes an Agent/Memories/ note recording the decision (fetched or
    skipped) and the score breakdown. This is the self-calibration data source.

    Args:
        league: League name, or empty to auto-pick.
        curiosity_reason: One-line explanation of why this fetch is happening
                          (e.g. "user asked about Lakers"). Stored in the
                          snapshot's frontmatter for later calibration.
    """
    if league:
        candidates = [_gate(league)]
    else:
        candidates = [_gate(name) for name in LEAGUES]
        candidates = [c for c in candidates if "error" not in c]

    eligible = sorted(
        (c for c in candidates if c.get("would_fetch")),
        key=lambda c: c["score"],
        reverse=True,
    )
    if not eligible:
        best = max(candidates, key=lambda c: c.get("score", 0.0)) if candidates else {"error": "no candidates"}
        memory_path = None
        if "error" not in best:
            memory_path = str(_write_fetch_memory(best, {}, best.get("reason", "below_threshold")))
        return {"fetched": False, "decision": best, "memory_path": memory_path}

    chosen = eligible[0]
    try:
        module = _import_snapshots_module()
    except Exception as exc:  # noqa: BLE001
        return {"fetched": False, "decision": chosen, "error": f"snapshot module unavailable: {exc}"}

    project_root = _project_root()
    client = module.SportsApiClient()
    token = module.env_token(project_root, "SERPAPI_API_KEY")
    reason = curiosity_reason.strip() or _auto_reason(chosen)
    fetcher = module.FETCHERS.get(chosen["league"])
    if fetcher is None:
        return {"fetched": False, "decision": chosen, "error": f"no fetcher for {chosen['league']}"}

    fetch_result = fetcher(
        vault=Path(get_settings().obsidian_vault_path).expanduser(),
        project_root=project_root,
        client=client,
        serpapi_token=token,
        curiosity_reason=reason,
    )
    memory_path = str(_write_fetch_memory(chosen, fetch_result, fetch_result.get("reason") if fetch_result.get("skipped") else None))
    return {
        "fetched": not fetch_result.get("skipped"),
        "decision": chosen,
        "result": fetch_result,
        "memory_path": memory_path,
    }


def _auto_reason(decision: dict[str, Any]) -> str:
    components = decision.get("components_raw", {})
    drivers = sorted(components.items(), key=lambda kv: kv[1], reverse=True)[:2]
    parts = [f"{name}={value}" for name, value in drivers]
    return f"opportunistic fetch (top drivers: {', '.join(parts)})"
