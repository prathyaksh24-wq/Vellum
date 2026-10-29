from __future__ import annotations

from pathlib import Path
import zipfile

from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_takeout import YouTubeTakeoutImporter, _event_timestamp


WATCH_HTML = """
<div class="outer-cell mdl-cell mdl-cell--12-col">
  <div><a href="https://www.youtube.com/watch?v=watch123456">Watched title</a><br>
  <a href="https://www.youtube.com/channel/UC-owner">Owner channel</a><br>
  22 Jul 2026, 10:04:24 IST</div>
</div>
"""

SEARCH_HTML = """
<div class="outer-cell mdl-cell mdl-cell--12-col">
  <div>Searched for <a href="https://www.youtube.com/results?search_query=local+agents+47">local agents 47</a><br>21 Jul 2026, 21:40:45 IST</div>
</div>
<div class="outer-cell mdl-cell mdl-cell--12-col">
  <div><a href="https://www.youtube.com/watch?v=watch-in-search">Watched from search file</a><br>21 Jul 2026, 20:00:00 IST</div>
</div>
<div class="outer-cell mdl-cell mdl-cell--12-col">
  <div>Visited YouTube home<br>21 Jul 2026, 19:00:00 IST</div>
</div>
"""


def _archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        root = "Takeout/YouTube and YouTube Music"
        archive.writestr(f"{root}/history/watch-history.html", WATCH_HTML)
        archive.writestr(f"{root}/history/search-history.html", SEARCH_HTML)
        archive.writestr(f"{root}/videos/large-video.mp4", b"not-real-media")


def test_takeout_import_is_private_idempotent_and_does_not_extract_media(tmp_path: Path) -> None:
    archive_path = tmp_path / "takeout.zip"
    _archive(archive_path)
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")
    importer = YouTubeTakeoutImporter(store=store, account_id="UC-primary")

    first = importer.run(archive_path, idempotency_key="archive-1")
    replay = importer.run(archive_path, idempotency_key="archive-1")

    assert first["status"] == "completed"
    assert first["stats"]["watch_events"] == 2
    assert first["stats"]["search_events"] == 1
    assert first["stats"]["other_events"] == 1
    assert first["stats"]["media_files_inventoried"] == 1
    assert replay["should_run"] is False
    assert store.status()["counts"]["observations"] == 4
    recent = importer.history(kind="watch", limit=10)
    assert recent["total"] == 2
    assert {item["video_id"] for item in recent["items"]} == {"watch123456", "watch-in-search"}
    assert not (tmp_path / "large-video.mp4").exists()


def test_takeout_timestamp_accepts_google_sept_abbreviation() -> None:
    parsed = _event_timestamp("YouTube Searched for test 30 Sept 2025, 11:18:48 IST Products: YouTube")

    assert parsed is not None
    assert parsed.isoformat() == "2025-09-30T05:48:48+00:00"


def test_takeout_imports_subscriptions_music_and_watch_later_locally(tmp_path: Path) -> None:
    archive_path = tmp_path / "takeout.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        root = "Takeout/YouTube and YouTube Music"
        archive.writestr(f"{root}/subscriptions/subscriptions.csv", "Channel ID,Channel URL,Channel title\nUC-owner,https://www.youtube.com/channel/UC-owner,Owner\n")
        archive.writestr(f"{root}/music (library and uploads)/music library songs.csv", "Video ID,Song Title,Album Title,Artist Name 1\nsong123,A song,Album,Artist\n")
        archive.writestr(f"{root}/playlists/Watch later videos.csv", "Video ID,Playlist video creation timestamp\nwatch123,2026-10-01T00:00:00Z\n")
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")
    importer = YouTubeTakeoutImporter(store=store, account_id="primary")
    result = importer.run(archive_path, idempotency_key="metadata")
    assert result["stats"]["library_rows"] == 3
    assert importer.library(kind="subscriptions")["items"][0]["title"] == "Owner"
    assert importer.library(kind="music")["items"][0]["artists"] == ["Artist"]
    assert importer.library(kind="watch_later")["items"][0]["video_id"] == "watch123"
    assert YouTubeTakeoutImporter(store=store, account_id="other").library(kind="music")["total"] == 0
    replay = importer.run(archive_path, idempotency_key="metadata-second")
    assert importer.library(kind="music")["total"] == 1
    assert replay["status"] == "completed"
