from __future__ import annotations

from datetime import datetime, UTC

from textual.widgets import Static
from textual.containers import VerticalScroll


def _now_label() -> str:
    return "now"


class MessageList(VerticalScroll):
    """Scrollable transcript with book-like messages."""

    assistant_message_id: str | None = None
    assistant_text: str = ""

    def on_mount(self) -> None:
        self.show_landing()

    def show_landing(self) -> None:
        self.remove_children()
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

    def begin_assistant_message(self, source: str = "from your library") -> None:
        self.clear_landing()
        stamp = int(datetime.now(UTC).timestamp() * 1000)
        self.assistant_message_id = f"assistant-{stamp}"
        self.assistant_text = ""
        self.mount(
            Static(
                f"[#716d68]vellum . {source}[/]\n\n[#ece6db][/]\n\n[#d97746]>[/]",
                id=self.assistant_message_id,
                classes="message message-vellum",
            )
        )
        self.scroll_end(animate=False)

    def append_assistant_token(self, text: str) -> None:
        if self.assistant_message_id is None:
            self.begin_assistant_message()
        self.assistant_text += text
        widget = self.query_one(f"#{self.assistant_message_id}", Static)
        drawn = "-" * min(72, max(1, len(self.assistant_text) // 4))
        widget.update(
            "[#716d68]vellum . from your library[/]\n\n"
            f"[#ece6db]{self.assistant_text}[/]\n\n"
            f"[#d97746]{drawn}>[/]"
        )
        self.scroll_end(animate=False)

    def finish_assistant_message(self, tool_names: list[str] | None = None) -> None:
        if self.assistant_message_id is None:
            return
        widget = self.query_one(f"#{self.assistant_message_id}", Static)
        tools = ""
        if tool_names:
            rendered = ", ".join(dict.fromkeys(tool_names))
            tools = f"\n\n[#716d68]i. {rendered}[/]"
        widget.update(
            "[#716d68]vellum . from your library[/]\n\n"
            f"[#ece6db]{self.assistant_text or 'No response.'}[/]"
            f"{tools}"
        )
        self.scroll_end(animate=False)

    def latest_assistant_response(self) -> str:
        return self.assistant_text.strip()

    def add_vellum_note(self, text: str, source: str = "local") -> None:
        self.clear_landing()
        self.assistant_text = text
        self.mount(
            Static(
                f"[#716d68]vellum . {source}[/]\n\n[#ece6db]{text}[/]",
                classes="message message-vellum",
            )
        )
        self.scroll_end(animate=False)
