"""Agent-maintained Obsidian knowledge wiki.

The wiki is a private, maintained knowledge layer.  ``Knowledge/`` is the
only directory this service mutates.  ``Library/`` is never read as part of a
normal wiki operation: a caller must supply content or explicitly approve a
specific source path before ingestion can use it.
"""

from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from agent.privacy.scrubber import PrivacyScrubber


WIKI_FOLDER = "Knowledge"
PAGE_FOLDERS = {
    "entity": "entities",
    "concept": "concepts",
    "topic": "topics",
    "project": "projects",
    "analysis": "analyses",
    "source": "sources",
}
SUPPORT_FOLDERS = ("inbox", "lint", ".history")
REQUIRED_FIELDS = (
    "id",
    "type",
    "title",
    "description",
    "sensitivity",
    "status",
    "created",
    "updated",
    "version",
    "sources",
    "source_count",
    "source_trust",
    "provenance",
    "tags",
)
VALID_STATUSES = {"draft", "verified", "needs_review", "superseded"}
VALID_SENSITIVITIES = {"public", "private"}
VALID_SOURCE_TRUST = {
    "maintained",
    "user_supplied",
    "approved_path",
    "trusted",
    "untrusted",
    "unknown",
    "mixed",
}
_SOURCE_TRUST_ALIASES = {
    "approved": "approved_path",
    "path_approved": "approved_path",
    "raw": "untrusted",
    "user": "user_supplied",
    "supplied": "user_supplied",
    "wiki": "maintained",
    "verified": "trusted",
}
_SUPPLIED_SOURCE_PREFIX = "supplied-content:"
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


class KnowledgeWikiError(ValueError):
    """Raised when a wiki operation violates its schema or path policy."""


