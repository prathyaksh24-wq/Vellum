"""Handler for the /project chat command family.

Used by both the web command parser (api.py) and the TUI command router."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent.memory.project_context import (
    InvalidSlug,
    ProjectContext,
    validate_slug,
)
from agent.memory.templates import load_template


class InvalidCommand(Exception):
    """User-visible error: malformed args, missing project, etc."""


@dataclass
class CommandResult:
    message: str
    side_effects: list[str]


def _list_projects(ctx: ProjectContext) -> list[str]:
    root = ctx.vault_root / "Projects"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "vellum.md").exists())


def _now_stamp() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def _today() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def handle_project_command(
    ctx: ProjectContext,
    thread_id: str,
    args: list[str],
) -> CommandResult:
    if not args:
        active = ctx._state.get_active_project(thread_id)
        projects = _list_projects(ctx)
        active_line = f"active: {active}" if active else "active: (none)"
        listing = "\n".join(f"- {p}" for p in projects) or "(no projects yet)"
        return CommandResult(
            message=f"{active_line}\nprojects:\n{listing}",
            side_effects=[],
        )

    if args[0] == "--clear":
        ctx._state.set_active_project(thread_id, None)
        return CommandResult(message="active project cleared", side_effects=[])

    if args[0] == "create":
        if len(args) != 2:
            raise InvalidCommand("usage: /project create <slug>")
        slug = args[1]
        try:
            validate_slug(slug)
        except InvalidSlug as exc:
            raise InvalidCommand(str(exc)) from exc

        proj = ctx.vault_root / "Projects" / slug
        if proj.exists():
            raise InvalidCommand(f"project {slug!r} already exists")

        (proj / "notes").mkdir(parents=True)

        charter = load_template("vellum").replace("<slug>", slug)
        charter = charter.replace("DD/MM/YYYY", _today())
        (proj / "vellum.md").write_text(charter, encoding="utf-8")

        hot = load_template("hot").replace("DD/MM/YYYY HH:MM", _now_stamp())
        (proj / "hot.md").write_text(hot, encoding="utf-8")

        (proj / "log.md").write_text("", encoding="utf-8")

        ctx._state.set_active_project(thread_id, slug)
        return CommandResult(
            message=f"created project {slug!r} and made it active",
            side_effects=[f"created Projects/{slug}/"],
        )

    # /project <slug>
    slug = args[0]
    try:
        validate_slug(slug)
    except InvalidSlug as exc:
        raise InvalidCommand(str(exc)) from exc

    if not (ctx.vault_root / "Projects" / slug / "vellum.md").exists():
        raise InvalidCommand(f"project {slug!r} not found")

    ctx._state.set_active_project(thread_id, slug)
    return CommandResult(message=f"active project: {slug}", side_effects=[])
