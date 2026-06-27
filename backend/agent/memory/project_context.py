"""Per-thread identity loader: assembles Meta + active project files into a
single <PROTECTED> block prepended to the agent system prompt each turn."""

from __future__ import annotations

import hashlib
import os
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
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


VELLUM_MANAGED_RE = re.compile(r"<!--\s*vellum-managed:\s*([0-9a-f]+)\s*-->", re.IGNORECASE)


def _default_summarizer(turn_summaries: list[str]) -> str:
    """Placeholder summarizer; real call to fast model wired up in Task 8.

    Deterministic concatenation lets tests/CLI run without an LLM call."""
    if not turn_summaries:
        return ""
    bullets = "\n".join(f"- {s}" for s in turn_summaries[-5:])
    return f"**Recent activity:**\n{bullets}"


def validate_slug(slug: str) -> None:
    if not SLUG_RE.match(slug or "") or _DOUBLE_HYPHEN.search(slug or "") or (slug or "").endswith("-"):
        raise InvalidSlug(
            f"invalid slug {slug!r}: must match {SLUG_RE.pattern}, no '--', no trailing '-'"
        )


@dataclass
class ProjectContext:
    vault_root: Path
    sessions_db: Path = SESSIONS_DB
    summarizer: object = None  # Callable[[list[str]], str]

    def __post_init__(self) -> None:
        self.vault_root = Path(self.vault_root)
        self.sessions_db = Path(self.sessions_db)
        self._state = ThreadStateStore(sessions_db=self.sessions_db)
        self._cache: dict = {}
        self._cache_lock = RLock()
        self._recent_summaries: dict[str, list[str]] = {}
        if self.summarizer is None:
            self.summarizer = _default_summarizer

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

    @staticmethod
    def _now_stamp() -> str:
        return datetime.now().strftime("%d/%m/%Y %H:%M")

    def tick(
        self,
        thread_id: str,
        turn_summary: str,
        *,
        turn_ref: str | None = None,
        source: str = "session",
    ) -> None:
        slug = self._state.get_active_project(thread_id)
        if not slug:
            return
        proj = self.vault_root / "Projects" / slug
        if not (proj / "vellum.md").exists():
            return

        line = f"- {self._now_stamp()} · [{source}] · {turn_summary} · turn={turn_ref or thread_id}\n"
        with open(proj / "log.md", "a", encoding="utf-8") as fh:
            fh.write(line)

        self._recent_summaries.setdefault(thread_id, []).append(turn_summary)

        count = self._state.bump_turns(thread_id)
        n = int(os.environ.get("HOT_REWRITE_EVERY_N_TURNS", "5"))
        if count < n:
            return

        self._rewrite_hot(proj, thread_id)
        self._state.reset_turns(thread_id)
        self._recent_summaries[thread_id] = []

    @staticmethod
    def _extract_managed_body(content: str) -> tuple[str, str | None]:
        m = VELLUM_MANAGED_RE.search(content)
        if not m:
            return content, None
        body = content[: m.start()].rstrip()
        return body, m.group(1)

    def _rewrite_hot(self, proj: Path, thread_id: str) -> None:
        hot_path = proj / "hot.md"
        existing = self._read_file(hot_path)
        body, recorded_sha = self._extract_managed_body(existing)
        current_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

        summarizer = self.summarizer or _default_summarizer
        summaries = self._recent_summaries.get(thread_id, [])
        # If in-memory summaries were lost across a process restart, fall back
        # to the tail of log.md so the rewrite still has material to compress.
        if not summaries:
            try:
                log_text = (proj / "log.md").read_text(encoding="utf-8")
                tail = [ln for ln in log_text.splitlines() if ln.strip()][-5:]
                summaries = []
                for ln in tail:
                    parts = ln.split("·", 2)
                    summaries.append(parts[2].strip() if len(parts) >= 3 else ln)
            except OSError:
                summaries = []
        new_body = summarizer(summaries)

        user_edited = (recorded_sha is None) or (recorded_sha != current_sha)

        if user_edited and existing.strip():
            stamp = self._now_stamp()
            appended = (
                f"{existing.rstrip()}\n\n## Hot (vellum proposed, {stamp})\n{new_body}\n"
            )
            hot_path.write_text(appended, encoding="utf-8")
            return

        # Fresh full rewrite. The sha must hash exactly the same string that
        # _extract_managed_body will return on the next read - i.e. everything
        # before the marker, rstripped. Otherwise the second rewrite would
        # falsely classify a Vellum-written file as user-edited.
        stamp = self._now_stamp()
        pre_marker = (
            f"---\ntype: project-hot\nupdated: {stamp}\n---\n"
            f"# Hot\n\n{new_body}\n\n"
        )
        new_sha = hashlib.sha256(pre_marker.rstrip().encode("utf-8")).hexdigest()
        full = f"{pre_marker}<!-- vellum-managed: {new_sha} -->\n"
        hot_path.write_text(full, encoding="utf-8")


def build_fast_summarizer():
    """Returns a Callable[[list[str]], str] that calls the fast model via OpenRouter
    to compress recent activity into a <=200-token Hot snapshot.

    Imported lazily so dev/test paths that do not have OPENROUTER_API_KEY still work."""
    from agent.config import get_settings
    from agent.graph.agent import build_llm

    settings = get_settings()
    llm = build_llm(settings.fast_model)

    def _summarize(turn_summaries: list[str]) -> str:
        if not turn_summaries:
            return ""
        joined = "\n".join(f"- {s}" for s in turn_summaries[-10:])
        prompt = (
            "Compress these recent activity notes from a project session into a "
            "<=200 token 'Hot' snapshot using the exact 4-line shape: "
            "Last touched / Open threads / Last decision / Next. "
            "Be concrete. No preamble.\n\nNotes:\n" + joined
        )
        response = llm.invoke(prompt)
        return getattr(response, "content", str(response))

    return _summarize
