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

    def serpapi_search(self, query, token):
        self.calls.append((query, token))
        return {
            "search_metadata": {"status": "Success"},
            "sports_results": {
                "title": query,
                "game_spotlight": {
                    "teams": [
                        {"name": "Arsenal", "score": "2"},
                        {"name": "PSG", "score": "1"},
                    ],
                    "status": "Final",
                },
            },
            "top_stories": [{"title": "Arsenal analysis", "source": "Example", "date": "Today"}],
        }


def test_default_run_writes_enabled_library_sports_snapshots(tmp_path):
    sports_importer = load_importer()
    result = sports_importer.run(
        project_root=tmp_path,
        leagues=None,
        dry_run=False,
        curiosity_reason="test run",
        client=FakeClient(),
        serpapi_token="serp-token",
    )

    sports = tmp_path / "Vault" / "Library" / "Sports"
    records = [
        json.loads(line)
        for line in (sports / "sports-snapshots.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    leagues = {record["league"] for record in records}

    assert result == 0
    assert leagues == {"NBA", "Formula-One", "Premier-League", "Champions-League", "Ambient"}
    assert "UFC" not in leagues
    assert "Boxing" not in leagues
    assert (sports / "NBA" / "latest.md").exists()
    assert any((sports / "Champions-League" / "snapshots" / "2026").glob("*.md"))


def test_dry_run_reports_paths_without_writing_or_network(tmp_path):
    sports_importer = load_importer()
    client = FakeClient()

    result = sports_importer.run(
        project_root=tmp_path,
        leagues=["NBA"],
        dry_run=True,
        curiosity_reason="dry run",
        client=client,
        serpapi_token="serp-token",
    )

    assert result == 0
    assert client.calls == []
    assert not (tmp_path / "Vault" / "Library" / "Sports").exists()


def test_disabled_league_is_rejected_even_when_requested(tmp_path):
    sports_importer = load_importer()
    result = sports_importer.run(
        project_root=tmp_path,
        leagues=["UFC"],
        dry_run=False,
        curiosity_reason="disabled league",
        client=FakeClient(),
        serpapi_token="serp-token",
    )

    sports = tmp_path / "Vault" / "Library" / "Sports"
    assert result == 0
    assert not (sports / "UFC").exists()
    records_path = sports / "sports-snapshots.jsonl"
    assert not records_path.exists()
