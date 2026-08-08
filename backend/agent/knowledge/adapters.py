"""Compatibility adapters that migrate existing Vellum stores without replacing them."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from agent.knowledge.models import (
    ExternalPolicy,
    ObservationActor,
    ObservationInput,
    ProjectionInput,
    Sensitivity,
    SourceItemInput,
)
from agent.knowledge.store import KnowledgeStore
from agent.obsidian.conversation_export import parse_frontmatter
from agent.obsidian.folder_policy import access_decision


@dataclass
class ImportStats:
    scanned: int = 0
    imported: int = 0
    versions: int = 0
    projections: int = 0
    archived: int = 0
    skipped: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "imported": self.imported,
            "versions": self.versions,
            "projections": self.projections,
            "archived": self.archived,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def _read_only_connection(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _stable_identifier(prefix: str, *parts: object) -> str:
    seed = "\x1f".join(str(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:40]}"


def _logical_source_path(path: str, suffix: str = "") -> str:
    """Return a stable logical reference without exposing a machine path."""

    return f"{path}{suffix}"


class ConversationAdapter:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    @staticmethod
    def load(path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        conversations = payload.get("conversations") if isinstance(payload, dict) else payload
        return [item for item in conversations if isinstance(item, dict)] if isinstance(conversations, list) else []

    def import_records(
        self,
        conversations: Iterable[Mapping[str, Any]],
        *,
        apply: bool,
        limit: int | None = None,
    ) -> ImportStats:
        stats = ImportStats()
        for conversation in conversations:
            if limit is not None and stats.scanned >= limit:
                break
            stats.scanned += 1
            conversation_id = str(
                conversation.get("id") or conversation.get("conversation_id") or conversation.get("thread_id") or ""
            ).strip()
            if not conversation_id:
                stats.skipped += 1
                continue
            if bool(conversation.get("archived", False)):
                stats.archived += 1
            if not apply:
                continue
            try:
                result = self.store.upsert_source(
                    SourceItemInput(
                        kind="conversation",
                        external_id=conversation_id,
                        title=str(conversation.get("title") or "Untitled conversation"),
                        content=json.dumps(conversation, ensure_ascii=False, sort_keys=True, indent=2, default=str),
                        source_path=f"data/ui/conversations.json#{conversation_id}",
                        account_id=str(conversation.get("profile_id") or "default"),
                        sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                        external_policy=ExternalPolicy.DENY_RAW,
                        trust="canonical_conversation",
                        metadata={
                            "thread_id": str(conversation.get("thread_id") or conversation_id),
                            "archived": bool(conversation.get("archived", False)),
                            "pinned": bool(conversation.get("pinned", False)),
                            "message_count": len(conversation.get("messages") or []),
                        },
                    )
                )
                stats.imported += int(result["created"])
                stats.versions += int(result["version_created"])
                self.store.record_observation(
                    ObservationInput(
                        origin="conversation_adapter",
                        actor=ObservationActor.IMPORTED,
                        trigger="bootstrap",
                        action="conversation.imported",
                        source_id=result["source_id"],
                        event_key=f"conversation-import:{conversation_id}:{result['content_hash']}",
                        payload={"message_count": len(conversation.get("messages") or [])},
                        sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                        confidence=1.0,
                    )
                )
            except Exception as exc:
                stats.errors.append({"ref": conversation_id, "error": str(exc)[:300]})
        return stats


class MemoryAdapter:
    """Read Memory Orchestrator SQLite records into shadow source records."""

    def __init__(
        self,
        store: KnowledgeStore,
        database_path: Path,
        *,
        snapshot_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.database_path = Path(database_path)
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else self.database_path.parent

    def import_records(self, *, apply: bool, limit: int | None = None) -> ImportStats:
        stats = ImportStats()
        try:
            connection = _read_only_connection(self.database_path)
        except sqlite3.DatabaseError as exc:
            stats.errors.append({"ref": "data/memory/sessions.db", "error": str(exc)[:300]})
            return stats
        if connection is None:
            return stats

        try:
            if _table_exists(connection, "memory_items"):
                rows = connection.execute(
                    """
                    SELECT id, scope, kind, text, status, source_thread_id,
                           confidence, pinned, created_at, updated_at, archived_at
                    FROM memory_items
                    ORDER BY id ASC
                    """
                ).fetchall()
                for row in rows:
                    if limit is not None and stats.scanned >= limit:
                        break
                    stats.scanned += 1
                    status = str(row["status"] or "active")
                    if status == "archived":
                        stats.archived += 1
                    if not apply:
                        continue
                    result = self.store.upsert_source(
                        SourceItemInput(
                            kind="memory_item",
                            external_id=f"memory-item:{row['id']}",
                            title=f"{str(row['kind'] or 'memory').strip() or 'memory'} memory",
                            content=str(row["text"] or ""),
                            source_path=_logical_source_path(
                                "data/memory/sessions.db",
                                f"#memory_items/{row['id']}",
                            ),
                            account_id=str(row["scope"] or "global"),
                            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                            external_policy=ExternalPolicy.DENY_RAW,
                            trust="memory_orchestrator",
                            status=status,
                            metadata={
                                "memory_id": int(row["id"]),
                                "scope": str(row["scope"] or "global"),
                                "kind": str(row["kind"] or ""),
                                "source_thread_id": str(row["source_thread_id"] or ""),
                                "confidence": float(row["confidence"] or 0.0),
                                "pinned": bool(row["pinned"]),
                                "created_at": str(row["created_at"] or ""),
                                "updated_at": str(row["updated_at"] or ""),
                                "archived_at": str(row["archived_at"] or ""),
                            },
                        )
                    )
                    stats.imported += int(result["created"])
                    stats.versions += int(result["version_created"])

            if _table_exists(connection, "memory_summaries"):
                summary_rows = connection.execute(
                    "SELECT scope, summary, updated_at FROM memory_summaries ORDER BY scope ASC"
                ).fetchall()
                for row in summary_rows:
                    stats.projections += 1
                    if not apply:
                        continue
                    summary = str(row["summary"] or "")
                    self.store.register_projection(
                        ProjectionInput(
                            canonical_type="memory",
                            canonical_id=_stable_identifier("memory-scope", row["scope"]),
                            target="memory_orchestrator",
                            target_ref=_logical_source_path(
                                "data/memory/sessions.db",
                                f"#memory_summaries/{row['scope']}",
                            ),
                            content_hash=_content_hash(summary),
                            projection_type="memory_summary",
                            generated_by="memory_orchestrator",
                            do_not_reingest=True,
                            metadata={
                                "scope": str(row["scope"] or ""),
                                "updated_at": str(row["updated_at"] or ""),
                            },
                        )
                    )
        except (OSError, sqlite3.DatabaseError, KeyError, TypeError, ValueError) as exc:
            stats.errors.append({"ref": "data/memory/sessions.db", "error": str(exc)[:300]})
        finally:
            connection.close()

        self._register_context_snapshots(stats, apply=apply)
        return stats

    def _register_context_snapshots(self, stats: ImportStats, *, apply: bool) -> None:
        for name in ("USER.md", "MEMORY.md"):
            path = self.snapshot_dir / name
            if not path.is_file():
                continue
            stats.projections += 1
            if not apply:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                self.store.register_projection(
                    ProjectionInput(
                        canonical_type="memory",
                        canonical_id=f"memory-snapshot:{name.casefold()}",
                        target="filesystem",
                        target_ref=_logical_source_path("data/memory", f"/{name}"),
                        content_hash=_content_hash(content),
                        projection_type="memory_snapshot",
                        generated_by="memory_orchestrator",
                        do_not_reingest=True,
                        metadata={"filename": name},
                    )
                )
            except OSError as exc:
                stats.errors.append({"ref": f"data/memory/{name}", "error": str(exc)[:300]})


class RetrievalIndexAdapter:
    """Register existing FTS/vector rows as disposable, non-ingestible projections."""

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        fts5_path: Path,
        vector_path: Path | None = None,
        vector_reader: Callable[[int | None], Iterable[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.store = store
        self.fts5_path = Path(fts5_path)
        self.vector_path = Path(vector_path) if vector_path is not None else None
        self.vector_reader = vector_reader

    def import_records(self, *, apply: bool, limit: int | None = None) -> ImportStats:
        stats = ImportStats()
        self._import_fts5(stats, apply=apply, limit=limit)
        self._import_vectors(stats, apply=apply, limit=limit)
        return stats

    def _import_fts5(self, stats: ImportStats, *, apply: bool, limit: int | None) -> None:
        try:
            connection = _read_only_connection(self.fts5_path)
        except sqlite3.DatabaseError as exc:
            stats.errors.append({"ref": "data/memory/fts5.db", "error": str(exc)[:300]})
            return
        if connection is None:
            return
        try:
            if not _table_exists(connection, "qa_fts"):
                return
            rows = connection.execute(
                "SELECT rowid, content, created, thread_id, source_paths FROM qa_fts ORDER BY rowid ASC"
            ).fetchall()
            for row in rows:
                if limit is not None and stats.scanned >= limit:
                    break
                stats.scanned += 1
                try:
                    source_paths = json.loads(str(row["source_paths"] or "[]"))
                except json.JSONDecodeError:
                    source_paths = []
                if not isinstance(source_paths, list):
                    source_paths = []
                thread_id = str(row["thread_id"] or "")
                rowid = int(row["rowid"])
                stats.projections += 1
                if not apply:
                    continue
                self.store.register_projection(
                    ProjectionInput(
                        canonical_type="retrieval_document",
                        canonical_id=_stable_identifier(
                            "fts5", source_paths[0] if source_paths else thread_id, rowid
                        ),
                        target="fts5",
                        target_ref=_logical_source_path("data/memory/fts5.db", f"#qa_fts/{rowid}"),
                        content_hash=_content_hash(str(row["content"] or "")),
                        projection_type="fts5_document",
                        generated_by="memory_orchestrator",
                        do_not_reingest=True,
                        metadata={
                            "rowid": rowid,
                            "thread_id": thread_id,
                            "created": str(row["created"] or ""),
                            "source_paths": [str(path) for path in source_paths],
                        },
                    )
                )
        except (OSError, sqlite3.DatabaseError, TypeError, ValueError) as exc:
            stats.errors.append({"ref": "data/memory/fts5.db", "error": str(exc)[:300]})
        finally:
            connection.close()

    def _import_vectors(self, stats: ImportStats, *, apply: bool, limit: int | None) -> None:
        if self.vector_reader is None and (self.vector_path is None or not self.vector_path.is_dir()):
            return
        try:
            entries = self.vector_reader(limit) if self.vector_reader is not None else self._read_chroma(limit)
            for entry in entries:
                if limit is not None and stats.scanned >= limit:
                    break
                collection = str(entry.get("collection") or "")
                vector_id = str(entry.get("id") or "")
                if not collection or not vector_id:
                    stats.skipped += 1
                    continue
                stats.scanned += 1
                metadata = entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else {}
                clean_metadata = {str(key): value for key, value in metadata.items() if key != "text"}
                digest_input = json.dumps(clean_metadata, ensure_ascii=False, sort_keys=True, default=str)
                stats.projections += 1
                if not apply:
                    continue
                self.store.register_projection(
                    ProjectionInput(
                        canonical_type="retrieval_document",
                        canonical_id=_stable_identifier("chroma", collection, vector_id),
                        target="chroma",
                        target_ref=_logical_source_path(
                            "data/embeddings/chroma", f"#{collection}/{vector_id}"
                        ),
                        content_hash=_content_hash(digest_input),
                        projection_type="vector_document",
                        generated_by="rag",
                        do_not_reingest=True,
                        metadata={
                            "collection": collection,
                            "vector_id": vector_id,
                            "metadata": clean_metadata,
                        },
                    )
                )
        except (OSError, RuntimeError, TypeError, ValueError, ImportError) as exc:
            stats.errors.append({"ref": "data/embeddings/chroma", "error": str(exc)[:300]})

    def _read_chroma(self, limit: int | None) -> Iterable[Mapping[str, Any]]:
        if self.vector_path is None:
            return []
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError:
            return []
        client = chromadb.PersistentClient(
            path=str(self.vector_path),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        remaining = limit
        entries: list[dict[str, Any]] = []
        for collection_ref in client.list_collections():
            collection_name = str(getattr(collection_ref, "name", collection_ref))
            collection = client.get_collection(collection_name)
            kwargs: dict[str, Any] = {"include": ["metadatas"]}
            if remaining is not None:
                kwargs["limit"] = max(0, remaining)
            result = collection.get(**kwargs)
            ids = result.get("ids") or []
            metadata_rows = result.get("metadatas") or []
            for index, vector_id in enumerate(ids):
                entries.append(
                    {
                        "collection": collection_name,
                        "id": vector_id,
                        "metadata": metadata_rows[index] if index < len(metadata_rows) else {},
                    }
                )
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return entries
        return entries


class ObsidianAdapter:
    """Classify current vault artifacts as sources or rebuildable projections."""

    def __init__(self, store: KnowledgeStore, vault_root: Path) -> None:
        self.store = store
        self.vault_root = vault_root.resolve()

    def candidate_paths(
        self,
        *,
        library: bool,
        knowledge_wiki: bool,
        agent_projections: bool,
        archives: bool = True,
    ) -> list[Path]:
        roots: list[Path] = []
        if library:
            roots.extend(self.vault_root / folder for folder in ("Library", "Books", "X", "Youtube", "Sports"))
        if knowledge_wiki:
            roots.append(self.vault_root / "Knowledge")
        if agent_projections:
            roots.extend(
                self.vault_root / folder
                for folder in ("Agent/Conversations", "Agent/Memories", "Agent/Digests", "Agent/Reflections")
            )
        if archives:
            roots.extend(
                self.vault_root / folder
                for folder in ("Archive/Agent/Conversations", "Archive/Legacy Agent Logs")
            )
        paths: set[Path] = set()
        for root in roots:
            if root.is_file() and root.suffix.casefold() == ".md":
                paths.add(root)
            elif root.is_dir():
                paths.update(path for path in root.rglob("*.md") if path.is_file())
        return sorted(paths)

    def import_paths(self, paths: Iterable[Path], *, apply: bool, limit: int | None = None) -> ImportStats:
        stats = ImportStats()
        for path in paths:
            if limit is not None and stats.scanned >= limit:
                break
            stats.scanned += 1
            try:
                relative = path.resolve().relative_to(self.vault_root).as_posix()
            except (OSError, ValueError):
                stats.skipped += 1
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                metadata = parse_frontmatter(content)
                classification = self._classify(relative, metadata)
                if classification["projection"]:
                    if apply:
                        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                        canonical_id = str(
                            metadata.get("canonical_id")
                            or metadata.get("conversation_id")
                            or metadata.get("id")
                            or f"legacy:{relative}"
                        )
                        self.store.register_projection(
                            ProjectionInput(
                                canonical_type=classification["canonical_type"],
                                canonical_id=canonical_id,
                                target="obsidian",
                                target_ref=relative,
                                content_hash=digest,
                                projection_type=classification["projection_type"],
                                generated_by=str(metadata.get("generated_by") or "vellum-legacy"),
                                do_not_reingest=True,
                                metadata={"legacy": True, "user_modified": metadata.get("user_modified", "false")},
                            )
                        )
                    stats.projections += 1
                    if classification["archive"]:
                        stats.archived += 1
                    if not classification["also_source"]:
                        continue
                if metadata.get("do_not_reingest", "").casefold() in {"true", "yes", "1"}:
                    stats.skipped += 1
                    continue
                if not apply:
                    continue
                decision = access_decision(relative)
                sensitivity = Sensitivity.PRIVATE_LOCAL_ONLY if decision.is_private else Sensitivity.PRIVATE
                external_policy = ExternalPolicy.DENY_RAW if decision.is_private else ExternalPolicy.ALLOW_SCRUBBED
                external_id = str(
                    metadata.get("video_id")
                    or metadata.get("status_id")
                    or metadata.get("id")
                    or relative
                )
                result = self.store.upsert_source(
                    SourceItemInput(
                        kind=classification["source_kind"],
                        external_id=external_id,
                        title=self._title(path, content, metadata),
                        content=content,
                        source_path=relative,
                        uri=str(metadata.get("url") or metadata.get("x_url") or ""),
                        sensitivity=sensitivity,
                        external_policy=external_policy,
                        trust=str(metadata.get("source_trust") or classification["trust"]),
                        metadata={
                            "vault_path": relative,
                            "legacy_projection": bool(classification["projection"]),
                            "frontmatter_type": metadata.get("type", ""),
                        },
                    )
                )
                stats.imported += int(result["created"])
                stats.versions += int(result["version_created"])
            except Exception as exc:
                stats.errors.append({"ref": relative, "error": str(exc)[:300]})
        return stats

    @staticmethod
    def _title(path: Path, content: str, metadata: Mapping[str, str]) -> str:
        if metadata.get("title"):
            return str(metadata["title"])
        heading = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), "")
        return heading or path.stem

    @staticmethod
    def _classify(relative: str, metadata: Mapping[str, str]) -> dict[str, Any]:
        lowered = relative.casefold()
        if lowered.startswith("archive/agent/conversations/"):
            return {
                "projection": True,
                "archive": True,
                "also_source": False,
                "canonical_type": "conversation",
                "projection_type": "conversation_archive",
                "source_kind": "conversation_archive_projection",
                "trust": "projection",
            }
        if lowered.startswith("archive/legacy agent logs/"):
            return {
                "projection": True,
                "archive": True,
                "also_source": False,
                "canonical_type": "conversation",
                "projection_type": "legacy_conversation_archive",
                "source_kind": "conversation_archive_projection",
                "trust": "projection",
            }
        if lowered.startswith("agent/conversations/"):
            return {
                "projection": True,
                "archive": False,
                "also_source": False,
                "canonical_type": "conversation",
                "projection_type": "conversation",
                "source_kind": "conversation_projection",
                "trust": "projection",
            }
        if lowered.startswith(("agent/memories/", "agent/digests/", "agent/reflections/")):
            return {
                "projection": True,
                "archive": False,
                "also_source": False,
                "canonical_type": "memory",
                "projection_type": "memory",
                "source_kind": "memory_projection",
                "trust": "projection",
            }
        if lowered.startswith("knowledge/"):
            support_page = lowered in {
                "knowledge/index.md",
                "knowledge/schema.md",
                "knowledge/log.md",
            } or lowered.startswith(("knowledge/.history/", "knowledge/lint/"))
            return {
                "projection": True,
                "archive": False,
                "also_source": not support_page,
                "canonical_type": "derived_insight",
                "projection_type": "karpathy_wiki",
                "source_kind": "legacy_knowledge_page",
                "trust": str(metadata.get("source_trust") or "maintained"),
            }
        if lowered.startswith(("library/x/", "x/")):
            source_kind = "x_post" if metadata.get("status_id") else "x_archive_note"
        elif lowered.startswith(("library/youtube/", "youtube/")):
            source_kind = "youtube_video" if metadata.get("video_id") else "youtube_note"
        elif lowered.startswith(("library/sports/", "sports/")):
            source_kind = "sports_observation"
        elif lowered.startswith(("library/books/", "books/")):
            source_kind = "book_page"
        else:
            source_kind = "library_note"
        return {
            "projection": False,
            "archive": False,
            "also_source": True,
            "canonical_type": "source",
            "projection_type": "",
            "source_kind": source_kind,
            "trust": "raw_import",
        }
