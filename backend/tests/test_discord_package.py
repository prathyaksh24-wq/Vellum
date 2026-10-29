from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from agent.knowledge.store import KnowledgeStore
from agent.plugins.discord_package import DiscordPackageError, DiscordPackageImporter


def _package(path: Path, *, unsafe: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Messages/index.json", json.dumps({"10001": "general"}))
        archive.writestr(
            "Messages/c10001/channel.json",
            json.dumps({
                "id": "10001",
                "type": "GUILD_TEXT",
                "name": "general",
                "guild": {"id": "20001", "name": "Example Guild"},
            }),
        )
        archive.writestr(
            "Messages/c10001/messages.json",
            json.dumps([
                {
                    "ID": "30001",
                    "Timestamp": "2025-08-01T00:58:56+00:00",
                    "Contents": "Project alpha status",
                    "Attachments": "",
                },
                {
                    "ID": "30002",
                    "Timestamp": "2024-03-02T10:30:00+00:00",
                    "Contents": "Older note",
                    "Attachments": "https://cdn.discordapp.com/files/report.txt?secret=discarded",
                },
            ]),
        )
        archive.writestr(
            "Account/user.json",
            json.dumps({"id": "raw-account-id", "email": "private@example.com"}),
        )
        archive.writestr("Account/user_data_exports/discord_billing/payments.json", "billing-secret")
        archive.writestr("Activity/analytics/events.json", "telemetry-secret")
        if unsafe:
            archive.writestr("../outside.json", "unsafe")


def test_discord_package_import_is_private_idempotent_and_queryable(tmp_path: Path) -> None:
    archive_path = tmp_path / "package.zip"
    _package(archive_path)
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")
    importer = DiscordPackageImporter(store=store, account_id="user-1")

    first = importer.run(archive_path)
    replay = importer.run(archive_path)

    assert first["status"] == "completed"
    assert first["stats"]["messages"] == 2
    assert first["stats"]["channels"] == 1
    assert first["stats"]["excluded_entries"] == 2
    assert replay["should_run"] is False
    assert importer.status() == {
        "available": True,
        "messages": 2,
        "latest": "2025-08-01T00:58:56+00:00",
        "local_only": True,
    }

    history = importer.history(query="project alpha", limit=10)
    assert history["total"] == 2
    assert [item["id"] for item in history["items"]] == ["30001"]
    assert history["items"][0]["content"] == "Project alpha status"

    sources = store.list_sources(kind="discord_message", limit=10)
    assert {source["external_id"] for source in sources} == {
        "discord:message:10001:30001",
        "discord:message:10001:30002",
    }
    assert all(source["sensitivity"] == "private_local_only" for source in sources)
    assert all(source["external_policy"] == "deny_raw" for source in sources)
    attachment_source = next(source for source in sources if source["external_id"].endswith(":30002"))
    attachment = store.get_source(attachment_source["id"], include_content=True)
    assert attachment is not None
    assert "secret=discarded" not in attachment["content"]
    assert "private@example.com" not in attachment["content"]
    assert "billing-secret" not in attachment["content"]
    assert "telemetry-secret" not in attachment["content"]

    observations = store.list_observation_details(origin="discord_data_package", limit=10)
    assert len(observations) == 2
    assert all(item["actor"] == "user" for item in observations)
    assert all("content" not in item["payload"] for item in observations)


def test_discord_package_rejects_unsafe_archive_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    _package(archive_path, unsafe=True)
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")

    with pytest.raises(DiscordPackageError, match="DISCORD_PACKAGE_UNSAFE_PATH"):
        DiscordPackageImporter(store=store).run(archive_path)

    jobs = store.list_ingestion_jobs(limit=10)
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["error_code"] == "DISCORDPACKAGEERROR"