class KnowledgeWiki:
    """Safe, deterministic file operations for Vellum's Obsidian wiki."""

    def __init__(self, vault_root: str | Path, wiki_folder: str = WIKI_FOLDER) -> None:
        self.vault_root = Path(vault_root).expanduser().resolve()
        self.wiki_folder = _safe_segment(wiki_folder)
        if self.wiki_folder.casefold() != WIKI_FOLDER.casefold():
            raise KnowledgeWikiError("Knowledge wiki writes must stay inside Knowledge/.")
        if not self.vault_root.exists() or not self.vault_root.is_dir():
            raise KnowledgeWikiError(f"Obsidian vault does not exist: {self.vault_root}")
        self.wiki_root = (self.vault_root / self.wiki_folder).resolve()
        if not self.wiki_root.is_relative_to(self.vault_root):
            raise KnowledgeWikiError("Knowledge wiki must stay inside the Obsidian vault.")
        self.scrubber = PrivacyScrubber()

    def ensure_structure(self) -> dict[str, Any]:
        self.wiki_root.mkdir(parents=True, exist_ok=True)
        for folder in (*PAGE_FOLDERS.values(), *SUPPORT_FOLDERS):
            (self.wiki_root / folder).mkdir(parents=True, exist_ok=True)

        seeds = {
            "schema.md": _schema_document(self.wiki_folder),
            "index.md": _empty_index_document(),
            "overview.md": _overview_document(),
            "log.md": _log_document(),
        }
        created: list[str] = []
        for filename, content in seeds.items():
            path = self.wiki_root / filename
            if path.exists():
                continue
            _atomic_write(path, content)
            created.append(self._relative(path))
        return {"ready": True, "root": self.wiki_folder, "created": created}

    def status(self) -> dict[str, Any]:
        self.ensure_structure()
        counts = Counter()
        pages = self._content_pages()
        for path in pages:
            metadata, _body = _parse_document(path.read_text(encoding="utf-8", errors="ignore"))
            counts[str(metadata.get("type") or "unknown")] += 1
        return {
            "ready": True,
            "root": self.wiki_folder,
            "index": f"{self.wiki_folder}/index.md",
            "schema": f"{self.wiki_folder}/schema.md",
            "log": f"{self.wiki_folder}/log.md",
            "page_count": len(pages),
            "counts": dict(sorted(counts.items())),
            "source_trust_counts": self._source_trust_counts(pages),
            "source_policy": {
                "library_auto_ingestion": False,
                "path_ingestion_requires_explicit_approval": True,
            },
            "inbox_count": len(list((self.wiki_root / "inbox").glob("*.md"))),
            "lint_report_count": len(list((self.wiki_root / "lint").glob("*.md"))),
            "history_count": sum(
                1 for path in (self.wiki_root / ".history").rglob("*.md") if path.is_file()
            ),
        }

    def _source_trust_counts(self, pages: Iterable[Path]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for path in pages:
            metadata, _body = _parse_document(path.read_text(encoding="utf-8", errors="ignore"))
            counts[str(metadata.get("source_trust") or "unknown")] += 1
        return dict(sorted(counts.items()))

    def upsert_page(
        self,
        *,
        title: str,
        page_type: str,
        content: str,
        description: str = "",
        sources: Iterable[str] | None = None,
        links: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        status: str = "draft",
        sensitivity: str = "private",
        source_trust: str = "",
        provenance: Iterable[dict[str, Any] | str] | None = None,
        page_id: str = "",
        identity: str = "",
        stable_id: str = "",
        id: str = "",
    ) -> dict[str, Any]:
        self.ensure_structure()
        clean_title = _clean_title(title)
        clean_type = page_type.strip().casefold()
        if clean_type not in PAGE_FOLDERS:
            raise KnowledgeWikiError(f"Unsupported page type: {page_type!r}.")
        clean_status = status.strip().casefold() or "draft"
        if clean_status not in VALID_STATUSES:
            raise KnowledgeWikiError(f"Unsupported page status: {status!r}.")
        clean_sensitivity = sensitivity.strip().casefold() or "private"
        if clean_sensitivity not in VALID_SENSITIVITIES:
            raise KnowledgeWikiError(f"Unsupported page sensitivity: {sensitivity!r}.")
        clean_source_trust = _clean_source_trust(source_trust or "maintained")
        clean_content = _clean_body(content, clean_title)
        if not clean_content:
            raise KnowledgeWikiError("Knowledge page content is required.")

        clean_sources = self._normalize_sources(sources or [])
        clean_links = _unique(_clean_title(item) for item in links or [] if str(item).strip())
        clean_tags = _unique(_slug(item) for item in tags or [] if str(item).strip())
        requested_id = _clean_page_id(page_id or identity or stable_id or id)
        path = self.wiki_root / PAGE_FOLDERS[clean_type] / f"{_slug(clean_title)}.md"
        identity_path: Path | None = None
        if requested_id:
            identity_path = self._find_page_by_id(requested_id)
            if identity_path is not None:
                existing_metadata, _existing_body = _parse_document(
                    identity_path.read_text(encoding="utf-8", errors="ignore")
                )
                existing_type = str(existing_metadata.get("type") or "").strip().casefold()
                if existing_type and existing_type != clean_type:
                    raise KnowledgeWikiError(
                        f"Stable page identity {requested_id!r} already belongs to type {existing_type!r}."
                    )
                path = identity_path
        title_path = self.wiki_root / PAGE_FOLDERS[clean_type] / f"{_slug(clean_title)}.md"
        if identity_path is not None and title_path.exists() and title_path.resolve() != identity_path.resolve():
            raise KnowledgeWikiError(
                f"A {clean_type} page with title {clean_title!r} already exists; use its stable identity."
            )
        old_metadata: dict[str, Any] = {}
        old_text = ""
        if path.exists():
            old_text = path.read_text(encoding="utf-8", errors="ignore")
            old_metadata, _old_body = _parse_document(old_text)

        if old_text and not source_trust:
            clean_source_trust = _clean_source_trust(str(old_metadata.get("source_trust") or "maintained"))
        if old_text and requested_id and str(old_metadata.get("id") or "").strip() != requested_id:
            raise KnowledgeWikiError(
                f"A page already exists at {self._relative(path)} with a different stable identity."
            )

        old_id = str(old_metadata.get("id") or "").strip()
        page_identity = requested_id or old_id or f"knowledge:{clean_type}:{_slug(clean_title)}"
        page_identity = _clean_page_id(page_identity)
        old_sources = _as_list(old_metadata.get("sources"))
        merged_sources = _unique([*old_sources, *clean_sources])
        merged_provenance = _merge_provenance(
            _as_provenance(old_metadata.get("provenance")),
            _as_provenance(provenance),
            merged_sources,
            clean_source_trust,
        )
        now = _now()
        metadata = {
            "id": page_identity,
            "type": clean_type,
            "title": clean_title,
            "description": _description(description or clean_content),
            "sensitivity": clean_sensitivity,
            "status": clean_status,
            "created": str(old_metadata.get("created") or now),
            "updated": now,
            "version": int(old_metadata.get("version") or 0) + 1,
            "sources": merged_sources,
            "source_count": 0,
            "source_trust": clean_source_trust,
            "provenance": merged_provenance,
            "tags": _unique([*_as_list(old_metadata.get("tags")), *clean_tags]),
        }
        metadata["source_count"] = len(metadata["sources"])
        document = _render_page(metadata, clean_content, clean_links)
        if old_text and _without_volatile_metadata(old_text) == _without_volatile_metadata(document):
            return {"created": False, "updated": False, "path": self._relative(path), "page": metadata}

        if old_text and int(old_metadata.get("version") or 0) > 0:
            self._save_history(path, old_text, int(old_metadata.get("version") or 1))
        _atomic_write(path, document)
        if identity_path is not None and path.resolve() != title_path.resolve():
            # A stable identity permits a deliberate rename without leaving a
            # near-duplicate page behind.  Both paths are inside Knowledge/.
            old_path = path
            new_path = title_path
            if new_path.exists():
                raise KnowledgeWikiError(f"Knowledge page path already exists: {self._relative(new_path)}")
            old_history = self._history_dir(old_path)
            _atomic_move(old_path, new_path)
            if old_history.exists():
                new_history = self._history_dir(new_path)
                if not new_history.exists():
                    old_history.replace(new_history)
            path = new_path
        self.rebuild_index()
        action = "update" if old_text else "ingest"
        self.append_log(action, clean_title, path=self._relative(path), detail=f"{clean_type} v{metadata['version']}")
        return {
            "created": not bool(old_text),
            "updated": True,
            "path": self._relative(path),
            "ref": _page_ref(self._relative(path), page_identity),
            "page": metadata,
        }

    def ingest_source(
        self,
        *,
        source_path: str = "",
        title: str = "",
        synthesis: str = "",
        content: str = "",
        description: str = "",
        links: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        related_pages: Iterable[dict[str, Any]] | None = None,
        source_content: str = "",
        source_trust: str = "",
        provenance: Iterable[dict[str, Any] | str] | None = None,
        source_provenance: Iterable[dict[str, Any] | str] | None = None,
        source_id: str = "",
        approved_source: bool = False,
        approved_path: bool = False,
        approve_source: bool = False,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.ensure_structure()
        clean_source_path = str(source_path or "").strip()
        explicit_path_approval = bool(approved_source or approved_path or approve_source or approved)
        source: Path | None = None
        source_metadata: dict[str, Any] = {}
        source_body = ""
        if clean_source_path:
            source = self._validate_approved_source(clean_source_path, explicit_path_approval)
            source_metadata, source_body = _parse_document(source.read_text(encoding="utf-8", errors="ignore"))
        supplied_body = str(synthesis or source_content or content or "").strip()
        if not supplied_body and source is not None:
            supplied_body = source_body
        if not supplied_body:
            raise KnowledgeWikiError(
                "Ingestion requires supplied content or an explicitly approved source_path."
            )
        source_sensitivity = str(source_metadata.get("sensitivity") or "private").strip().casefold()
        if source_sensitivity not in VALID_SENSITIVITIES:
            source_sensitivity = "private"
        source_title = _clean_title(title or (source.stem if source is not None else "Supplied Source"))
        clean_trust = _clean_source_trust(
            source_trust or ("approved_path" if source is not None else "user_supplied")
        )
        if source is not None:
            source_ref = self._relative(source)
            source_kind = "approved_path"
        else:
            digest = hashlib.sha256(supplied_body.encode("utf-8")).hexdigest()[:16]
            source_ref = _SUPPLIED_SOURCE_PREFIX + digest
            source_kind = "supplied_content"
        source_provenance = [
            *(_as_provenance(provenance)),
            *(_as_provenance(source_provenance)),
            {"kind": source_kind, "ref": source_ref, "trust": clean_trust, "approved": source is not None},
        ]
        source_identity = _clean_page_id(source_id) or (
            f"knowledge:source:{_slug(source_ref if source is not None else source_title)}"
        )
        related = list(related_pages or [])
        related_titles = [_clean_title(str(item.get("title") or "")) for item in related if item.get("title")]
        source_result = self.upsert_page(
            title=source_title,
            page_type="source",
            content=supplied_body,
            description=description,
            sources=[source_ref],
            links=[*(links or []), *related_titles],
            tags=tags,
            status="draft",
            sensitivity=source_sensitivity,
            source_trust=clean_trust,
            provenance=source_provenance,
            page_id=source_identity,
        )

        compiled: list[dict[str, Any]] = []
        for page in related:
            page_sources = [*_as_list(page.get("sources")), source_ref]
            page_links = [*_as_list(page.get("links")), source_title]
            compiled.append(
                self.upsert_page(
                    title=str(page.get("title") or ""),
                    page_type=str(page.get("page_type") or page.get("type") or "concept"),
                    content=str(page.get("content") or page.get("body") or ""),
                    description=str(page.get("description") or ""),
                    sources=page_sources,
                    links=page_links,
                    tags=_as_list(page.get("tags")),
                    status=str(page.get("status") or "draft"),
                    sensitivity=str(page.get("sensitivity") or source_sensitivity),
                    source_trust=str(page.get("source_trust") or clean_trust),
                    provenance=_as_provenance(page.get("provenance")) + source_provenance,
                    page_id=str(page.get("page_id") or page.get("identity") or page.get("stable_id") or page.get("id") or ""),
                )
            )
        if source_result.get("updated") or any(item.get("updated") for item in compiled):
            self.append_log(
                "ingest",
                source_title,
                path=source_ref if source is not None else "",
                detail=f"Compiled one source page and {len(compiled)} related pages.",
            )
        return {"source": source_ref, "source_page": source_result, "related_pages": compiled, "source_trust": clean_trust}

    def query(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        self.ensure_structure()
        clean_limit = _clean_limit(limit)
        terms = _terms(query)
        if not terms:
            return {"query": query, "index_consulted": f"{self.wiki_folder}/index.md", "results": []}

        index_text = (self.wiki_root / "index.md").read_text(encoding="utf-8", errors="ignore")
        index_titles = {
            match.group(1).split("|")[-1].strip().casefold()
            for match in re.finditer(r"\[\[([^\]]+)\]\]", index_text)
            if terms.intersection(_terms(match.group(0)))
        }
        scored: list[tuple[float, dict[str, Any]]] = []
        for path in self._content_pages():
            text = path.read_text(encoding="utf-8", errors="ignore")
            metadata, body = _parse_document(text)
            title = str(metadata.get("title") or path.stem)
            description = str(metadata.get("description") or "")
            sensitivity = str(metadata.get("sensitivity") or "private")
            score = (
                4 * len(terms.intersection(_terms(title)))
                + 2 * len(terms.intersection(_terms(description)))
                + len(terms.intersection(_terms(body)))
                + (2 if title.casefold() in index_titles else 0)
            )
            if score <= 0:
                continue
            if sensitivity == "public":
                safe_title = title
                safe_description = description
            else:
                safe_title, _title_mapping = self.scrubber.scrub_regex(title)
                safe_description, _description_mapping = self.scrubber.scrub_regex(description)
            scored.append(
                (
                    float(score),
                    {
                        "ref": _page_ref(
                            self._relative(path),
                            str(metadata.get("id") or f"knowledge:{metadata.get('type', 'unknown')}:{_slug(path.stem)}"),
                        ),
                        "title": safe_title,
                        "type": str(metadata.get("type") or "unknown"),
                        "description": safe_description,
                        "sensitivity": sensitivity,
                        "status": str(metadata.get("status") or "draft"),
                        "updated": str(metadata.get("updated") or ""),
                        "score": float(score),
                    },
                )
            )
        results = [item for _score, item in sorted(scored, key=lambda pair: (-pair[0], pair[1]["title"]))[:clean_limit]]
        return {"query": query, "index_consulted": f"{self.wiki_folder}/index.md", "results": results}

    def read_page(self, page_ref: str) -> dict[str, Any]:
        self.ensure_structure()
        clean_ref = _clean_ref(page_ref)
        selected: tuple[Path, dict[str, Any], str] | None = None
        for path in self._content_pages():
            relative = self._relative(path)
            metadata, body = _parse_document(path.read_text(encoding="utf-8", errors="ignore"))
            page_id = str(metadata.get("id") or f"knowledge:{metadata.get('type', 'unknown')}:{_slug(path.stem)}")
            if _page_ref(relative, page_id) != clean_ref and _legacy_page_ref(relative) != clean_ref:
                continue
            selected = (path, metadata, body)
            break
        if selected is None:
            raise KnowledgeWikiError("Knowledge page reference was not found.")

        _path, metadata, body = selected
        return self._display_page(clean_ref, metadata, body)

    def _display_page(
        self,
        page_ref: str,
        metadata: dict[str, Any],
        body: str,
        *,
        version: int | None = None,
    ) -> dict[str, Any]:
        sensitivity = str(metadata.get("sensitivity") or "private")
        raw_title = str(metadata.get("title") or "Untitled")
        raw_description = str(metadata.get("description") or "")
        display_body = _display_wikilinks(body)
        if sensitivity == "public":
            safe_title, safe_description, safe_body = raw_title, raw_description, display_body
        else:
            safe_title, _title_mapping = self.scrubber.scrub_regex(raw_title)
            safe_description, _description_mapping = self.scrubber.scrub_regex(raw_description)
            safe_body, _body_mapping = self.scrubber.scrub_regex(display_body)
        sources = []
        for source in _as_list(metadata.get("sources")):
            source_label = source if _is_url(source) or _is_source_token(source) else Path(source).stem
            if sensitivity == "public":
                sources.append(source_label)
            else:
                safe_source, _source_mapping = self.scrubber.scrub_regex(source_label)
                sources.append(safe_source)
        provenance = _display_provenance(_as_provenance(metadata.get("provenance")), sensitivity, self.scrubber)
        raw_id = str(metadata.get("id") or "")
        if sensitivity == "public":
            safe_id = raw_id
        else:
            safe_id, _id_mapping = self.scrubber.scrub_regex(raw_id)
        return {
            "ref": page_ref,
            "id": safe_id,
            "title": safe_title,
            "type": str(metadata.get("type") or "unknown"),
            "description": safe_description,
            "sensitivity": sensitivity,
            "status": str(metadata.get("status") or "draft"),
            "updated": str(metadata.get("updated") or ""),
            "version": int(version if version is not None else metadata.get("version") or 0),
            "content": safe_body,
            "sources": sources,
            "source_count": int(metadata.get("source_count") or len(sources)),
            "source_trust": str(metadata.get("source_trust") or "unknown"),
            "provenance": provenance,
        }

    def version_history(self, page_ref: str) -> dict[str, Any]:
        """Return the immutable prior revisions for one page.

        History files remain private vault artifacts. This method intentionally
        returns metadata and opaque version refs, not raw historical text;
        callers can request a particular version with ``read_page_version``.
        """
        path, metadata, _body = self._page_for_ref(page_ref)
        history_dir = self._history_dir(path)
        versions: list[dict[str, Any]] = []
        if history_dir.exists():
            for history_path in sorted(history_dir.glob("*.md")):
                match = re.search(r"-v(\d+)\.md$", history_path.name)
                if not match:
                    continue
                versions.append(
                    {
                        "version": int(match.group(1)),
                        "ref": f"{_clean_ref(page_ref)}:v{int(match.group(1))}",
                    }
                )
        sensitivity = str(metadata.get("sensitivity") or "private")
        raw_title = str(metadata.get("title") or path.stem)
        raw_id = str(metadata.get("id") or "")
        if sensitivity == "public":
            safe_title, safe_id = raw_title, raw_id
        else:
            safe_title, _title_mapping = self.scrubber.scrub_regex(raw_title)
            safe_id, _id_mapping = self.scrubber.scrub_regex(raw_id)
        return {
            "ref": _clean_ref(page_ref),
            "id": safe_id,
            "title": safe_title,
            "current_version": int(metadata.get("version") or 0),
            "versions": versions,
        }

    def history(self, page_ref: str) -> dict[str, Any]:
        """Compatibility alias for :meth:`version_history`."""
        return self.version_history(page_ref)

    def read_page_version(self, page_ref: str, version: int) -> dict[str, Any]:
        path, current_metadata, _body = self._page_for_ref(page_ref)
        try:
            clean_version = int(version)
        except (TypeError, ValueError) as exc:
            raise KnowledgeWikiError("Page version must be an integer.") from exc
        if clean_version < 1 or clean_version >= int(current_metadata.get("version") or 0):
            raise KnowledgeWikiError("Requested page version is not available in history.")
        history_path = self._history_dir(path)
        matches = list(history_path.glob(f"*-v{clean_version}.md"))
        if not matches:
            raise KnowledgeWikiError("Requested page version is not available in history.")
        metadata, body = _parse_document(matches[0].read_text(encoding="utf-8", errors="ignore"))
        current_id = str(
            current_metadata.get("id")
            or f"knowledge:{current_metadata.get('type', 'unknown')}:{_slug(path.stem)}"
        )
        return self._display_page(
            _page_ref(self._relative(path), current_id),
            metadata,
            body,
            version=clean_version,
        )

    def rebuild_index(self) -> dict[str, Any]:
        self.ensure_structure()
        grouped: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for path in self._content_pages():
            metadata, _body = _parse_document(path.read_text(encoding="utf-8", errors="ignore"))
            grouped[str(metadata.get("type") or "unknown")].append((self._relative(path), metadata))

        lines = [
            "---",
            'type: "index"',
            f'updated: {json.dumps(_now())}',
            "---",
            "",
            "# Knowledge Index",
            "",
            "Read this page first. Use the one-line descriptions to choose a small set of pages before reading full notes.",
        ]
        for page_type in PAGE_FOLDERS:
            entries = sorted(grouped.get(page_type, []), key=lambda item: str(item[1].get("title") or "").casefold())
            lines.extend(["", f"## {page_type.title()} pages", ""])
            if not entries:
                lines.append("_No pages yet._")
                continue
            for relative, metadata in entries:
                title = str(metadata.get("title") or Path(relative).stem)
                link = relative[:-3] if relative.endswith(".md") else relative
                description = str(metadata.get("description") or "No description.").replace("\n", " ")
                lines.append(
                    f"- [[{link}|{title}]] - {description} "
                    f"(updated {str(metadata.get('updated') or '')[:10]}; {int(metadata.get('source_count') or 0)} sources)"
                )
        content = "\n".join(lines).rstrip() + "\n"
        path = self.wiki_root / "index.md"
        previous = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        if previous != content:
            _atomic_write(path, content)
        return {"path": self._relative(path), "page_count": sum(len(items) for items in grouped.values())}

    def update_overview(
        self,
        *,
        content: str,
        links: Iterable[str] | None = None,
        sources: Iterable[str] | None = None,
        source_trust: str = "",
        provenance: Iterable[dict[str, Any] | str] | None = None,
    ) -> dict[str, Any]:
        self.ensure_structure()
        clean_content = _clean_body(content, "Knowledge Overview")
        if not clean_content:
            raise KnowledgeWikiError("Knowledge overview content is required.")
        clean_links = _unique(_clean_title(item) for item in links or [] if str(item).strip())
        clean_sources = self._normalize_sources(sources or [])
        path = self.wiki_root / "overview.md"
        old_text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        old_metadata, _old_body = _parse_document(old_text)
        clean_trust = _clean_source_trust(
            source_trust or str(old_metadata.get("source_trust") or "maintained")
        )
        clean_provenance = _merge_provenance(
            _as_provenance(old_metadata.get("provenance")),
            _as_provenance(provenance),
            clean_sources,
            clean_trust,
        )
        version = int(old_metadata.get("version") or 0) + 1
        lines = [
            "---",
            'type: "overview"',
            f'updated: {json.dumps(_now())}',
            f"version: {version}",
            f"sources: {json.dumps(clean_sources, ensure_ascii=False)}",
            f"source_trust: {json.dumps(clean_trust)}",
            f"provenance: {json.dumps(clean_provenance, ensure_ascii=False)}",
            "---",
            "",
            "# Knowledge Overview",
            "",
            clean_content,
        ]
        if clean_links:
            lines.extend(["", "## Knowledge map", ""])
            lines.extend(f"- [[{link}]]" for link in clean_links)
        document = "\n".join(lines).rstrip() + "\n"
        if old_text and _without_volatile_metadata(old_text) == _without_volatile_metadata(document):
            return {"updated": False, "path": self._relative(path), "version": int(old_metadata.get("version") or 0)}
        if old_text and int(old_metadata.get("version") or 0) > 0:
            self._save_history(path, old_text, int(old_metadata.get("version") or 1))
        _atomic_write(path, document)
        self.append_log("overview", "Knowledge Overview", path=self._relative(path), detail=f"v{version}")
        return {"updated": True, "path": self._relative(path), "version": version}

    def lint(self, *, stale_days: int = 120, write_report: bool = True) -> dict[str, Any]:
        self.ensure_structure()
        self.rebuild_index()
        pages: list[tuple[Path, dict[str, Any], str]] = []
        title_paths: dict[str, list[str]] = defaultdict(list)
        target_names: dict[str, str] = {}
        for path in self._content_pages():
            metadata, body = _parse_document(path.read_text(encoding="utf-8", errors="ignore"))
            pages.append((path, metadata, body))
            title = str(metadata.get("title") or path.stem)
            title_paths[_normalized(title)].append(self._relative(path))
            target_names[_normalized(title)] = self._relative(path)
            target_names[_normalized(path.stem)] = self._relative(path)

        missing_fields: list[dict[str, Any]] = []
        broken_links: list[dict[str, str]] = []
        missing_sources: list[dict[str, str]] = []
        missing_provenance: list[str] = []
        invalid_source_trust: list[dict[str, str]] = []
        stale_pages: list[str] = []
        identity_paths: dict[str, list[str]] = defaultdict(list)
        inbound: Counter[str] = Counter()
        cutoff = datetime.now(UTC) - timedelta(days=max(0, int(stale_days)))

        for path, metadata, body in pages:
            relative = self._relative(path)
            missing = [field for field in REQUIRED_FIELDS if field not in metadata]
            if missing:
                missing_fields.append({"path": relative, "fields": missing})
            page_id = str(metadata.get("id") or "").strip()
            if page_id:
                identity_paths[page_id.casefold()].append(relative)
            if not _as_provenance(metadata.get("provenance")):
                missing_provenance.append(relative)
            try:
                _clean_source_trust(str(metadata.get("source_trust") or "unknown"))
            except KnowledgeWikiError:
                invalid_source_trust.append(
                    {"path": relative, "source_trust": str(metadata.get("source_trust") or "")}
                )
            updated = _parse_date(str(metadata.get("updated") or ""))
            if updated is not None and updated <= cutoff and not bool(metadata.get("pinned")):
                stale_pages.append(relative)
            for source in _as_list(metadata.get("sources")):
                if _is_url(source) or _is_source_token(source):
                    continue
                source_path = (self.vault_root / source).resolve()
                if not source_path.is_relative_to(self.vault_root) or not source_path.exists():
                    missing_sources.append({"path": relative, "source": source})
            for link in _WIKILINK_RE.findall(body):
                clean_link = link.strip()
                if not clean_link:
                    continue
                if "/" in clean_link:
                    target = (self.vault_root / f"{clean_link}.md").resolve()
                    if not target.exists():
                        target = (self.vault_root / clean_link).resolve()
                    if target.is_relative_to(self.vault_root) and target.exists():
                        if target.is_relative_to(self.wiki_root):
                            inbound[self._relative(target)] += 1
                        continue
                resolved = target_names.get(_normalized(clean_link))
                if resolved:
                    inbound[resolved] += 1
                else:
                    broken_links.append({"path": relative, "link": clean_link})

        duplicates = [paths for paths in title_paths.values() if len(paths) > 1]
        duplicate_identities = [paths for paths in identity_paths.values() if len(paths) > 1]
        orphan_pages = [self._relative(path) for path, _metadata, _body in pages if inbound[self._relative(path)] == 0]
        overview = self.wiki_root / "overview.md"
        newest_page_mtime = max((path.stat().st_mtime for path, _metadata, _body in pages), default=0)
        overview_drift = bool(newest_page_mtime and overview.exists() and overview.stat().st_mtime < newest_page_mtime)
        errors = (
            len(missing_fields)
            + len(missing_sources)
            + len(missing_provenance)
            + len(invalid_source_trust)
        )
        warnings = (
            len(broken_links)
            + len(duplicates)
            + len(duplicate_identities)
            + len(orphan_pages)
            + len(stale_pages)
            + int(overview_drift)
        )
        health = "red" if errors else "yellow" if warnings else "green"
        result = {
            "health": health,
            "page_count": len(pages),
            "missing_fields": missing_fields,
            "missing_sources": missing_sources,
            "missing_provenance": missing_provenance,
            "invalid_source_trust": invalid_source_trust,
            "broken_links": broken_links,
            "duplicate_titles": duplicates,
            "duplicate_identities": duplicate_identities,
            "orphan_pages": orphan_pages,
            "stale_pages": stale_pages,
            "overview_drift": overview_drift,
        }
        if write_report:
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            report_path = self.wiki_root / "lint" / f"{stamp}.md"
            _atomic_write(report_path, _render_lint_report(result))
            result["report_path"] = self._relative(report_path)
            self.append_log("lint", health.upper(), path=self._relative(report_path), detail=f"{errors} errors, {warnings} warnings")
        return result

    def append_log(self, action: str, title: str, *, path: str = "", detail: str = "") -> None:
        self.ensure_structure()
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"## [{timestamp}] {action.strip().casefold()} | {_clean_title(title)}"]
        if path:
            link = path[:-3] if path.endswith(".md") else path
            lines.append(f"- Path: [[{link}]]")
        if detail:
            lines.append(f"- Detail: {detail.strip()}")
        log_path = self.wiki_root / "log.md"
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n" + "\n".join(lines) + "\n")

    def _content_pages(self) -> list[Path]:
        paths: list[Path] = []
        for folder in PAGE_FOLDERS.values():
            paths.extend(sorted((self.wiki_root / folder).glob("*.md")))
        return paths

    def _find_page_by_id(self, page_id: str) -> Path | None:
        matches: list[Path] = []
        for path in self._content_pages():
            metadata, _body = _parse_document(path.read_text(encoding="utf-8", errors="ignore"))
            if str(metadata.get("id") or "").strip() == page_id:
                matches.append(path)
        if len(matches) > 1:
            raise KnowledgeWikiError(f"Stable page identity {page_id!r} is duplicated in the wiki.")
        return matches[0] if matches else None

    def _page_for_ref(self, page_ref: str) -> tuple[Path, dict[str, Any], str]:
        clean_ref = _clean_ref(page_ref)
        for path in self._content_pages():
            relative = self._relative(path)
            metadata, body = _parse_document(path.read_text(encoding="utf-8", errors="ignore"))
            page_id = str(metadata.get("id") or f"knowledge:{metadata.get('type', 'unknown')}:{_slug(path.stem)}")
            if _page_ref(relative, page_id) == clean_ref or _legacy_page_ref(relative) == clean_ref:
                return path, metadata, body
        raise KnowledgeWikiError("Knowledge page reference was not found.")

    def _normalize_sources(self, sources: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for source in sources:
            clean = str(source or "").strip().replace("\\", "/")
            if not clean:
                continue
            if _is_url(clean):
                normalized.append(clean)
                continue
            if _is_source_token(clean):
                normalized.append(clean)
                continue
            target = (self.vault_root / clean.strip("/")).resolve()
            if not target.is_relative_to(self.vault_root):
                raise KnowledgeWikiError("Knowledge source escapes the Obsidian vault.")
            if not target.exists():
                raise KnowledgeWikiError(f"Knowledge source does not exist: {clean}")
            normalized.append(self._relative(target))
        return _unique(normalized)

    def _validate_approved_source(self, source_path: str, approved: bool) -> Path:
        clean = str(source_path or "").strip().replace("\\", "/").strip("/")
        if not clean:
            raise KnowledgeWikiError("An explicit source_path is required when approving path ingestion.")
        if not approved:
            raise KnowledgeWikiError(
                "Source path ingestion is opt-in; pass approved_source=true. Library/ is never read automatically."
            )
        target = (self.vault_root / clean).resolve()
        if not target.is_relative_to(self.vault_root):
            raise KnowledgeWikiError("Knowledge source must stay inside the Obsidian vault.")
        if not target.is_file():
            raise KnowledgeWikiError(f"Approved source does not exist: {clean}")
        return target

    def _validate_library_source(self, source_path: str) -> Path:
        """Backward-compatible validation that always requires approval.

        Kept private for older integrations; callers should use
        :meth:`_validate_approved_source` through ``ingest_source``.
        """
        return self._validate_approved_source(source_path, approved=False)

    def _history_dir(self, page_path: Path) -> Path:
        relative = page_path.resolve().relative_to(self.wiki_root)
        return self.wiki_root / ".history" / relative.with_suffix("")

    def _save_history(self, page_path: Path, text: str, version: int) -> None:
        history_dir = self._history_dir(page_path)
        history_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        _atomic_write(history_dir / f"{stamp}-v{version}.md", text)

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.vault_root).as_posix()


def _render_page(metadata: dict[str, Any], body: str, links: list[str]) -> str:
    lines = ["---"]
    for key in REQUIRED_FIELDS:
        lines.append(f"{key}: {json.dumps(metadata[key], ensure_ascii=False)}")
    lines.extend(["---", "", f"# {metadata['title']}", "", body.strip()])
    if links:
        lines.extend(["", "## Connections", ""])
        lines.extend(f"- [[{link}]]" for link in links)
    if metadata["sources"]:
        lines.extend(["", "## Sources", ""])
        for source in metadata["sources"]:
            if _is_url(source):
                lines.append(f"- [{source}]({source})")
            elif _is_source_token(source):
                lines.append(f"- `{source}`")
            else:
                link = source[:-3] if source.endswith(".md") else source
                lines.append(f"- [[{link}]]")
    return "\n".join(lines).rstrip() + "\n"


def _parse_document(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    metadata: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        try:
            metadata[key] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            metadata[key] = raw.strip('"\'')
    return metadata, parts[2].strip()


def _render_lint_report(result: dict[str, Any]) -> str:
    timestamp = _now()
    lines = [
        "---",
        'type: "lint-report"',
        f'created: {json.dumps(timestamp)}',
        f'health: {json.dumps(result["health"])}',
        "---",
        "",
        f"# Wiki Lint Report - {timestamp[:10]}",
        "",
        "## Summary",
        "",
        f"Health: **{str(result['health']).upper()}**. Checked {result['page_count']} content pages.",
    ]
    sections = (
        ("Schema integrity", result["missing_fields"]),
        ("Missing sources", result["missing_sources"]),
        ("Missing provenance", result.get("missing_provenance", [])),
        ("Invalid source trust", result.get("invalid_source_trust", [])),
        ("Broken links", result["broken_links"]),
        ("Duplicate titles", result["duplicate_titles"]),
        ("Duplicate identities", result.get("duplicate_identities", [])),
        ("Orphan pages", result["orphan_pages"]),
        ("Stale pages", result["stale_pages"]),
    )
    for heading, items in sections:
        lines.extend(["", f"## {heading}", ""])
        if not items:
            lines.append("- None")
        else:
            lines.extend(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in items)
    lines.extend(["", "## Overview drift", "", f"- {'Yes' if result['overview_drift'] else 'No'}"])
    lines.extend(["", "## Safety", "", "No pages were deleted or rewritten by this lint pass."])
    return "\n".join(lines).rstrip() + "\n"


def _schema_document(wiki_folder: str) -> str:
    return f"""---
type: \"schema\"
version: 1
updated: \"{_now()}\"
---

# Vellum Knowledge Wiki Schema

## Layers

1. `Library/` contains raw sources whose accuracy is not assumed. The wiki agent never reads them automatically and never edits them.
2. `{wiki_folder}/` contains agent-maintained synthesis. Vellum owns these pages; the user reviews them in Obsidian.
3. This schema defines how Vellum ingests, queries, and lints the wiki.

## Page types

- `source`: synthesis of one immutable source.
- `entity`: a person, organization, product, team, place, or other named thing.
- `concept`: an idea, method, pattern, or principle.
- `topic`: a broader subject that connects entities and concepts.
- `project`: compiled knowledge about a project; active working state remains in `Projects/`.
- `analysis`: a comparison, answer, or synthesis worth preserving.

## Required frontmatter

Every content page requires `id`, `type`, `title`, `description`, `sensitivity`, `status`, `created`, `updated`, `version`, `sources`, `source_count`, `source_trust`, `provenance`, and `tags`. Sensitivity is explicitly `public` or `private`; missing values are treated as private. `id` is the stable identity used to derive opaque API references.

## Ingest workflow

1. Supply complete content, or pass one explicit `source_path` together with `approved_source=true`. A `Library/` path without approval is rejected.
2. Record the source trust (`user_supplied` or `approved_path`) and provenance in every affected page.
3. Read `index.md` and search existing pages before creating anything.
4. Create or revise the source page.
5. Revise every affected entity, concept, topic, project, or analysis page with the new synthesis.
6. Preserve citations and add Obsidian wikilinks between related pages.
7. Rebuild `index.md` and append the operation to `log.md`.

Prefer revising an existing page when the new information changes an attribute or synthesis. Create a new page only for a distinct entity or concept that deserves inbound links.

## Query workflow

Read `index.md` first, choose a small set of relevant pages, then read those pages and their cited sources. Valuable new analyses may be filed back into the wiki after user approval.

## Lint workflow

Check required metadata, missing sources, broken links, duplicate titles, orphan pages, stale pages, and overview drift. Lint never deletes or rewrites content pages. It writes a report under `lint/` and records the pass in `log.md`.
"""


def _empty_index_document() -> str:
    return """---
type: \"index\"
updated: \"never\"
---

# Knowledge Index

Read this page first. The index is rebuilt whenever the wiki changes.
"""


def _overview_document() -> str:
    return f"""---
type: \"overview\"
updated: \"{_now()}\"
source_trust: \"maintained\"
provenance: [{{\"kind\": \"maintained_page\", \"trust\": \"maintained\"}}]
---

# Knowledge Overview

The wiki is ready. This page will become the high-level synthesis of the knowledge graph as sources are compiled.
"""


def _log_document() -> str:
    return """---
type: \"log\"
format: \"## [YYYY-MM-DD HH:MM UTC] action | title\"
---

# Knowledge Wiki Log
"""


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _atomic_move(source: Path, target: Path) -> None:
    """Move a Knowledge page without ever crossing the wiki root."""
    source_root = source.resolve().parents
    target_root = target.resolve().parents
    if not any(parent.name == WIKI_FOLDER for parent in source_root) or not any(
        parent.name == WIKI_FOLDER for parent in target_root
    ):
        raise KnowledgeWikiError("Knowledge page moves must stay inside Knowledge/.")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)


def _safe_segment(value: str) -> str:
    clean = str(value or "").strip().strip("/\\")
    if not clean or clean in {".", ".."} or "/" in clean or "\\" in clean:
        raise KnowledgeWikiError("Invalid wiki folder name.")
    return clean


def _clean_title(value: str) -> str:
    clean = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).strip()
    if not clean:
        raise KnowledgeWikiError("Knowledge page title is required.")
    if len(clean) > 160:
        raise KnowledgeWikiError("Knowledge page title is too long.")
    return clean


def _clean_page_id(value: str) -> str:
    clean = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).strip()
    if not clean:
        return ""
    if len(clean) > 200 or any(char in clean for char in "/\\\x00"):
        raise KnowledgeWikiError("Stable page identity must be a short path-free value.")
    return clean


