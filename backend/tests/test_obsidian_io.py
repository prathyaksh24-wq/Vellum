from pathlib import Path

import pytest

from agent.obsidian.ingester import VaultIngester, chunk_text
from agent.obsidian.vault import ObsidianVault
from agent.privacy.metadata_strip import safe_chunk_id, strip_obsidian_metadata


class FakeEmbedder:
    def embed(self, text: str):
        return [float(len(text))]


class FakeStore:
    def __init__(self):
        self.upserts = []
        self.deletes = []

    def upsert(self, collection: str, text: str, embedding: list[float], metadata: dict, point_id: str | None = None):
        self.upserts.append(
            {
                "collection": collection,
                "text": text,
                "embedding": embedding,
                "metadata": metadata,
                "point_id": point_id,
            }
        )

    def delete_by_metadata(self, collection: str, key: str, value):
        self.deletes.append((collection, key, value))


def test_vault_create_read_append_and_search(tmp_path):
    vault = ObsidianVault(tmp_path)
    note = vault.create_note("Sports/NBA", "Latest: Notes?", "NBA standings and playoffs")

    assert note.exists()
    assert "NBA standings" in vault.read_note("Sports/NBA/Latest- Notes.md")

    vault.append_to_note("Sports/NBA/Latest- Notes.md", "More playoff notes")
    assert "More playoff notes" in vault.read_note("Sports/NBA/Latest- Notes.md")

    results = vault.search("playoff", folder="Sports")
    assert results[0]["path"] == "Sports/NBA/Latest- Notes.md"
    assert results[0]["folder"] == "Sports/NBA"


def test_vault_rejects_path_escape(tmp_path):
    vault = ObsidianVault(tmp_path)

    with pytest.raises(ValueError, match="escapes"):
        vault.read_note("../outside.md")


def test_metadata_strip_and_chunk_id_are_stable():
    text = "---\ntype: note\n---\n\nHello #tag world"

    assert strip_obsidian_metadata(text) == "Hello  world"
    assert safe_chunk_id("A.md", 1) == safe_chunk_id("A.md", 1)
    assert safe_chunk_id("A.md", 1) != safe_chunk_id("A.md", 2)


def test_chunk_text_uses_overlap():
    chunks = chunk_text("one two three four five", size=3, overlap=1)

    assert chunks == ["one two three", "three four five", "five"]


def test_ingester_indexes_sports_as_llm_sendable_and_private_as_scrubbed(tmp_path):
    sports = tmp_path / "Sports" / "NBA"
    books = tmp_path / "Books"
    sports.mkdir(parents=True)
    books.mkdir(parents=True)
    (sports / "latest.md").write_text("---\ntype: note\n---\n\nNBA playoffs", encoding="utf-8")
    (books / "private.md").write_text("Email person@example.com about reading", encoding="utf-8")

    store = FakeStore()
    ingester = VaultIngester(vault_root=tmp_path, embedder=FakeEmbedder(), store=store)
    count = ingester.ingest()

    assert count == 2
    sports_item = next(item for item in store.upserts if item["metadata"]["folder"] == "Sports/NBA")
    books_item = next(item for item in store.upserts if item["metadata"]["folder"] == "Books")
    assert sports_item["metadata"]["can_send_to_llm"] is True
    assert books_item["metadata"]["can_send_to_llm"] is False
    assert books_item["metadata"]["requires_scrubbing"] is True
    assert "person@example.com" not in books_item["text"]
    assert "[EMAIL_1]" in books_item["text"]
    assert sports_item["point_id"]
    assert books_item["point_id"]
    assert ("obsidian_vault", "path", "Sports/NBA/latest.md") in store.deletes
    assert ("obsidian_vault", "path", "Books/private.md") in store.deletes


def test_ingester_rejects_outside_file(tmp_path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    ingester = VaultIngester(vault_root=tmp_path, embedder=FakeEmbedder(), store=FakeStore())

    with pytest.raises(ValueError, match="outside the Obsidian vault"):
        ingester.ingest_file(outside)


def test_ingester_deletes_records_for_relative_and_absolute_note_paths(tmp_path):
    note = tmp_path / "Books" / "private.md"
    note.parent.mkdir(parents=True)
    note.write_text("private", encoding="utf-8")
    store = FakeStore()
    ingester = VaultIngester(vault_root=tmp_path, embedder=FakeEmbedder(), store=store)

    ingester.delete_file_records("Books/private.md")
    ingester.delete_file_records(note)

    assert store.deletes == [
        ("obsidian_vault", "path", "Books/private.md"),
        ("obsidian_vault", "path", "Books/private.md"),
    ]
