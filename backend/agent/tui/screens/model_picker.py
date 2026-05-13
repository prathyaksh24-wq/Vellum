"""Modal screen for picking a provider/model."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from agent.llm.providers import ModelEntry, get_provider_registry


def _format_context(n: int) -> str:
    if n >= 1_000_000:
        return f"{n // 1_000_000}M"
    if n >= 1000:
        return f"{n // 1000}k"
    return str(n)


class ModelPickerModal(ModalScreen[ModelEntry | None]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("up,k", "move(-1)", "up", show=False),
        Binding("down,j", "move(1)", "down", show=False),
        Binding("enter", "pick", "pick", show=False),
        Binding("/", "focus_filter", "filter", show=False),
    ]

    cursor = reactive(0)
    filter_text = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self.registry = get_provider_registry()
        self._entries: list[ModelEntry] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="model-picker-root"):
            yield Static("[italic #ece6db]pick a model[/]", id="picker-title")
            yield Static("", id="picker-list")
            yield Input(placeholder="/ filter", id="picker-filter")
            yield Static("[#716d68]↑/↓ j/k nav   ↵ pick   / filter   esc cancel[/]", id="picker-help")

    def on_mount(self) -> None:
        active = self.registry.current_model()
        self._refresh_entries()
        for index, entry in enumerate(self._entries):
            if entry.id == active.id:
                self.cursor = index
                break
        self._render_list()

    def _refresh_entries(self) -> None:
        normalized = self.filter_text.strip().casefold()
        results: list[ModelEntry] = []
        for entry in self.registry.list_models():
            if not normalized:
                results.append(entry)
                continue
            haystack = f"{entry.label} {entry.provider} {entry.id}".casefold()
            if normalized in haystack:
                results.append(entry)
        self._entries = results
        if self.cursor >= len(self._entries):
            self.cursor = max(0, len(self._entries) - 1)

    def _render_list(self) -> None:
        lines: list[str] = []
        current_provider: str | None = None
        active_id = self.registry.current_model().id
        for index, entry in enumerate(self._entries):
            if entry.provider != current_provider:
                if current_provider is not None:
                    lines.append("")
                lines.append(f"[#716d68]{entry.provider}[/]")
                current_provider = entry.provider
            is_active = entry.id == active_id
            is_cursor = index == self.cursor
            marker = "[#d97746]▸[/]" if is_cursor else (" " if not is_active else "[#d97746]·[/]")
            label_color = "#ece6db" if is_cursor else ("#d97746" if is_active else "#aaa49b")
            label = f"[{label_color}]{entry.label:<20}[/]"
            ctx = f"[#716d68]{_format_context(entry.context):>5}[/]"
            lines.append(f"  {marker} {label} {ctx}")
        if not lines:
            lines.append("[#716d68]no matches[/]")
        self.query_one("#picker-list", Static).update("\n".join(lines))

    def watch_cursor(self, _value: int) -> None:
        self._render_list()

    def watch_filter_text(self, _value: str) -> None:
        self._refresh_entries()
        self._render_list()

    def action_move(self, delta: int) -> None:
        if not self._entries:
            return
        self.cursor = (self.cursor + delta) % len(self._entries)

    def action_pick(self) -> None:
        if not self._entries:
            self.dismiss(None)
            return
        entry = self._entries[self.cursor]
        self.registry.set_active(entry.id)
        self.dismiss(entry)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_focus_filter(self) -> None:
        self.query_one("#picker-filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_pick()
