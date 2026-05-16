"""Per-thread identity loader: assembles Meta + active project files into a
single <PROTECTED> block prepended to the agent system prompt each turn."""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

from agent.memory.sessions import ThreadStateStore, SESSIONS_DB

logger = logging.getLogger(__name__)


SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
_DOUBLE_HYPHEN = re.compile(r"--")


class ProjectContextError(Exception):
    """Base class for ProjectContext errors."""


class InvalidSlug(ProjectContextError):
    """Slug failed validation."""


class ProjectNotFound(ProjectContextError):
    """Project folder or vellum.md missing."""


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
