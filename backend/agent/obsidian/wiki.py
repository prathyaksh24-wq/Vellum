"""Agent-maintained Obsidian knowledge wiki.

The wiki is a compiled knowledge layer over immutable source notes. Library/
contains source material, Knowledge/ contains maintained synthesis, and the
existing memory/search systems remain implementation details and indexes.
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
    "tags",
)
VALID_STATUSES = {"draft", "verified", "needs_review", "superseded"}
VALID_SENSITIVITIES = {"public", "private"}
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


class KnowledgeWikiError(ValueError):
    """Raised when a wiki operation violates its schema or path policy."""


class KnowledgeWiki:
    """Safe, deterministic file operations for Vellum's Obsidian wiki."""

    def __init__(self, vault_root: str | Path, wiki_folder: str = WIKI_FOLDER) -> None:
        self.vault_root = Path(vault_root).expanduser().resolve()
        self.wiki_folder = _safe_segment(wiki_folder)
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
            "inbox_count": len(list((self.wiki_root / "inbox").glob("*.md"))),
            "lint_report_count": len(list((self.wiki_root / "lint").glob("*.md"))),
        }

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
        clean_content = _clean_body(content, clean_title)
        if not clean_content:
            raise KnowledgeWikiError("Knowledge page content is required.")

        clean_sources = self._normalize_sources(sources or [])
        clean_links = _unique(_clean_title(item) for item in links or [] if str(item).strip())
        clean_tags = _unique(_slug(item) for item in tags or [] if str(item).strip())
        path = self.wiki_root / PAGE_FOLDERS[clean_type] / f"{_slug(clean_title)}.md"
        old_metadata: dict[str, Any] = {}
        old_text = ""
        if path.exists():
            old_text = path.read_text(encoding="utf-8", errors="ignore")
            old_metadata, _old_body = _parse_document(old_text)

        now = _now()
        metadata = {
            "id": str(old_metadata.get("id") or f"knowledge:{clean_type}:{_slug(clean_title)}"),
            "type": clean_type,
            "title": clean_title,
            "description": _description(description or clean_content),
            "sensitivity": clean_sensitivity,
            "status": clean_status,
            "created": str(old_metadata.get("created") or now),
            "updated": now,
            "version": int(old_metadata.get("version") or 0) + 1,
            "sources": _unique([*_as_list(old_metadata.get("sources")), *clean_sources]),
            "source_count": 0,
            "tags": _unique([*_as_list(old_metadata.get("tags")), *clean_tags]),
        }
        metadata["source_count"] = len(metadata["sources"])
        document = _render_page(metadata, clean_content, clean_links)
        if old_text and _without_volatile_metadata(old_text) == _without_volatile_metadata(document):
            return {"created": False, "updated": False, "path": self._relative(path), "page": metadata}

        if old_text and int(old_metadata.get("version") or 0) > 0:
            self._save_history(path, old_text, int(old_metadata.get("version") or 1))
        _atomic_write(path, document)
        self.rebuild_index()
        action = "update" if old_text else "ingest"
        self.append_log(action, clean_title, path=self._relative(path), detail=f"{clean_type} v{metadata['version']}")
        return {"created": not bool(old_text), "updated": True, "path": self._relative(path), "page": metadata}

    def ingest_source(
        self,
        *,
        source_path: str,
        title: str,
        synthesis: str,
        description: str = "",
        links: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        related_pages: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        source = self._validate_library_source(source_path)
        source_metadata, _source_body = _parse_document(source.read_text(encoding="utf-8", errors="ignore"))
        source_sensitivity = str(source_metadata.get("sensitivity") or "private").strip().casefold()
        if source_sensitivity not in VALID_SENSITIVITIES:
            source_sensitivity = "private"
        source_title = _clean_title(title or source.stem)
        related = list(related_pages or [])
        related_titles = [_clean_title(str(item.get("title") or "")) for item in related if item.get("title")]
        source_result = self.upsert_page(
            title=source_title,
            page_type="source",
            content=synthesis,
            description=description,
            sources=[self._relative(source)],
            links=[*(links or []), *related_titles],
            tags=tags,
            status="draft",
            sensitivity=source_sensitivity,
        )

        compiled: list[dict[str, Any]] = []
        for page in related:
            page_sources = [*_as_list(page.get("sources")), self._relative(source)]
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
                )
            )
        self.append_log(
            "ingest",
            source_title,
            path=self._relative(source),
            detail=f"Compiled one source page and {len(compiled)} related pages.",
        )
        return {"source": self._relative(source), "source_page": source_result, "related_pages": compiled}

    def query(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        self.ensure_structure()
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
                        "ref": _page_ref(self._relative(path)),
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
        results = [item for _score, item in sorted(scored, key=lambda pair: (-pair[0], pair[1]["title"]))[: max(1, int(limit))]]
        return {"query": query, "index_consulted": f"{self.wiki_folder}/index.md", "results": results}

    def read_page(self, page_ref: str) -> dict[str, Any]:
        self.ensure_structure()
        clean_ref = str(page_ref or "").strip()
        selected: tuple[Path, dict[str, Any], str] | None = None
        for path in self._content_pages():
            relative = self._relative(path)
            if _page_ref(relative) != clean_ref:
                continue
            metadata, body = _parse_document(path.read_text(encoding="utf-8", errors="ignore"))
            selected = (path, metadata, body)
            break
        if selected is None:
            raise KnowledgeWikiError("Knowledge page reference was not found.")

        _path, metadata, body = selected
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
            sources.append(source if _is_url(source) else Path(source).stem)
        return {
            "ref": clean_ref,
            "title": safe_title,
            "type": str(metadata.get("type") or "unknown"),
            "description": safe_description,
            "sensitivity": sensitivity,
            "status": str(metadata.get("status") or "draft"),
            "updated": str(metadata.get("updated") or ""),
            "content": safe_body,
            "sources": sources,
        }

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
        version = int(old_metadata.get("version") or 0) + 1
        lines = [
            "---",
            'type: "overview"',
            f'updated: {json.dumps(_now())}',
            f"version: {version}",
            f"sources: {json.dumps(clean_sources, ensure_ascii=False)}",
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
        stale_pages: list[str] = []
        inbound: Counter[str] = Counter()
        cutoff = datetime.now(UTC) - timedelta(days=max(0, int(stale_days)))

        for path, metadata, body in pages:
            relative = self._relative(path)
            missing = [field for field in REQUIRED_FIELDS if field not in metadata]
            if missing:
                missing_fields.append({"path": relative, "fields": missing})
            updated = _parse_date(str(metadata.get("updated") or ""))
            if updated is not None and updated <= cutoff and not bool(metadata.get("pinned")):
                stale_pages.append(relative)
            for source in _as_list(metadata.get("sources")):
                if _is_url(source):
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
        orphan_pages = [self._relative(path) for path, _metadata, _body in pages if inbound[self._relative(path)] == 0]
        overview = self.wiki_root / "overview.md"
        newest_page_mtime = max((path.stat().st_mtime for path, _metadata, _body in pages), default=0)
        overview_drift = bool(newest_page_mtime and overview.exists() and overview.stat().st_mtime < newest_page_mtime)
        errors = len(missing_fields) + len(missing_sources)
        warnings = len(broken_links) + len(duplicates) + len(orphan_pages) + len(stale_pages) + int(overview_drift)
        health = "red" if errors else "yellow" if warnings else "green"
        result = {
            "health": health,
            "page_count": len(pages),
            "missing_fields": missing_fields,
            "missing_sources": missing_sources,
            "broken_links": broken_links,
            "duplicate_titles": duplicates,
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

    def _normalize_sources(self, sources: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for source in sources:
            clean = str(source or "").strip().replace("\\", "/")
            if not clean:
                continue
            if _is_url(clean):
                normalized.append(clean)
                continue
            target = (self.vault_root / clean.strip("/")).resolve()
            if not target.is_relative_to(self.vault_root):
                raise KnowledgeWikiError("Knowledge source escapes the Obsidian vault.")
            if not target.exists():
                raise KnowledgeWikiError(f"Knowledge source does not exist: {clean}")
            normalized.append(self._relative(target))
        return _unique(normalized)

    def _validate_library_source(self, source_path: str) -> Path:
        clean = str(source_path or "").strip().replace("\\", "/").strip("/")
        target = (self.vault_root / clean).resolve()
        library_root = (self.vault_root / "Library").resolve()
        if not target.is_relative_to(library_root):
            raise KnowledgeWikiError("Wiki ingestion accepts immutable sources from Library/ only.")
        if not target.is_file():
            raise KnowledgeWikiError(f"Library source does not exist: {clean}")
        return target

    def _save_history(self, page_path: Path, text: str, version: int) -> None:
        relative = page_path.relative_to(self.wiki_root)
        history_dir = self.wiki_root / ".history" / relative.with_suffix("")
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
        ("Broken links", result["broken_links"]),
        ("Duplicate titles", result["duplicate_titles"]),
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

1. `Library/` contains immutable raw sources. The wiki agent may read but never edit these files.
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

Every content page requires `id`, `type`, `title`, `description`, `sensitivity`, `status`, `created`, `updated`, `version`, `sources`, `source_count`, and `tags`. Sensitivity is explicitly `public` or `private`; missing values are treated as private.

## Ingest workflow

1. Read the source from `Library/`; never modify it.
2. Read `index.md` and search existing pages before creating anything.
3. Create or revise the source page.
4. Revise every affected entity, concept, topic, project, or analysis page with the new synthesis.
5. Preserve citations and add Obsidian wikilinks between related pages.
6. Rebuild `index.md` and append the operation to `log.md`.

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


def _is_url(value: str) -> bool:
    return str(value or "").startswith(("https://", "http://"))


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


def _page_ref(relative_path: str) -> str:
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
