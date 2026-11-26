"""Recognise pasted skill-install commands and install into Vellum instead.

Commands such as ``npx skills add owner/repo --skill name`` or ``clawhub install
slug`` install into another agent's folder (Claude Code, Codex). When the user asks
Vellum to run one, Vellum installs the same skill with its own installer, into its
own skills folder (``.skills/packages/<category>/<name>``).
"""

from __future__ import annotations

import re
import shlex
from urllib.parse import urlparse

_RUNNERS = {"npx", "bunx", "pnpx", "yarn", "pnpm", "bun"}
_GITHUB_TREE = re.compile(r"^/([^/]+)/([^/]+)/(?:tree|blob)/[^/]+/(.+?)(?:/SKILL\.md)?/?$")


class SkillInstallCommandError(ValueError):
    pass


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command.strip(), posix=True)
    except ValueError:
        return command.split()


def _strip_runner(tokens: list[str]) -> list[str]:
    while tokens and (tokens[0].casefold() in _RUNNERS or tokens[0] in {"dlx", "-y", "--yes", "exec"}):
        tokens = tokens[1:]
    return tokens


def _option(tokens: list[str], *names: str) -> str:
    for index, token in enumerate(tokens):
        for name in names:
            if token == name and index + 1 < len(tokens):
                return tokens[index + 1]
            if token.startswith(name + "="):
                return token.split("=", 1)[1]
    return ""


def skill_install_identifier(command: str) -> str | None:
    """The Vellum skill identifier a pasted install command refers to, or None.

    Raises SkillInstallCommandError when the command is a skill install Vellum can
    see but cannot resolve to one skill (for example a repository with no skill named).
    """
    tokens = _strip_runner(_tokens(command))
    if len(tokens) < 3:
        return None
    tool, verb = tokens[0].casefold(), tokens[1].casefold()
    tool = tool.split("@", 1)[0]
    if tool == "clawhub" and verb == "install":
        return f"clawhub/{tokens[2].strip('/')}"
    if tool not in {"skills", "skills.sh"} or verb not in {"add", "install"}:
        return None
    source = tokens[2]
    skill = _option(tokens, "--skill", "-s")
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        if host == "github.com":
            tree = _GITHUB_TREE.match(parsed.path)
            if tree:
                return f"github/{tree.group(1)}/{tree.group(2)}/{tree.group(3)}"
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2:
                source = f"{parts[0]}/{parts[1].removesuffix('.git')}"
        elif host == "skills.sh":
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 3:
                return "skills-sh/" + "/".join(parts[:3])
            if len(parts) == 2:
                source = "/".join(parts)
    if "@" in source and not skill:
        source, skill = source.split("@", 1)
    pieces = [piece for piece in source.split("/") if piece]
    if len(pieces) >= 3 and not skill:
        return "skills-sh/" + "/".join(pieces[:3])
    if len(pieces) == 2 and skill:
        return f"skills-sh/{pieces[0]}/{pieces[1]}/{skill}"
    raise SkillInstallCommandError(
        "This install command names a repository but not one skill. Add --skill <name> "
        "(or paste the skill's own link) so Vellum knows which skill to install.")


def install_into_vellum(identifier: str) -> dict:
    """Fetch, scan and install the skill into Vellum's own skills folder."""
    from agent.tools import skill_hub

    staged = skill_hub._stage_bundle("hub_install", identifier, category="community", force=True)
    applied = skill_hub._mutations().approve(staged["id"])
    if applied.get("ok") is False:
        raise SkillInstallCommandError(str(applied.get("error") or "The skill could not be installed."))
    return applied