def _clean_source_trust(value: str) -> str:
    clean = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    clean = _SOURCE_TRUST_ALIASES.get(clean, clean)
    if clean not in VALID_SOURCE_TRUST:
        raise KnowledgeWikiError(
            f"Unsupported source trust {value!r}; use maintained, user_supplied, approved_path, trusted, untrusted, unknown, or mixed."
        )
    return clean


def _clean_ref(value: str) -> str:
    clean = str(value or "").strip().casefold()
    if not re.fullmatch(r"kw-[0-9a-f]{16}", clean):
        raise KnowledgeWikiError("Knowledge page reference must be an opaque kw- reference returned by query.")
    return clean


def _clean_limit(value: int) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise KnowledgeWikiError("Query limit must be an integer between 1 and 25.") from exc
    if clean < 1 or clean > 25:
        raise KnowledgeWikiError("Query limit must be an integer between 1 and 25.")
    return clean


def _clean_body(value: str, title: str) -> str:
    body = str(value or "").strip()
    lines = body.splitlines()
    if lines and lines[0].strip().casefold() == f"# {title}".casefold():
        body = "\n".join(lines[1:]).strip()
    return body


def _description(value: str) -> str:
    clean = " ".join(re.sub(r"[`*_#>]", "", str(value or "")).split())
    if not clean:
        return "No description yet."
    sentence = re.split(r"(?<=[.!?])\s+", clean, maxsplit=1)[0]
    return sentence[:240].rstrip()


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    if clean:
        return clean[:100].rstrip("-")
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return "page-" + digest


