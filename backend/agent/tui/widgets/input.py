from __future__ import annotations

from textual.widgets import Input


class VellumInput(Input):
    """Single-line composer."""

    DEFAULT_CSS = """
    VellumInput {
        background: #0c0c0e;
    }
    """

    def __init__(self) -> None:
        super().__init__(placeholder="ask.", id="composer")
