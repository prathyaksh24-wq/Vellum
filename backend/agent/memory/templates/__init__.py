"""Starter templates for Meta/ and Projects/ files."""

from importlib import resources
from typing import Final

TEMPLATE_FILES: Final[dict[str, str]] = {
    "profile": "profile.md.tpl",
    "goals": "goals.md.tpl",
    "principles": "principles.md.tpl",
    "vellum": "vellum.md.tpl",
    "hot": "hot.md.tpl",
}


def load_template(name: str) -> str:
    """Return the raw text of a named template. Raises KeyError if unknown."""
    filename = TEMPLATE_FILES[name]
    return resources.files(__package__).joinpath(filename).read_text(encoding="utf-8")