def _terms(value: str) -> set[str]:
    return {term.casefold() for term in re.findall(r"[A-Za-z0-9]+", str(value or "")) if len(term) > 2}


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    if value is None or value == "":
        return []
    return [str(value)]


def _as_provenance(value: Any) -> list[dict[str, Any]]:
    if value is None or value == "":
        return []
    items: Iterable[Any]
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            clean: dict[str, Any] = {}
            for key, raw in item.items():
                key_text = str(key).strip()
                if not key_text:
                    continue
                if isinstance(raw, (str, int, float, bool)) or raw is None:
                    clean[key_text] = raw
                elif isinstance(raw, (list, tuple)):
                    clean[key_text] = [str(entry) for entry in raw]
                else:
                    clean[key_text] = str(raw)
            if clean:
                result.append(clean)
        elif str(item).strip():
            result.append({"kind": "reference", "ref": str(item).strip()})
    return result


def _merge_provenance(
    previous: Iterable[dict[str, Any]],
    incoming: Iterable[dict[str, Any]],
    sources: Iterable[str],
    source_trust: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*previous, *incoming]:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(dict(item))
    refs = {
        str(item.get("ref") or item.get("source") or "").casefold()
        for item in result
        if isinstance(item, dict)
    }
    for source in sources:
        if source.casefold() in refs:
            continue
        result.append({"kind": "reference", "ref": source, "trust": source_trust})
        refs.add(source.casefold())
    if not result:
        result.append({"kind": "maintained_page", "trust": source_trust})
    return result


