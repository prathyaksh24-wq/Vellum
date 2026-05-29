from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from agent.tools import sports_curiosity


class SportsCuriosityAdapter(Protocol):
    def should_fetch(self, league: str) -> dict:
        ...

    def fetch(self, league: str, curiosity_reason: str) -> dict:
        ...


class LangChainSportsCuriosity:
    def should_fetch(self, league: str) -> dict:
        return sports_curiosity.should_fetch_sports.invoke({"league": league})

    def fetch(self, league: str, curiosity_reason: str) -> dict:
        return sports_curiosity.fetch_sports_if_curious.invoke({"league": league, "curiosity_reason": curiosity_reason})


class SportsDaemonLoop:
    def __init__(
        self,
        vault_root: Path,
        curiosity: SportsCuriosityAdapter | None = None,
        enabled_leagues: tuple[str, ...] = ("NBA", "Formula-One", "Premier-League", "Champions-League", "Ambient"),
        dry_run: bool = False,
    ):
        self.vault_root = Path(vault_root)
        self.curiosity = curiosity or LangChainSportsCuriosity()
        self.enabled_leagues = enabled_leagues
        self.dry_run = dry_run

    def tick(self) -> dict:
        checked: list[str] = []
        fetched: list[str] = []
        decisions: list[dict] = []
        reason = "daemon sports_loop curiosity tick"

        for league in self.enabled_leagues:
            decision = self.curiosity.should_fetch(league)
            checked.append(league)
            decisions.append(decision)
            if decision.get("would_fetch") and not self.dry_run:
                result = self.curiosity.fetch(league, reason)
                if result.get("fetched"):
                    fetched.append(league)

        payload = {
            "loop": "sports",
            "checked": checked,
            "fetched": fetched,
            "decisions": decisions,
            "dry_run": self.dry_run,
            "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        self._write_tick_log(payload)
        return payload

    def _write_tick_log(self, payload: dict) -> None:
        path = self.vault_root / "Agent" / "Memories" / "Daemon" / "sports-loop-last.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
