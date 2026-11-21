"""One metadata-only audit record for each user-visible agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Iterable

from agent.telemetry.prices import compute_cost_usd

logger = logging.getLogger(__name__)
DEFAULT_AUDIT_LOG = Path("data/memory/audit_log.jsonl")
_WRITE_LOCK = threading.Lock()


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return round(ordered[index], 1)


def _read_turns(path: Path, since: datetime | None, until: datetime | None = None) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        return turns
    with handle:
        for line in handle:
            try:
                entry = json.loads(line)
                at = datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00"))
            except (ValueError, KeyError, TypeError):
                continue
            # Fixture models written by tests are not the user's usage.
            if str(entry.get("model") or "").startswith("test/"):
                continue
            if (since is None or at >= since) and (until is None or at < until):
                entry["_at"] = at
                turns.append(entry)
    return turns


def summarize_turns(path: Path = DEFAULT_AUDIT_LOG, *, days: int | None = 7,
                    now: datetime | None = None) -> dict[str, Any]:
    """Aggregate the metadata-only turn audit: latency, outcomes, models, tools, privacy."""
    now = now or datetime.now(timezone.utc)
    since = None if days is None else now - timedelta(days=days)
    turns = _read_turns(path, since)
    previous = _read_turns(path, since - timedelta(days=days), since) if since is not None else []

    def tally(key_fn) -> dict[str, int]:
        counts: dict[str, int] = {}
        for turn in turns:
            for key in key_fn(turn):
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: -item[1]))

    models: dict[str, dict[str, Any]] = {}
    for turn in turns:
        model = str(turn.get("model") or "unknown")
        row = models.setdefault(model, {"model": model, "provider": str(turn.get("provider") or ""), "turns": 0,
                                        "input": 0, "output": 0, "cost_usd": 0.0, "_ttft": []})
        row["turns"] += 1
        row["input"] += int(turn.get("prompt_tokens") or 0)
        row["output"] += int(turn.get("completion_tokens") or 0)
        row["cost_usd"] += float(turn.get("cost_usd") or 0)
        if turn.get("latency_first_token_ms"):
            row["_ttft"].append(float(turn["latency_first_token_ms"]))
    model_rows = []
    for row in sorted(models.values(), key=lambda item: -(item["input"] + item["output"])):
        ttft = row.pop("_ttft")
        model_rows.append({**row, "cost_usd": round(row["cost_usd"], 6), "p50_first_token_ms": _percentile(ttft, .5)})

    daily: dict[str, dict[str, Any]] = {}
    for turn in turns:
        day = turn["_at"].date().isoformat()
        bucket = daily.setdefault(day, {"day": day, "turns": 0, "failed": 0, "input": 0, "output": 0, "_total": []})
        bucket["turns"] += 1
        bucket["failed"] += 1 if turn.get("outcome") == "failed" else 0
        bucket["input"] += int(turn.get("prompt_tokens") or 0)
        bucket["output"] += int(turn.get("completion_tokens") or 0)
        if turn.get("latency_total_ms"):
            bucket["_total"].append(float(turn["latency_total_ms"]))
    daily_rows = [{**{k: v for k, v in bucket.items() if k != "_total"},
                   "p50_total_ms": _percentile(bucket["_total"], .5)} for _, bucket in sorted(daily.items())]

    ttft = [float(t["latency_first_token_ms"]) for t in turns if t.get("latency_first_token_ms")]
    total = [float(t["latency_total_ms"]) for t in turns if t.get("latency_total_ms")]
    outcomes = tally(lambda t: [str(t.get("outcome") or "unknown")])
    tokens = sum(int(t.get("total_tokens") or 0) for t in turns)
    previous_tokens = sum(int(t.get("total_tokens") or 0) for t in previous)
    return {
        "turns": len(turns),
        "previous_turns": len(previous),
        "tokens": tokens,
        "previous_tokens": previous_tokens,
        "cost_usd": round(sum(float(t.get("cost_usd") or 0) for t in turns), 6),
        "previous_cost_usd": round(sum(float(t.get("cost_usd") or 0) for t in previous), 6),
        "success_rate": outcomes.get("completed", 0) / max(len(turns), 1),
        "outcomes": outcomes,
        "latency": {
            "first_token_p50_ms": _percentile(ttft, .5), "first_token_p95_ms": _percentile(ttft, .95),
            "total_p50_ms": _percentile(total, .5), "total_p95_ms": _percentile(total, .95),
        },
        "providers": tally(lambda t: [str(t.get("provider") or "unknown")]),
        "privacy": tally(lambda t: [str(t.get("privacy_class") or "unknown")]),
        "tools": [{"name": name, "turns": count}
                  for name, count in list(tally(lambda t: list(dict.fromkeys(t.get("tools_called") or []))).items())[:12]],
        "turns_with_tools": sum(1 for t in turns if t.get("tools_called")),
        "models": model_rows,
        "daily": daily_rows,
    }


@dataclass
class TurnAudit:
    thread_id: str
    model: str
    provider: str
    privacy_class: str
    path: Path = DEFAULT_AUDIT_LOG
    retrieval_confidence: float | None = None
    followup_detected: bool = False
    saved: bool = False
    regenerated: bool = False
    _started: float = field(default_factory=time.monotonic, init=False, repr=False)
    _first_token: float | None = field(default=None, init=False, repr=False)
    _prompt_tokens: int = field(default=0, init=False, repr=False)
    _completion_tokens: int = field(default=0, init=False, repr=False)
    _cost_usd: float | None = field(default=None, init=False, repr=False)
    _finalized: bool = field(default=False, init=False, repr=False)

    def mark_first_token(self) -> None:
        if self._first_token is None:
            self._first_token = time.monotonic()

    def observe_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        self._prompt_tokens += int(
            usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        )
        self._completion_tokens += int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )
        if usage.get("cost") is not None:
            self._cost_usd = float(usage["cost"])
        elif usage.get("cost_usd") is not None:
            self._cost_usd = float(usage["cost_usd"])

    def finalize(
        self,
        outcome: str,
        *,
        tools_called: Iterable[str] = (),
    ) -> bool:
        if self._finalized:
            return False
        self._finalized = True
        ended = time.monotonic()
        prompt_tokens = self._prompt_tokens
        completion_tokens = self._completion_tokens
        cost_usd = self._cost_usd
        if cost_usd is None:
            cost_usd = compute_cost_usd(self.model, prompt_tokens, completion_tokens)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thread_id": self.thread_id,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost_usd": cost_usd,
            "latency_first_token_ms": (
                round((self._first_token - self._started) * 1000, 3)
                if self._first_token is not None
                else None
            ),
            "latency_total_ms": round((ended - self._started) * 1000, 3),
            "tools_called": list(dict.fromkeys(str(name) for name in tools_called if name)),
            "privacy_class": self.privacy_class,
            "outcome": outcome,
            "retrieval_confidence": self.retrieval_confidence,
            "followup_detected": self.followup_detected,
            "saved": self.saved,
            "regenerated": self.regenerated,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _WRITE_LOCK, self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        except Exception as exc:  # observability must not break the turn
            logger.warning("turn audit write failed: %s", exc)
            return False
        return True