def _is_url(value: str) -> bool:
    return str(value or "").startswith(("https://", "http://"))


def _is_source_token(value: str) -> bool:
    clean = str(value or "").casefold()
    return clean.startswith((_SUPPLIED_SOURCE_PREFIX, "approved-source:"))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _page_ref(relative_path: str, page_id: str = "") -> str:
    stable_key = str(page_id or relative_path)
    return "kw-" + hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]


def _legacy_page_ref(relative_path: str) -> str:
    return "kw-" + hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def _display_wikilinks(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "|" in inner:
            return inner.rsplit("|", 1)[-1].strip()
        target = inner.split("#", 1)[0].strip()
        return Path(target).stem.replace("-", " ")

    return re.sub(r"\[\[([^\]]+)\]\]", replace, text)


def _without_volatile_metadata(text: str) -> str:
    clean = re.sub(r"^updated:.*$", "updated:", text, flags=re.MULTILINE)
    return re.sub(r"^version:.*$", "version:", clean, flags=re.MULTILINE)


def _display_provenance(
    provenance: Iterable[dict[str, Any]], sensitivity: str, scrubber: PrivacyScrubber
) -> list[dict[str, Any]]:
    if sensitivity == "public":
        return [dict(item) for item in provenance]
    displayed: list[dict[str, Any]] = []
    for item in provenance:
        safe: dict[str, Any] = {}
        for key, value in item.items():
            if isinstance(value, str) and not _is_url(value):
                scrubbed, _mapping = scrubber.scrub_regex(value)
                safe[key] = scrubbed
            elif isinstance(value, list):
                safe[key] = [
                    scrubber.scrub_regex(str(entry))[0] if not _is_url(str(entry)) else str(entry)
                    for entry in value
                ]
            else:
                safe[key] = value
        displayed.append(safe)
    return displayed
