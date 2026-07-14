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
    if clean.startswith(("skillsmp/", "clawhub/", "official/")):
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
    return SkillIntakeTarget("author", clean)


def validate_skill_learn_input(value: str) -> str:
    """Reject malformed source values while retaining explicit procedure learning."""
    clean = value.strip()
    if clean.startswith(("skills-sh/", "skills.sh/", "skillsmp/", "clawhub/", "official/")):
        return clean
    parsed = urlparse(clean)
    if parsed.scheme or "://" in clean:
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(character.isspace() for character in clean)
        ):
            raise ValueError("Enter a valid public HTTP(S) skill URL")
        return clean
    if len(clean) < 12 or not any(character.isspace() for character in clean):
        raise ValueError("Enter a valid public skill URL or a meaningful procedure")
    return clean
