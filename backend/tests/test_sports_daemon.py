import json
from pathlib import Path

from agent.daemon.loops.sports import SportsDaemonLoop


class FakeCuriosity:
    def __init__(self):
        self.checked = []
        self.fetched = []

    def should_fetch(self, league):
        self.checked.append(league)
        return {"league": league, "would_fetch": league == "NBA", "score": 0.9, "threshold": 0.65, "reason": "above_threshold"}

    def fetch(self, league, curiosity_reason):
        self.fetched.append((league, curiosity_reason))
        return {"fetched": True, "result": {"league": league, "path": "Library/Sports/NBA/snapshots/2026/test.md"}}


def test_sports_daemon_tick_fetches_only_enabled_league(tmp_path):
    curiosity = FakeCuriosity()
    loop = SportsDaemonLoop(
        vault_root=tmp_path,
        curiosity=curiosity,
        enabled_leagues=("NBA", "Formula-One"),
        dry_run=False,
    )

    result = loop.tick()

    assert result["checked"] == ["NBA", "Formula-One"]
    assert result["fetched"] == ["NBA"]
    assert curiosity.fetched == [("NBA", "daemon sports_loop curiosity tick")]


def test_sports_daemon_dry_run_does_not_fetch(tmp_path):
    curiosity = FakeCuriosity()
    loop = SportsDaemonLoop(vault_root=tmp_path, curiosity=curiosity, enabled_leagues=("NBA",), dry_run=True)

    result = loop.tick()

    assert result["checked"] == ["NBA"]
    assert result["fetched"] == []
    assert curiosity.fetched == []


def test_sports_daemon_writes_tick_log(tmp_path):
    curiosity = FakeCuriosity()
    loop = SportsDaemonLoop(vault_root=tmp_path, curiosity=curiosity, enabled_leagues=("NBA",), dry_run=True)

    loop.tick()

    log_path = tmp_path / "Agent" / "Memories" / "Daemon" / "sports-loop-last.json"
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["loop"] == "sports"
    assert payload["dry_run"] is True
