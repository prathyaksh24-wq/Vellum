"""Per-thread identity loader: assembles Meta + active project files into a
single <PROTECTED> block prepended to the agent system prompt each turn."""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

from agent.memory.sessions import ThreadStateStore, SESSIONS_DB
from agent.privacy.scrubber import PrivacyScrubber

logger = logging.getLogger(__name__)


SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
_DOUBLE_HYPHEN = re.compile(r"--")


class ProjectContextError(Exception):
    """Base class for ProjectContext errors."""


class InvalidSlug(ProjectContextError):
    """Slug failed validation."""


class ProjectNotFound(ProjectContextError):
    """Project folder or vellum.md missing."""


# Per-file token budgets (approximate; 1 token ~= 0.75 words).
TOKEN_BUDGETS: dict[str, int] = {
    "profile.md": 600,
    "goals.md": 400,
    "principles.md": 400,
    "vellum.md": 800,
    "hot.md": 200,
}


def _approx_token_count(text: str) -> int:
    # Rough heuristic; avoids a tokenizer dependency for a non-critical budget.
    return max(1, len(text.split()) * 4 // 3)


def _truncate_to_budget(text: str, budget: int) -> str:
    if _approx_token_count(text) <= budget:
        return text
    words = text.split()
    keep = max(1, budget * 3 // 4)
    return " ".join(words[:keep]) + "\n[truncated]"


def _budget_for(filename: str) -> int:
    return TOKEN_BUDGETS.get(filename, 1000)


def validate_slug(slug: str) -> None:
    if not SLUG_RE.match(slug or "") or _DOUBLE_HYPHEN.search(slug or "") or (slug or "").endswith("-"):
        raise InvalidSlug(
            f"invalid slug {slug!r}: must match {SLUG_RE.pattern}, no '--', no trailing '-'"
        )


@dataclass
class ProjectContext:
    vault_root: Path
    sessions_db: Path = SESSIONS_DB

    def __post_init__(self) -> None:
        self.vault_root = Path(self.vault_root)
        self.sessions_db = Path(self.sessions_db)
        self._state = ThreadStateStore(sessions_db=self.sessions_db)
        self._cache: dict = {}
        self._cache_lock = RLock()

    # ---- file readers ----

    def _read_file(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("project_context: failed to read %s: %s", path, exc)
            return ""

    def _read_meta(self) -> str:
        meta = self.vault_root / "Meta"
        if not meta.exists():
            return ""
        parts: list[str] = []
        for name in ("profile.md", "goals.md", "principles.md"):
            body = self._read_file(meta / name)
            if body:
                parts.append(f"## {name}\n{body}")
        return "\n\n".join(parts)

    def _read_project(self, slug: str) -> str:
        validate_slug(slug)
        proj = self.vault_root / "Projects" / slug
        charter = proj / "vellum.md"
        if not charter.exists():
            raise ProjectNotFound(slug)
        parts: list[str] = [f"## vellum.md\n{self._read_file(charter)}"]
        hot = self._read_file(proj / "hot.md")
        if hot:
            parts.append(f"## hot.md\n{hot}")
        return "\n\n".join(parts)

    def _cache_key(self, thread_id: str):
        files: list[tuple[str, float]] = []
        meta_root = self.vault_root / "Meta"
        for name in ("profile.md", "goals.md", "principles.md"):
            p = meta_root / name
            files.append((str(p), p.stat().st_mtime if p.exists() else -1.0))
        slug = self._state.get_active_project(thread_id)
        if slug:
            proj_root = self.vault_root / "Projects" / slug
            for name in ("vellum.md", "hot.md"):
                p = proj_root / name
                files.append((str(p), p.stat().st_mtime if p.exists() else -1.0))
        return (thread_id, frozenset(files))

    def build(self, thread_id: str) -> str:
        key = self._cache_key(thread_id)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        result = self._build_uncached(thread_id)
        with self._cache_lock:
            if len(self._cache) >= 32:
                # FIFO eviction (insertion-ordered dict)
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = result
        return result

    def _build_uncached(self, thread_id: str) -> str:
        """Return the IDENTITY block for this thread, ready to prepend to
        the system prompt. Empty string when Meta/ is absent."""
        meta_root = self.vault_root / "Meta"
        if not meta_root.exists():
            return ""

        parts: list[str] = []

        for name in ("profile.md", "goals.md", "principles.md"):
            body = self._read_file(meta_root / name)
            if not body:
                continue
            body = _truncate_to_budget(body, _budget_for(name))
            parts.append(f"## {name}\n{body}")

        slug = self._state.get_active_project(thread_id)
        if slug:
            try:
                proj_root = self.vault_root / "Projects" / slug
                charter = self._read_file(proj_root / "vellum.md")
                if not charter:
                    raise ProjectNotFound(slug)
                charter = _truncate_to_budget(charter, _budget_for("vellum.md"))
                parts.append(f"## vellum.md\n{charter}")
                hot = self._read_file(proj_root / "hot.md")
                if hot:
                    hot = _truncate_to_budget(hot, _budget_for("hot.md"))
                    parts.append(f"## hot.md\n{hot}")
            except ProjectNotFound:
                logger.warning("project_context: active project %r missing; clearing", slug)
                self._state.set_active_project(thread_id, None)

        if not parts:
            return ""

        raw = "\n\n".join(parts)

        try:
            scrubber = PrivacyScrubber()
            scrubbed, _replacements = scrubber.scrub(raw)
        except Exception as exc:
            logger.error("project_context: scrubber failed: %s", exc)
            return ""

        return f"<PROTECTED>\n{scrubbed}\n</PROTECTED>"
