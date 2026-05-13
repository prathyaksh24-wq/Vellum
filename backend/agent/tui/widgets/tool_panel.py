"""Collapsible tool-call panel for the message list."""

from __future__ import annotations

import json
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from agent.tui.widgets.spinner import BrailSpinner


def _short_args(args: Any) -> str:
    if args is None:
        return ""
    if isinstance(args, dict):
        try:
            text = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
        except (TypeError, ValueError):
            text = str(args)
    else:
        text = str(args)
    text = text.replace("\n", " ").strip()
    if len(text) > 120:
        text = text[:117] + "…"
    return text


class ToolCallPanel(Static):
    """Bordered, animated panel showing a tool invocation and its outcome."""

    def __init__(self, name: str, args: Any = None) -> None:
        super().__init__(classes="tool-panel tool-panel-running")
        self._name = name
        self._args = _short_args(args)
        self._collapsed = True
        self._summary = "reading…"
        self._citations: list[dict] = []
        self._success: bool | None = None
        self._spinner: BrailSpinner | None = None

    def compose(self) -> ComposeResult:
        self._spinner = BrailSpinner(id="tool-spinner")
        with Horizontal(classes="tool-panel-header"):
            yield Static(f"[#716d68]┌─[/] [#ece6db]{self._name}[/]  ", id="tool-name")
            yield self._spinner
            yield Static(f"  [#716d68]─[/]", id="tool-trailing")
        if self._args:
            yield Static(f"[#716d68]│[/]  [#aaa49b]{self._args}[/]", id="tool-args")
        yield Static(f"[#716d68]│[/]  [#aaa49b]↳ {self._summary}[/]", id="tool-summary")
        yield Static("[#716d68]└─[/]", id="tool-foot")

    def set_result(self, summary: str, citations: list[dict] | None = None, success: bool = True) -> None:
        self._summary = summary
        self._citations = list(citations or [])
        self._success = success
        if self._spinner is not None:
            self._spinner.done(success=success)
        self.remove_class("tool-panel-running")
        self.add_class("tool-panel-done" if success else "tool-panel-error")
        try:
            self.query_one("#tool-summary", Static).update(
                f"[#716d68]│[/]  [#aaa49b]↳ {self._summary}[/]"
            )
        except Exception:
            pass
