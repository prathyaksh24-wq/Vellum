from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, UTC
import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.screen import Screen
from textual.widgets import Static

from agent.tui.widgets.heatmap import bar


AUDIT_LOG = Path("data/memory/audit_log.jsonl")


@dataclass
class UsageSummary:
    total_tokens: int = 0
    turns: int = 0
    models: Counter[str] = field(default_factory=Counter)
    hours: list[list[int]] = field(default_factory=lambda: [[0 for _ in range(24)] for _ in range(7)])


def _entry_tokens(entry: dict[str, Any]) -> int:
    usage = entry.get("usage")
    if isinstance(usage, dict):
        explicit = usage.get("total_tokens")
        if isinstance(explicit, int):
            return explicit
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if isinstance(prompt, int) or isinstance(completion, int):
            return int(prompt or 0) + int(completion or 0)
    return int(entry.get("prompt_tokens_approx") or 0) + int(entry.get("response_tokens_approx") or 0)


def _entry_datetime(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_usage_summary(path: Path = AUDIT_LOG) -> UsageSummary:
    summary = UsageSummary()
    if not path.exists():
        return summary

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            tokens = _entry_tokens(entry)
            model = str(entry.get("model") or "unknown")
            summary.total_tokens += tokens
            summary.turns += 1
            summary.models[model] += tokens
            ts = _entry_datetime(entry)
            if ts is not None:
                local_ts = ts.astimezone(UTC)
                summary.hours[local_ts.weekday()][local_ts.hour] += tokens
    return summary


def _money(tokens: int) -> str:
    # Approximate display until model-specific pricing is added.
    return f"${tokens * 0.0000025:.2f}"


def _hour_cell(value: int, maximum: int) -> str:
    if value <= 0 or maximum <= 0:
        return "."
    ratio = value / maximum
    if ratio >= 0.80:
        return "#"
    if ratio >= 0.55:
        return "▓"
    if ratio >= 0.30:
        return "▒"
    return "░"


class LedgerScreen(Screen[None]):
    BINDINGS = [
        ("escape", "app.pop_screen", "back"),
        ("d", "cycle_period", "period"),
        ("r", "refresh", "refresh"),
        ("m", "expand_models", "models"),
        ("t", "expand_threads", "threads"),
        ("h", "expand_hours", "hours"),
        ("s", "suggestions", "suggestions"),
        ("e", "export", "export"),
    ]

    def __init__(self, audit_log: Path = AUDIT_LOG) -> None:
        super().__init__()
        self.audit_log = audit_log
        self.periods = ["today", "7 days", "30 days", "all time"]
        self.period_index = 0

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("", id="ledger-header"),
            Static("--------------------------------------------------------------------------------", id="ledger-rule"),
            Grid(
                Static("", id="period-panel"),
                Static("", id="models-panel"),
                Static("", id="threads-panel"),
                Static("", id="hours-panel"),
                id="ledger-grid",
            ),
            Static("d period   m models   t threads   h hours   s suggestions   r refresh   esc back", id="ledger-footer"),
            id="ledger-root",
        )

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        summary = load_usage_summary(self.audit_log)
        period = self.periods[self.period_index]
        self.query_one("#ledger-header", Static).update(f"[italic #ece6db]vellum[/]  [#d97746]o[/]  [italic #716d68]ledger[/]{period:>62}")
        self.query_one("#period-panel", Static).update(
            "[italic #ece6db]period[/]\n\n"
            f"Today: {summary.total_tokens:,} tokens across {summary.turns} turns. {_money(summary.total_tokens)}.\n"
            f"This week: {summary.total_tokens:,} tokens. {_money(summary.total_tokens)}.\n"
            f"This month: {summary.total_tokens:,} tokens. {_money(summary.total_tokens)}.\n"
            f"All time: {summary.total_tokens:,} tokens. {_money(summary.total_tokens)}."
        )

        model_rows = summary.models.most_common(8)
        max_model = max((value for _name, value in model_rows), default=0)
        model_lines = ["[italic #ece6db]models[/]\n"]
        for name, value in model_rows or [("no entries", 0)]:
            model_lines.append(f"{name:<28} {bar(value, max_model)} {value:>8,}")
        self.query_one("#models-panel", Static).update("\n".join(model_lines))

        self.query_one("#threads-panel", Static).update(
            "[italic #ece6db]threads[/]\n\n"
            "i.   current thread         " + bar(summary.total_tokens, summary.total_tokens) + f" {summary.total_tokens:>8,}\n"
            "ii.  earlier                " + bar(0, summary.total_tokens) + "        0"
        )

        maximum = max((value for row in summary.hours for value in row), default=0)
        labels = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        hour_lines = ["[italic #ece6db]hours[/]\n"]
        for label, row in zip(labels, summary.hours, strict=True):
            cells = "".join(_hour_cell(value, maximum) for value in row)
            hour_lines.append(f"{label} {cells}")
        self.query_one("#hours-panel", Static).update("\n".join(hour_lines))

    def action_cycle_period(self) -> None:
        self.period_index = (self.period_index + 1) % len(self.periods)
        self.refresh_data()

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_expand_models(self) -> None:
        self.notify("models expanded view pending", timeout=2)

    def action_expand_threads(self) -> None:
        self.notify("threads expanded view pending", timeout=2)

    def action_expand_hours(self) -> None:
        self.notify("hours expanded view pending", timeout=2)

    def action_suggestions(self) -> None:
        self.query_one("#ledger-grid", Grid).display = False
        self.query_one("#period-panel", Static).update(
            "[italic #ece6db]suggestions[/]\n\n"
            "[#aaa49b]Usage is too sparse for reliable suggestions.[/]\n\n"
            "                  .\n\n"
            "[#aaa49b]Keep the ledger local until pricing by model is available.[/]\n\n"
            "                  .\n\n"
            "[#aaa49b]No suppressed suggestions.[/]\n\n"
            "                  .\n\n"
            "[#aaa49b]Refresh after a longer session.[/]"
        )

    def action_export(self) -> None:
        exports = Path("data/exports")
        exports.mkdir(parents=True, exist_ok=True)
        target = exports / "ledger-summary.csv"
        summary = load_usage_summary(self.audit_log)
        rows = ["model,tokens"] + [f"{model},{tokens}" for model, tokens in summary.models.most_common()]
        target.write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.notify(f"Exported. {target}", timeout=2)
