import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "apply_retention.py"


def load_retention():
    assert SCRIPT_PATH.exists(), "scripts/apply_retention.py should exist"
    spec = importlib.util.spec_from_file_location("apply_retention", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeIngester:
    def __init__(self):
        self.deleted = []
        self.ingested = []

    def delete_file_records(self, path):
        self.deleted.append(str(path).replace("\\", "/"))

    def ingest_file(self, path):
        self.ingested.append(str(path).replace("\\", "/"))
        return 1


def write_note(path: Path, captured_at: str, body: str = "Truth, curiosity, kindness.") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
type: youtube_transcript
captured_at: "{captured_at}"
---

# Source Note

{body}
""",
        encoding="utf-8",
        newline="\n",
    )


def test_moves_hot_raw_notes_to_archive_after_30_days(tmp_path):
    retention = load_retention()
    vault = tmp_path / "Vault"
    source = vault / "Youtube" / "channels" / "moresidemen" / "videos" / "2026" / "video.md"
    write_note(source, "2026-04-01T00:00:00+00:00")
    ingester = FakeIngester()

    result = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        archive_after_days=30,
        delete_after_days=90,
        dry_run=False,
        ingester=ingester,
    )

    archived = vault / "Archive" / "Youtube" / "channels" / "moresidemen" / "videos" / "2026" / "video.md"
    memory = vault / "Agent" / "Memories" / "Youtube" / "moresidemen" / "2026-04-memory.md"
    assert result["archived"] == 1
    assert result["distilled"] == 1
    assert not source.exists()
    assert archived.exists()
    assert memory.exists()
    assert "Archived from: Youtube/channels/moresidemen/videos/2026/video.md" in archived.read_text(encoding="utf-8")
    assert "Archive/Youtube/channels/moresidemen/videos/2026/video.md" in memory.read_text(encoding="utf-8")
    assert "Youtube/channels/moresidemen/videos/2026/video.md" in ingester.deleted
    assert any("Archive/Youtube/channels/moresidemen/videos/2026/video.md" in item for item in ingester.ingested)
    assert any("Agent/Memories/Youtube/moresidemen/2026-04-memory.md" in item for item in ingester.ingested)


def test_distills_then_deletes_archived_notes_after_90_days(tmp_path):
    retention = load_retention()
    vault = tmp_path / "Vault"
    source = vault / "Archive" / "X" / "naval" / "tweets" / "2026" / "old.md"
    write_note(
        source,
        "2026-01-01T00:00:00+00:00",
        body="Naval says to sell the truth, direct attention, and seek peace through clarity.",
    )
    ingester = FakeIngester()

    result = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        archive_after_days=30,
        delete_after_days=90,
        dry_run=False,
        ingester=ingester,
    )

    memory = vault / "Agent" / "Memories" / "X" / "naval" / "2026-01-memory.md"
    assert result["distilled"] == 1
    assert result["deleted"] == 1
    assert not source.exists()
    text = memory.read_text(encoding="utf-8")
    assert "Naval" in text
    assert "truth" in text.casefold()
    assert "Archived Sources Distilled" in text
    assert "Archive/X/naval/tweets/2026/old.md" in ingester.deleted
    assert any("Agent/Memories/X/naval/2026-01-memory.md" in item for item in ingester.ingested)


def test_dry_run_does_not_move_or_delete(tmp_path):
    retention = load_retention()
    vault = tmp_path / "Vault"
    source = vault / "Sports" / "NBA" / "live-scoreboard.md"
    write_note(source, "2026-01-01T00:00:00+00:00")

    result = retention.run(
        vault_root=vault,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
        archive_after_days=30,
        delete_after_days=90,
        dry_run=True,
        ingester=FakeIngester(),
    )

    assert result["would_archive"] == 1
    assert source.exists()
    assert not (vault / "Archive").exists()
