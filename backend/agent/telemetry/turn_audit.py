"""One metadata-only audit record for each user-visible agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
