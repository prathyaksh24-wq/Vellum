"""Controlled proof that existing Vellum evidence materializes without duplication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from agent.knowledge.adapters import ConversationAdapter, ObsidianAdapter
from agent.knowledge.backup import KnowledgeBackupService
from agent.knowledge.models import ContextPackRequest, MaterializationCanaryRequest
from agent.knowledge.store import KnowledgeStore
from agent.obsidian.conversation_export import parse_frontmatter


CANARY_CONFIRMATION = "APPLY_KNOWLEDGE_CANARY"
_STABLE_TABLES = ("sources", "source_versions", "observations", "projections")


class MaterializationCanaryError(ValueError):
    """Raised before a canary write when its safety contract is not satisfied."""


@dataclass(frozen=True)
class _CanarySelection:
    conversation: Mapping[str, Any] | None
    obsidian_source: Path | None
    x_item: Path | None
    wiki_projection: Path | None
    public: dict[str, dict[str, Any] | None]
    missing: tuple[str, ...]


class MaterializationCanary:
    """Preview, apply twice, reconcile, and roll back one bounded evidence set."""

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        conversations_path: Path,
        vault_root: Path,
    ) -> None:
        self.store = store
        self.conversations_path = Path(conversations_path)
        self.vault_root = Path(vault_root).resolve()
        self.backups = KnowledgeBackupService(store)

    def run(self, request: MaterializationCanaryRequest) -> dict[str, Any]:
        selection = self._select()
        before = self._counts()
        integrity_before = self.store.integrity_check()
        base = {
            "mode": "apply" if request.apply else "preview",
            "ready": not selection.missing and integrity_before["ok"],
            "selection": selection.public,
            "missing": list(selection.missing),
            "counts_before": before,
            "integrity_before": integrity_before,
        }
        if not request.apply:
            return {**base, "status": "ready" if base["ready"] else "incomplete", "passed": None}
        if request.confirmation != CANARY_CONFIRMATION:
            raise MaterializationCanaryError(
                f"Canary apply requires confirmation token {CANARY_CONFIRMATION}."
            )
        if selection.missing:
            raise MaterializationCanaryError(
                "Canary apply requires one conversation, one non-X vault source, "
                "one X item, and one generated wiki projection marked do_not_reingest."
            )
        if not integrity_before["ok"]:
            raise MaterializationCanaryError("Knowledge Core integrity must pass before canary apply.")

        source_fingerprints = self._input_fingerprints(selection)
        backup = self.backups.create(self._archive_path("pre-canary"))
        try:
            first = self._apply(selection)
            counts_after_first = self._counts()
            identities_after_first = self._identity_snapshot(selection)
            second = self._apply(selection)
            counts_after_second = self._counts()
            identities_after_second = self._identity_snapshot(selection)
            reconciliation = self._reconcile(
                selection=selection,
                first=first,
                second=second,
                before=before,
                after_first=counts_after_first,
                after_second=counts_after_second,
                identities_after_first=identities_after_first,
                identities_after_second=identities_after_second,
                input_fingerprints=source_fingerprints,
            )
        except Exception as exc:
            rollback = self._restore_backup(backup, before)
            return {
                **base,
                "status": "rolled_back",
                "passed": False,
                "backup": backup,
                "rollback": rollback,
                "error": {"type": type(exc).__name__},
            }

        if not reconciliation["passed"]:
            rollback = self._restore_backup(backup, before)
            return {
                **base,
                "status": "rolled_back",
                "passed": False,
                "backup": backup,
                "passes": {"first": first, "second": second},
                "reconciliation": reconciliation,
                "rollback": rollback,
            }
        return {
            **base,
            "status": "completed",
            "passed": True,
            "backup": backup,
            "passes": {"first": first, "second": second},
            "reconciliation": reconciliation,
        }

    def _select(self) -> _CanarySelection:
        conversations = sorted(
            (
                item
                for item in ConversationAdapter.load(self.conversations_path)
                if str(item.get("id") or item.get("conversation_id") or item.get("thread_id") or "").strip()
            ),
            key=lambda item: str(
                item.get("id") or item.get("conversation_id") or item.get("thread_id") or ""
            ),
        )
        conversation = conversations[0] if conversations else None
        adapter = ObsidianAdapter(self.store, self.vault_root)
        library_paths = adapter.candidate_paths(
            library=True,
            knowledge_wiki=False,
            agent_projections=False,
            archives=False,
        )
        x_item = self._first_path(library_paths, role="x_item")
        obsidian_source = self._first_path(library_paths, role="obsidian_source")
        wiki_paths = adapter.candidate_paths(
            library=False,
            knowledge_wiki=True,
            agent_projections=False,
            archives=False,
        )
        wiki_projection = self._first_path(wiki_paths, role="wiki_projection")
        public = {
            "conversation": self._conversation_descriptor(conversation) if conversation is not None else None,
            "obsidian_source": self._note_descriptor(obsidian_source, "obsidian_source") if obsidian_source else None,
            "x_item": self._note_descriptor(x_item, "x_item") if x_item else None,
            "wiki_projection": self._note_descriptor(wiki_projection, "wiki_projection") if wiki_projection else None,
        }
        missing = tuple(role for role, value in public.items() if value is None)
        return _CanarySelection(
            conversation=conversation,
            obsidian_source=obsidian_source,
            x_item=x_item,
            wiki_projection=wiki_projection,
            public=public,
            missing=missing,
        )

    def _first_path(self, paths: list[Path], *, role: str) -> Path | None:
        for path in paths:
            try:
                relative = path.resolve().relative_to(self.vault_root).as_posix()
                content = path.read_text(encoding="utf-8", errors="ignore")
                metadata = parse_frontmatter(content)
            except (OSError, ValueError):
                continue
            is_x = relative.casefold().startswith(("library/x/", "x/"))
            do_not_reingest = str(metadata.get("do_not_reingest") or "").casefold() in {
                "true",
                "yes",
                "1",
            }
            generated_by = str(metadata.get("generated_by") or "").strip()
            if role == "x_item" and is_x and not do_not_reingest:
                return path
            if role == "obsidian_source" and not is_x and not do_not_reingest:
                return path
            if role == "wiki_projection" and do_not_reingest and generated_by:
                return path
        return None

    @staticmethod
    def _conversation_descriptor(conversation: Mapping[str, Any]) -> dict[str, Any]:
        external_id = str(
            conversation.get("id") or conversation.get("conversation_id") or conversation.get("thread_id") or ""
        ).strip()
        return {
            "role": "conversation",
            "kind": "conversation",
            "external_id": external_id,
            "title": str(conversation.get("title") or "Untitled conversation"),
            "ref": f"data/ui/conversations.json#{external_id}",
        }

    def _note_descriptor(self, path: Path, role: str) -> dict[str, Any]:
        relative = path.resolve().relative_to(self.vault_root).as_posix()
        content = path.read_text(encoding="utf-8", errors="ignore")
        metadata = parse_frontmatter(content)
        classification = ObsidianAdapter._classify(relative, metadata)
        external_id = str(
            metadata.get("video_id")
            or metadata.get("status_id")
            or metadata.get("id")
            or relative
        )
        descriptor = {
            "role": role,
            "kind": classification["source_kind"],
            "external_id": external_id,
            "title": ObsidianAdapter._title(path, content, metadata),
            "ref": relative,
        }
        if role == "wiki_projection":
            descriptor.update(
                {
                    "canonical_type": classification["canonical_type"],
                    "canonical_id": str(
                        metadata.get("canonical_id")
                        or metadata.get("conversation_id")
                        or metadata.get("id")
                        or f"legacy:{relative}"
                    ),
                    "target": "obsidian",
                    "do_not_reingest": True,
                }
            )
        return descriptor

    def _apply(self, selection: _CanarySelection) -> dict[str, Any]:
        conversation_stats = ConversationAdapter(self.store).import_records(
            [selection.conversation] if selection.conversation is not None else [],
            apply=True,
        )
        adapter = ObsidianAdapter(self.store, self.vault_root)
        return {
            "conversation": conversation_stats.as_dict(),
            "obsidian_source": adapter.import_paths(
                [selection.obsidian_source] if selection.obsidian_source else [], apply=True
            ).as_dict(),
            "x_item": adapter.import_paths(
                [selection.x_item] if selection.x_item else [], apply=True
            ).as_dict(),
            "wiki_projection": adapter.import_paths(
                [selection.wiki_projection] if selection.wiki_projection else [], apply=True
            ).as_dict(),
        }

    def _reconcile(
        self,
        *,
        selection: _CanarySelection,
        first: dict[str, Any],
        second: dict[str, Any],
        before: dict[str, int],
        after_first: dict[str, int],
        after_second: dict[str, int],
        identities_after_first: dict[str, Any],
        identities_after_second: dict[str, Any],
        input_fingerprints: dict[str, str],
    ) -> dict[str, Any]:
        citations = self._citation_checks(selection, identities_after_second)
        errors = [
            error
            for pass_result in (first, second)
            for role in pass_result.values()
            for error in role.get("errors", [])
        ]
        second_pass_delta = {
            table: after_second[table] - after_first[table] for table in _STABLE_TABLES
        }
        expected_sources = {"conversation", "obsidian_source", "x_item"}
        source_identities = identities_after_second["sources"]
        projection = identities_after_second["projections"].get("wiki_projection")
        gates = {
            "no_adapter_errors": not errors,
            "counts_reconcile": all(value == 0 for value in second_pass_delta.values()),
            "stable_identifiers": identities_after_first == identities_after_second,
            "expected_records_present": expected_sources <= set(source_identities) and projection is not None,
            "provenance_retained": all(
                item.get("source_path") and item.get("trust") and item.get("current_version_id")
                for item in source_identities.values()
            ),
            "citations_retrievable": bool(citations) and all(item["retrieved"] for item in citations),
            "projection_not_reingestible": bool(projection and projection.get("do_not_reingest")),
            "source_inputs_unchanged": input_fingerprints == self._input_fingerprints(selection),
            "integrity": self.store.integrity_check()["ok"],
        }
        return {
            "passed": all(gates.values()),
            "gates": gates,
            "stable_tables": list(_STABLE_TABLES),
            "counts": {
                "before": before,
                "after_first": after_first,
                "after_second": after_second,
                "second_pass_delta": second_pass_delta,
            },
            "identities": identities_after_second,
            "citations": citations,
            "adapter_errors": errors,
        }

    def _identity_snapshot(self, selection: _CanarySelection) -> dict[str, Any]:
        sources = self.store.list_sources(limit=500)
        source_identities: dict[str, dict[str, Any]] = {}
        for role in ("conversation", "obsidian_source", "x_item"):
            descriptor = selection.public.get(role) or {}
            match = next(
                (
                    source
                    for source in sources
                    if source["kind"] == descriptor.get("kind")
                    and source["external_id"] == descriptor.get("external_id")
                ),
                None,
            )
            if match is not None:
                source_identities[role] = {
                    key: match[key]
                    for key in (
                        "id",
                        "kind",
                        "external_id",
                        "source_path",
                        "trust",
                        "sensitivity",
                        "external_policy",
                        "current_version_id",
                    )
                }
        wiki_descriptor = selection.public.get("wiki_projection") or {}
        projections = self.store.list_projections(
            target="obsidian",
            target_ref=str(wiki_descriptor.get("ref") or ""),
            limit=1,
        )
        wiki_match = next(
            (
                projection
                for projection in projections
                if projection["target_ref"] == wiki_descriptor.get("ref")
            ),
            None,
        )
        projection_identities = {}
        if wiki_match is not None:
            projection_identities["wiki_projection"] = {
                key: wiki_match[key]
                for key in (
                    "id",
                    "canonical_type",
                    "canonical_id",
                    "target",
                    "target_ref",
                    "projection_type",
                    "content_hash",
                    "generated_by",
                    "do_not_reingest",
                )
            }
        return {"sources": source_identities, "projections": projection_identities}

    def _citation_checks(
        self,
        selection: _CanarySelection,
        identities: dict[str, Any],
    ) -> list[dict[str, Any]]:
        checks = []
        for role, source in identities["sources"].items():
            descriptor = selection.public.get(role) or {}
            pack = self.store.create_context_pack(
                ContextPackRequest(
                    query=f"{descriptor.get('title', '')} {descriptor.get('external_id', '')}".strip(),
                    destination="local",
                    source_kinds=[str(descriptor.get("kind") or "")],
                )
            )
            evidence = next(
                (item for item in pack["evidence"] if item["source_id"] == source["id"]),
                None,
            )
            checks.append(
                {
                    "role": role,
                    "source_id": source["id"],
                    "retrieved": evidence is not None,
                    "content_hash": str((evidence or {}).get("content_hash") or ""),
                }
            )
        return checks

    def _counts(self) -> dict[str, int]:
        counts = self.store.status()["counts"]
        return {table: int(counts[table]) for table in _STABLE_TABLES}

    def _input_fingerprints(self, selection: _CanarySelection) -> dict[str, str]:
        paths = {
            "conversations": self.conversations_path,
            "obsidian_source": selection.obsidian_source,
            "x_item": selection.x_item,
            "wiki_projection": selection.wiki_projection,
        }
        result = {}
        for role, path in paths.items():
            if path is not None and path.is_file():
                result[role] = self._hash_file(path)
        return result

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _archive_path(self, prefix: str) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return self.store.db_path.parent / "backups" / f"{prefix}-{timestamp}.zip"

    def _restore_backup(self, backup: dict[str, Any], before: dict[str, int]) -> dict[str, Any]:
        restored = self.backups.restore(
            str(backup["path"]),
            rollback_destination=self._archive_path("failed-canary-state"),
        )
        restored["counts_match_before"] = self._counts() == before
        return restored
