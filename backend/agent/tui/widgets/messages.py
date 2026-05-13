from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from agent.tui.widgets.markdown_message import MarkdownMessage
from agent.tui.widgets.tool_panel import ToolCallPanel


def _now_label() -> str:
    return "now"


class MessageList(VerticalScroll):
    """Scrollable transcript with markdown rendering and tool-call panels."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._assistant: MarkdownMessage | None = None
        self._assistant_text: str = ""
        self._tool_panels: dict[str, ToolCallPanel] = {}

    def on_mount(self) -> None:
        self.show_landing()

    def show_landing(self) -> None:
        self.remove_children()
        self._assistant = None
        self._assistant_text = ""
        self._tool_panels.clear()
        self.mount(
            Static(
                "[italic #ece6db]vellum[/]\n\n"
                "[italic #aaa49b]What are you reading.[/]\n\n"
                "[italic #716d68]what did I write about patience[/]\n"
                "[italic #716d68]find the note about the river[/]\n"
                "[italic #716d68]what should I remember from yesterday[/]",
                classes="landing",
            )
        )

    def clear_landing(self) -> None:
        if len(self.children) == 1 and "landing" in self.children[0].classes:
            self.remove_children()

    def add_user_message(self, text: str) -> None:
        self.clear_landing()
        self.mount(
            Static(
                f"[#716d68]you . {_now_label()}[/]\n\n[#aaa49b]{text}[/]",
                classes="message message-user",
            )
        )
        self.scroll_end(animate=False)

    def add_tool_panel(self, key: str, name: str, args: Any = None) -> ToolCallPanel:
        """Mount a running tool-call panel and return it."""
        self.clear_landing()
        panel = ToolCallPanel(name=name, args=args)
        self._tool_panels[key] = panel
        self.mount(panel)
        self.scroll_end(animate=False)
        return panel

    def complete_tool_panel(
        self,
        key: str,
        summary: str,
        citations: list[dict] | None = None,
        success: bool = True,
    ) -> None:
        panel = self._tool_panels.get(key)
        if panel is not None:
            panel.set_result(summary, citations=citations, success=success)

    def begin_assistant_message(self, source: str = "from your library") -> None:
        self.clear_landing()
        self._assistant = MarkdownMessage(source=source)
        self._assistant_text = ""
        self.mount(self._assistant)
        self.scroll_end(animate=False)

    def append_assistant_token(self, text: str) -> None:
        if self._assistant is None:
            self.begin_assistant_message()
        self._assistant_text += text
        assert self._assistant is not None
        self._assistant.append_token(text)
        self.scroll_end(animate=False)

    def finish_assistant_message(
        self,
        tool_names: list[str] | None = None,
        citations: list[dict] | None = None,
    ) -> None:
        if self._assistant is None:
            return
        self._assistant.finalize(citations=citations)
        self.scroll_end(animate=False)

    def latest_assistant_response(self) -> str:
        return self._assistant_text.strip()

    def add_vellum_note(self, text: str, source: str = "local") -> None:
        self.clear_landing()
        self._assistant_text = text
        self.mount(
            Static(
                f"[#716d68]vellum . {source}[/]\n\n[#ece6db]{text}[/]",
                classes="message message-vellum",
            )
        )
        self.scroll_end(animate=False)
