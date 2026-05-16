import pytest

from agent.memory.templates import load_template, TEMPLATE_FILES


@pytest.mark.parametrize("name", list(TEMPLATE_FILES.keys()))
def test_template_loads_and_has_frontmatter(name: str) -> None:
    text = load_template(name)
    assert text.startswith("---\n"), f"{name} must start with YAML frontmatter"
    # Frontmatter must close before any markdown header
    closing = text.find("\n---\n", 4)
    assert closing > 0, f"{name} frontmatter must close with ---"


def test_unknown_template_raises() -> None:
    with pytest.raises(KeyError):
        load_template("nonexistent")


def test_vellum_template_contains_slug_placeholder() -> None:
    assert "<slug>" in load_template("vellum")


def test_hot_template_has_managed_marker() -> None:
    assert "vellum-managed:" in load_template("hot")
