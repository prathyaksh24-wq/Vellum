from __future__ import annotations

from textual.widgets import Static


def bar(value: int, maximum: int, width: int = 18) -> str:
    if maximum <= 0 or value <= 0:
        return "." * width
    filled = max(1, round((value / maximum) * width))
    return "#" * min(width, filled) + "." * max(0, width - filled)


class Heatmap(Static):
    """Simple ember-compatible text heatmap."""

    def render_rows(self, rows: list[tuple[str, int]], width: int = 18) -> None:
        maximum = max((value for _label, value in rows), default=0)
        lines = [f"{label:<24} {bar(value, maximum, width)} {value:>8,}" for label, value in rows]
        self.update("\n".join(lines) if lines else "[#716d68]No entries.[/]")
