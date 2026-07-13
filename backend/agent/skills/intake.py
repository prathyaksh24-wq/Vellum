from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class SkillIntakeTarget:
    kind: str
    value: str
    source: str | None = None


def resolve_skill_intake(value: str) -> SkillIntakeTarget:
    clean = value.strip()
    if not clean:
        raise ValueError("learn source is required")
    if clean.startswith(("skills-sh/", "skills.sh/")):
        return SkillIntakeTarget("marketplace", "skills-sh/" + clean.split("/", 1)[1].strip("/"), "skills-sh")
    if clean.startswith(("skillsmp/", "clawhub/", "github/", "official/")):
        return SkillIntakeTarget("marketplace", clean, clean.split("/", 1)[0])
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return SkillIntakeTarget("author", clean)
    host = parsed.hostname.casefold().removeprefix("www.")
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if host == "skills.sh" and len(parts) >= 3:
        return SkillIntakeTarget("marketplace", "skills-sh/" + "/".join(parts[:3]), "skills-sh")
    if host in {"clawhub.ai", "www.clawhub.ai"} and parts:
        slug = parts[-1]
        return SkillIntakeTarget("marketplace", f"clawhub/{slug}", "clawhub")
    if host == "github.com" and len(parts) >= 5 and parts[2] in {"tree", "blob"}:
        return SkillIntakeTarget("marketplace", f"github/{parts[0]}/{parts[1]}/" + "/".join(parts[4:]), "github")
    return SkillIntakeTarget("author", clean)
