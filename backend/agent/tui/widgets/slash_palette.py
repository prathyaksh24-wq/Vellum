from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from agent.tui.slash_commands import SlashCommand, filter_commands


class SlashCommandPalette(Static):
    """Inline slash command menu similar to Claude Code/Codex."""

    selected_index = reactive(0)

    def __init__(self) -> None:
        super().__init__("", id="slash-palette")
        self.commands: list[SlashCommand] = []

    def show_for(self, query: str) -> None:
        self.commands = filter_commands(query)
        if self.selected_index >= len(self.commands):
            self.selected_index = 0
        self.display = bool(self.commands)
        self.render_palette()

    def hide(self) -> None:
        self.display = False
        self.commands = []
        self.selected_index = 0
        self.update("")

    def move_selection(self, delta: int) -> None:
        if not self.commands:
            return
        self.selected_index = (self.selected_index + delta) % len(self.commands)
        self.render_palette()

    def selected_command(self) -> SlashCommand | None:
        if not self.commands:
            return None
        return self.commands[self.selected_index]

    def render_palette(self) -> None:
        if not self.commands:
            self.update("[#716d68]No commands.[/]")
            return
        lines = ["[#716d68]commands[/]"]
        for index, command in enumerate(self.commands[:8]):
            marker = "[#d97746]>[/]" if index == self.selected_index else " "
            alias = f" [#716d68]{', '.join(command.aliases)}[/]" if command.aliases else ""
            lines.append(f"{marker} [#ece6db]{command.name:<10}[/] [#aaa49b]{command.description}[/]{alias}")
        self.update("\n".join(lines))
