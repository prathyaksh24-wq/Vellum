import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_sports_snapshots.py"


def load_importer():
    assert SCRIPT_PATH.exists(), "scripts/import_sports_snapshots.py should exist"
    spec = importlib.util.spec_from_file_location("import_sports_snapshots", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self):
        self.calls = []

    def nba_scoreboard(self):
        self.calls.append(("nba-scoreboard",))
        return {"scoreboard": {"games": [{"gameId": "0022500001", "gameStatusText": "Q2", "homeTeam": {"teamName": "Warriors", "score": 62}, "awayTeam": {"teamName": "Lakers", "score": 58}}]}}

    def nba_boxscore(self, game_id):
        self.calls.append(("nba-boxscore", game_id))
        return {"game": {"gameId": game_id, "homeTeam": {"players": [{"name": "Stephen Curry", "points": 28}]}, "awayTeam": {"players": [{"name": "LeBron James", "points": 25}]}}}

    def openf1_drivers_latest(self):
        self.calls.append(("f1",))
        return [
            {"full_name": "Lewis Hamilton", "driver_number": 44, "team_name": "Ferrari"},
            {"full_name": "George Russell", "driver_number": 63, "team_name": "Mercedes"},
        ]

    def espn_scoreboard(self, sport_slug):
        self.calls.append(("espn-scoreboard", sport_slug))
        return {"events": [{"name": f"{sport_slug} fixture", "status": {"type": {"description": "Scheduled"}}}]}

    def fpl_bootstrap(self):
        self.calls.append(("fpl-bootstrap",))
        return {"events": [{"id": 38, "is_current": True}], "elements": [{"web_name": "Saka", "total_points": 210}]}

    def fpl_fixtures(self):
        self.calls.append(("fpl-fixtures",))
        return [{"id": 1, "team_h": 1, "team_a": 2, "started": False}]

    def fpl_event_live(self, event_id):
        self.calls.append(("fpl-live", event_id))
        return {"elements": [{"id": 1, "stats": {"goals_scored": 1}}]}

    def serpapi_search(self, query, token):
        self.calls.append(("serpapi", query, token))
        return {"search_metadata": {"status": "Success"}, "sports_results": {"game_spotlight": {"league": "Champions League"}}}


class PartiallyBrokenClient(FakeClient):
    def nba_scoreboard(self):
        self.calls.append(("nba-scoreboard",))
        raise RuntimeError("blocked")


def test_run_writes_free_live_snapshot_files(tmp_path):
    sports_importer = load_importer()
    client = FakeClient()

    result = sports_importer.run(
        project_root=tmp_path,
        dry_run=False,
        client=client,
        serpapi_token="",
    )

    sports = tmp_path / "Vault" / "Sports"
    state = json.loads((sports / ".state" / "sports_snapshot_state.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in (sports / "sports-snapshots.jsonl").read_text(encoding="utf-8").splitlines()]

    assert result == 0
    assert "Warriors" in (sports / "NBA" / "live-scoreboard.md").read_text(encoding="utf-8")
    assert "Stephen Curry" in (sports / "NBA" / "games" / "0022500001.md").read_text(encoding="utf-8")
    assert "Lewis Hamilton" in (sports / "Formula One" / "drivers" / "lewis-hamilton.md").read_text(encoding="utf-8")
    assert "eng.1 fixture" in (sports / "Football" / "Premier League" / "live-scoreboard.md").read_text(encoding="utf-8")
    assert "Saka" in (sports / "Football" / "Premier League" / "fantasy-player-stats.md").read_text(encoding="utf-8")
    assert "uefa.champions fixture" in (sports / "Football" / "Champions League" / "live-scoreboard.md").read_text(encoding="utf-8")
    assert state["written_count"] == len(records)
    assert state["skipped"] == [{"source": "serpapi", "reason": "SERPAPI_API_KEY missing"}]


def test_run_writes_serpapi_fallback_when_key_present(tmp_path):
    sports_importer = load_importer()
    client = FakeClient()

    result = sports_importer.run(
        project_root=tmp_path,
        dry_run=False,
        client=client,
        serpapi_token="serp-token",
    )

    sports = tmp_path / "Vault" / "Sports"
    records = [json.loads(line) for line in (sports / "sports-snapshots.jsonl").read_text(encoding="utf-8").splitlines()]

    assert result == 0
    assert (sports / "Football" / "Champions League" / "final-2026" / "serpapi-search.md").exists()
    assert any(record["source"] == "serpapi" for record in records)
    assert any(call[0] == "serpapi" and "Champions League final" in call[1] for call in client.calls)


def test_run_records_source_errors_without_aborting(tmp_path):
    sports_importer = load_importer()
    client = PartiallyBrokenClient()

    result = sports_importer.run(
        project_root=tmp_path,
        dry_run=False,
        client=client,
        serpapi_token="",
    )

    sports = tmp_path / "Vault" / "Sports"
    state = json.loads((sports / ".state" / "sports_snapshot_state.json").read_text(encoding="utf-8"))

    assert result == 0
    assert (sports / "Formula One" / "drivers" / "lewis-hamilton.md").exists()
    assert any(item["source"] == "nba-cdn" and "blocked" in item["reason"] for item in state["skipped"])


def test_dry_run_does_not_write_files(tmp_path):
    sports_importer = load_importer()

    result = sports_importer.run(
        project_root=tmp_path,
        dry_run=True,
        client=FakeClient(),
        serpapi_token="serp-token",
    )

    assert result == 0
    assert not (tmp_path / "Vault" / "Sports").exists()
