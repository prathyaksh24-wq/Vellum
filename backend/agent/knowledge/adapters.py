"""Compatibility adapters that migrate existing Vellum stores without replacing them."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

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
    skipped: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "imported": self.imported,
            "versions": self.versions,
            "projections": self.projections,
            "skipped": self.skipped,
            "errors": self.errors,
        }


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
        if lowered.startswith("agent/conversations/"):
            return {
                "projection": True,
                "also_source": False,
                "canonical_type": "conversation",
                "projection_type": "conversation",
                "source_kind": "conversation_projection",
                "trust": "projection",
            }
        if lowered.startswith(("agent/memories/", "agent/digests/", "agent/reflections/")):
            return {
                "projection": True,
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
            "also_source": True,
            "canonical_type": "source",
            "projection_type": "",
            "source_kind": source_kind,
            "trust": "raw_import",
        }
