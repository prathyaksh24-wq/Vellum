"""
Bulk ingest Obsidian vault content into the configured vector store.

Phase 7 keeps the store/embedder abstraction lightweight. Phase 8 will replace
those internals with BGE-M3 and Qdrant while preserving this policy-aware flow.
"""

from pathlib import Path
import logging
import uuid

from agent.config import get_settings
from agent.obsidian.folder_policy import FolderPermission, get_policy
from agent.privacy.metadata_strip import safe_chunk_id, strip_obsidian_metadata
from agent.privacy.scrubber import PrivacyScrubber
from agent.rag.embedder import Embedder, get_embedder
from agent.rag.store import VectorStore, get_vector_store

logger = logging.getLogger(__name__)

CHUNK_SIZE = 400
CHUNK_OVERLAP = 50


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if size < 1:
        raise ValueError("Chunk size must be positive.")
    if overlap < 0:
        raise ValueError("Chunk overlap cannot be negative.")
    step = max(size - overlap, 1)
    words = (text or "").split()
    chunks = []
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + size]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks


class VaultIngester:
    def __init__(
        self,
        *,
        vault_root: str | Path | None = None,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
        scrubber: PrivacyScrubber | None = None,
    ):
        settings = get_settings()
        self.vault_root = Path(vault_root or settings.obsidian_vault_path).expanduser().resolve()
        self.embedder = embedder or get_embedder()
        self.store = store or get_vector_store()
        self.scrubber = scrubber or PrivacyScrubber()

    def markdown_files(self) -> list[Path]:
        return sorted(self.vault_root.rglob("*.md"))

    def ingest(self, force: bool = False) -> int:
        count = 0
        files = self.markdown_files()
        logger.info("Ingesting %s Obsidian notes.", len(files))

        for md_file in files:
            count += self.ingest_file(md_file)

        logger.info("Vault ingestion complete. Indexed %s chunks.", count)
        return count

    def ingest_file(self, md_file: str | Path) -> int:
        path = Path(md_file).expanduser().resolve()
        if not path.is_relative_to(self.vault_root):
            raise ValueError("Cannot ingest files outside the Obsidian vault.")

        rel_path = path.relative_to(self.vault_root).as_posix()
        self.delete_file_records(rel_path)
        folder = Path(rel_path).parent.as_posix()
        if folder == ".":
            folder = ""

        policy = get_policy(folder)
        if FolderPermission.INDEXED not in policy.permissions:
            return 0

        raw = path.read_text(encoding="utf-8", errors="ignore")
        clean = strip_obsidian_metadata(raw, str(path))
        if not clean.strip():
            return 0

        if policy.requires_scrubbing:
            clean, _ = self.scrubber.scrub(clean)

        chunks = chunk_text(clean)
        can_send_to_llm = FolderPermission.SENT_TO_LLM in policy.permissions
        for index, chunk in enumerate(chunks):
            self.store.upsert(
                collection="obsidian_vault",
                text=chunk,
                embedding=self.embedder.embed(chunk),
                metadata={
                    "folder": folder,
                    "path": rel_path,
                    "source_hash": safe_chunk_id(rel_path, index),
                    "chunk_index": index,
                    "can_send_to_llm": can_send_to_llm,
                    "requires_scrubbing": policy.requires_scrubbing,
                },
                point_id=_chunk_point_id(rel_path, index),
            )
        return len(chunks)

    def delete_file_records(self, md_file: str | Path) -> None:
        path = Path(md_file).expanduser()
        if path.is_absolute():
            path = path.resolve()
            if not path.is_relative_to(self.vault_root):
                raise ValueError("Cannot delete index records for files outside the Obsidian vault.")
            rel_path = path.relative_to(self.vault_root).as_posix()
        else:
            rel_path = path.as_posix().strip("/")

        delete = getattr(self.store, "delete_by_metadata", None)
        if delete is not None:
            delete("obsidian_vault", "path", rel_path)


def _chunk_point_id(rel_path: str, chunk_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"obsidian:{rel_path}:{chunk_index}"))
