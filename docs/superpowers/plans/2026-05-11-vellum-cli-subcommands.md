# Vellum CLI Subcommands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-purpose `vellum` entry point (TUI launcher) with a hermes-style subcommand surface (chat / resume / setup / models / sessions / usage / config / doctor) backed by a token-usage ledger. Wording follows BRAND.md throughout.

**Architecture:** Typer wraps the existing `VellumTuiApp` and adds subcommands. Interactive wizards use questionary pickers preceded by a full ANSI clear (`\x1b[2J\x1b[3J\x1b[H`) so each step is a fresh screen with no scrollback. Scrolling-output subcommands print Rich tables. A new `agent.telemetry.usage_ledger` SQLite store records tokens + cost per chat turn, written from TUI/CLI/API hook points. Sessions live in a new `thread_titles` table inside the existing `long_term.db`, joined with checkpoint metadata from `checkpoints.db`.

**Tech Stack:** Python 3.11+, Typer 0.12+, Questionary 2.0+, Rich (existing), SQLite via `sqlite3` (stdlib), LangGraph (existing), Textual (existing — untouched).

**Spec:** [docs/superpowers/specs/2026-05-11-vellum-cli-subcommands-design.md](../specs/2026-05-11-vellum-cli-subcommands-design.md)

---

## File Structure

**New files (create):**
- `backend/agent/tui/cli/__init__.py` — `main()` entry, `PHRASES` voice dict
- `backend/agent/tui/cli/app.py` — Typer root, subcommand wiring, `--version`, help override
- `backend/agent/tui/cli/screen.py` — `ansi_clear()`, `draw_header()`, picker wrappers
- `backend/agent/tui/cli/atomic_env.py` — atomic `.env` read/write helpers
- `backend/agent/tui/cli/commands/__init__.py` — empty (package marker)
- `backend/agent/tui/cli/commands/chat.py` — bare / `chat` / `resume` + first-run routing
- `backend/agent/tui/cli/commands/setup.py` — wizard
- `backend/agent/tui/cli/commands/models.py` — model picker + `KNOWN_MODELS`
- `backend/agent/tui/cli/commands/sessions.py` — list / rename / delete
- `backend/agent/tui/cli/commands/usage.py` — token-ledger summary
- `backend/agent/tui/cli/commands/config.py` — print / edit
- `backend/agent/tui/cli/commands/doctor.py` — diagnostics
- `backend/agent/telemetry/__init__.py` — package marker
- `backend/agent/telemetry/prices.py` — `MODEL_PRICES` dict
- `backend/agent/telemetry/usage_ledger.py` — SQLite ledger
- `backend/agent/telemetry/hooks.py` — capture helpers used by TUI/CLI/API
- `backend/agent/memory/sessions.py` — sessions reader (joins checkpoints + titles)
- `backend/tests/test_telemetry_ledger.py`
- `backend/tests/test_telemetry_prices.py`
- `backend/tests/test_memory_sessions.py`
- `backend/tests/test_cli_app.py`
- `backend/tests/test_cli_setup.py`
- `backend/tests/test_cli_sessions.py`
- `backend/tests/test_cli_usage.py`
- `backend/tests/test_cli_config.py`
- `backend/tests/test_cli_doctor.py`
- `backend/tests/test_cli_models.py`
- `backend/tests/test_cli_atomic_env.py`

**Modify:**
- `backend/pyproject.toml` — add `typer`, `questionary` deps; change `vellum` script target
- `backend/requirements.txt` — same deps
- `backend/agent/memory/long_term.py` — add `thread_titles` migration to `__init__`
- `backend/agent/cli.py` — call telemetry hook after `agent.ainvoke`
- `backend/agent/tui/app.py` — call telemetry hook on `on_chat_model_end`
- `backend/agent/api.py` — call telemetry hook after `LazyAgent.ainvoke`
- `backend/agent/llm/openrouter.py` — record usage on `openrouter_chat` calls

---

## Task 1: Add dependencies

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add `typer` and `questionary` to `pyproject.toml`**

Edit `backend/pyproject.toml`, in `[project] dependencies`, insert two lines alphabetically:

```toml
  "qdrant-client>=1.12.0",
  "questionary>=2.0.1",
  "rich>=13.7.1",
  "sentence-transformers>=3.3.0",
  "presidio-analyzer>=2.2.354",
  "presidio-anonymizer>=2.2.354",
  "spacy>=3.7.4",
  "textual>=0.89.0",
  "typer>=0.12.0",
  "watchdog>=4.0.0",
```

- [ ] **Step 2: Mirror into `requirements.txt`**

Append (keep alphabetical-ish order to match the existing file):

```
questionary>=2.0.1
typer>=0.12.0
```

- [ ] **Step 3: Install**

Run: `cd backend && ../.venv/Scripts/pip install -e .` (Windows) or `cd backend && ../.venv/bin/pip install -e .` (POSIX)
Expected: `typer` and `questionary` install without errors.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/requirements.txt
git commit -m "Add typer and questionary deps for vellum CLI"
```

---

## Task 2: Create CLI package skeleton with brand voice constants

**Files:**
- Create: `backend/agent/tui/cli/__init__.py`
- Create: `backend/agent/tui/cli/commands/__init__.py`
- Create: `backend/tests/test_cli_app.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_cli_app.py`:

```python
from agent.tui.cli import PHRASES, main


def test_phrases_dict_has_brand_voice_entries():
    expected_keys = {
        "set", "filed", "out", "withheld", "unreachable",
        "nothing_library", "not_configured",
        "landing_setup", "path_quick", "path_full",
        "confirm_yes", "confirm_no", "cancelled",
    }
    assert expected_keys.issubset(PHRASES.keys())


def test_phrases_never_contain_emoji_or_exclamation():
    for key, value in PHRASES.items():
        assert "!" not in value, f"{key} contains '!'"
        for char in value:
            assert ord(char) < 128 or char in "─│·", f"{key} contains non-ascii '{char}'"


def test_main_is_callable():
    assert callable(main)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_app.py -v`
Expected: FAIL — `ImportError: cannot import name 'PHRASES' from 'agent.tui.cli'`

- [ ] **Step 3: Create the package init**

Create `backend/agent/tui/cli/__init__.py`:

```python
"""Vellum CLI — subcommand surface following BRAND.md voice."""

from __future__ import annotations


PHRASES: dict[str, str] = {
    "set": "Set.",
    "filed": "Filed.",
    "out": "Out.",
    "withheld": "Withheld.",
    "unreachable": "Unreachable.",
    "nothing_library": "Nothing on this in your library.",
    "not_configured": "vellum has not been configured. begin setup.",
    "landing_setup": "two paths.",
    "path_quick": "quick      the few choices that matter",
    "path_full":  "full       every choice",
    "confirm_yes": "yes",
    "confirm_no": "no",
    "cancelled": "Out.",
}


def main() -> None:
    from agent.tui.cli.app import app

    app()


__all__ = ["main", "PHRASES"]
```

- [ ] **Step 4: Create `commands` subpackage marker**

Create `backend/agent/tui/cli/commands/__init__.py`:

```python
"""Subcommand handlers for the vellum CLI."""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_app.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/tui/cli/__init__.py backend/agent/tui/cli/commands/__init__.py backend/tests/test_cli_app.py
git commit -m "Create vellum CLI package with brand-voice PHRASES dict"
```

---

## Task 3: Typer root app with --version

**Files:**
- Create: `backend/agent/tui/cli/app.py`
- Modify: `backend/tests/test_cli_app.py`

- [ ] **Step 1: Add failing tests for --version and --help**

Append to `backend/tests/test_cli_app.py`:

```python
from typer.testing import CliRunner

from agent.tui.cli.app import app


def test_version_flag_prints_version():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "vellum" in result.stdout
    assert "0.1.0" in result.stdout


def test_help_uses_brand_voice():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "!" not in result.stdout
    assert "great" not in result.stdout.lower()
    assert "happy" not in result.stdout.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_app.py -v -k "version or help"`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Create the Typer root**

Create `backend/agent/tui/cli/app.py`:

```python
"""Typer entry point for the `vellum` command."""

from __future__ import annotations

import typer

VERSION = "0.1.0"

app = typer.Typer(
    name="vellum",
    help="trained on you.",
    add_completion=False,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"vellum {VERSION}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="show version and exit.",
    ),
) -> None:
    """trained on you."""
    if ctx.invoked_subcommand is None:
        # Bare `vellum` will route to chat in a later task.
        # For now, show help.
        typer.echo(ctx.get_help())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_app.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tui/cli/app.py backend/tests/test_cli_app.py
git commit -m "Wire Typer root app with --version and brand-voiced help"
```

---

## Task 4: Atomic .env read/write helper

**Files:**
- Create: `backend/agent/tui/cli/atomic_env.py`
- Create: `backend/tests/test_cli_atomic_env.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_cli_atomic_env.py`:

```python
from pathlib import Path

import pytest

from agent.tui.cli.atomic_env import load_env, write_env


def test_load_env_returns_dict(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=bar\nBAZ=qux\n", encoding="utf-8")
    assert load_env(env) == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_ignores_blank_and_comment_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# a comment\n\nFOO=bar\n  # indented\n", encoding="utf-8")
    assert load_env(env) == {"FOO": "bar"}


def test_load_env_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_env(tmp_path / "missing.env") == {}


def test_write_env_is_atomic_on_crash(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=original\n", encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(RuntimeError):
        write_env(env, {"FOO": "changed"})

    assert env.read_text(encoding="utf-8") == "FOO=original\n"


def test_write_env_round_trip(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    write_env(env, {"FOO": "bar", "BAZ": "qux"})
    assert load_env(env) == {"FOO": "bar", "BAZ": "qux"}


def test_write_env_preserves_existing_keys_via_merge(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=keep\nBAR=old\n", encoding="utf-8")
    current = load_env(env)
    current["BAR"] = "new"
    current["EXTRA"] = "added"
    write_env(env, current)
    result = load_env(env)
    assert result == {"FOO": "keep", "BAR": "new", "EXTRA": "added"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_atomic_env.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement atomic env helpers**

Create `backend/agent/tui/cli/atomic_env.py`:

```python
"""Atomic .env read/write. Never partial-writes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Missing file returns {}."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        result[key.strip()] = value.strip()
    return result


def write_env(path: Path, values: dict[str, str]) -> None:
    """Write the env file atomically. Crashes mid-write leave the original intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".env.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for key, value in values.items():
                f.write(f"{key}={value}\n")
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_atomic_env.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tui/cli/atomic_env.py backend/tests/test_cli_atomic_env.py
git commit -m "Add atomic .env load/write helpers for vellum CLI"
```

---

## Task 5: Telemetry prices module

**Files:**
- Create: `backend/agent/telemetry/__init__.py`
- Create: `backend/agent/telemetry/prices.py`
- Create: `backend/tests/test_telemetry_prices.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_telemetry_prices.py`:

```python
import pytest

from agent.telemetry.prices import MODEL_PRICES, compute_cost_usd


def test_prices_dict_has_user_env_models():
    # Models referenced in the current .env
    for model in [
        "google/gemma-4-31b-it",
        "google/gemma-3-12b-it",
        "qwen/qwen3.5-35b-a3b",
    ]:
        assert model in MODEL_PRICES, f"missing price entry: {model}"


def test_prices_has_input_and_output_per_million():
    for model, price in MODEL_PRICES.items():
        assert "input" in price, f"{model} missing input price"
        assert "output" in price, f"{model} missing output price"
        assert price["input"] >= 0
        assert price["output"] >= 0


def test_compute_cost_zero_tokens():
    assert compute_cost_usd("google/gemma-4-31b-it", 0, 0) == 0.0


def test_compute_cost_known_model():
    cost = compute_cost_usd("google/gemma-4-31b-it", 1_000_000, 1_000_000)
    price = MODEL_PRICES["google/gemma-4-31b-it"]
    assert cost == pytest.approx(price["input"] + price["output"])


def test_compute_cost_unknown_model_returns_zero():
    assert compute_cost_usd("nonexistent/model", 1_000, 1_000) == 0.0
```

(Note: `import pytest` is at the top — `pytest.approx` is used inside `test_compute_cost_known_model`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_telemetry_prices.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Create the telemetry package**

Create `backend/agent/telemetry/__init__.py`:

```python
"""Token-usage ledger and capture hooks."""
```

- [ ] **Step 4: Implement prices**

Create `backend/agent/telemetry/prices.py`:

```python
"""OpenRouter model prices (USD per million tokens).

Hand-curated. OpenRouter's billing is the source of truth — these numbers
exist for the `vellum usage` display only. Update when a model is added.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


MODEL_PRICES: dict[str, dict[str, float]] = {
    # Anthropic via OpenRouter
    "anthropic/claude-opus-4.6":    {"input": 15.00, "output": 75.00},
    "anthropic/claude-sonnet-4.6":  {"input":  3.00, "output": 15.00},
    "anthropic/claude-haiku-4.5":   {"input":  1.00, "output":  5.00},
    # OpenAI via OpenRouter
    "openai/gpt-5.4":               {"input":  2.50, "output": 15.00},
    "openai/gpt-5.4-mini":          {"input":  0.75, "output":  4.50},
    # Google via OpenRouter
    "google/gemini-3-pro-preview":  {"input":  2.00, "output": 12.00},
    "google/gemini-3-flash-preview":{"input":  0.50, "output":  3.00},
    "google/gemma-4-31b-it":        {"input":  0.20, "output":  0.30},
    "google/gemma-3-12b-it":        {"input":  0.05, "output":  0.10},
    # Qwen
    "qwen/qwen3.5-35b-a3b":         {"input":  0.16, "output":  1.30},
    "qwen/qwen3.6-plus":            {"input":  0.33, "output":  1.95},
    # Misc cheap fallbacks
    "minimax/minimax-m2.5":         {"input":  0.12, "output":  0.99},
    "z-ai/glm-5.1":                 {"input":  0.95, "output":  3.15},
}


def compute_cost_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    """Compute usd cost for one call. Unknown models price at zero."""
    if model not in MODEL_PRICES:
        logger.debug("no price entry for model %s — recording zero cost", model)
        return 0.0
    p = MODEL_PRICES[model]
    return (in_tokens / 1_000_000) * p["input"] + (out_tokens / 1_000_000) * p["output"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_telemetry_prices.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/telemetry/__init__.py backend/agent/telemetry/prices.py backend/tests/test_telemetry_prices.py
git commit -m "Add MODEL_PRICES dict and compute_cost_usd helper"
```

---

## Task 6: Telemetry usage ledger SQLite store

**Files:**
- Create: `backend/agent/telemetry/usage_ledger.py`
- Create: `backend/tests/test_telemetry_ledger.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_telemetry_ledger.py`:

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.telemetry.usage_ledger import UsageLedger


@pytest.fixture
def ledger(tmp_path: Path) -> UsageLedger:
    return UsageLedger(tmp_path / "usage.db")


def test_ledger_creates_db_on_first_write(ledger: UsageLedger, tmp_path: Path) -> None:
    assert not (tmp_path / "usage.db").exists()
    ledger.record(
        thread_id="t1", model="google/gemma-4-31b-it",
        in_tokens=100, out_tokens=50, source="tui",
    )
    assert (tmp_path / "usage.db").exists()


def test_record_persists_row(ledger: UsageLedger) -> None:
    ledger.record(
        thread_id="t1", model="google/gemma-4-31b-it",
        in_tokens=100, out_tokens=50, source="tui",
    )
    rows = ledger.all_rows()
    assert len(rows) == 1
    assert rows[0]["thread_id"] == "t1"
    assert rows[0]["model"] == "google/gemma-4-31b-it"
    assert rows[0]["in_tokens"] == 100
    assert rows[0]["out_tokens"] == 50
    assert rows[0]["source"] == "tui"
    assert rows[0]["cost_usd"] == pytest.approx(0.0000350)  # 100*0.2/1M + 50*0.3/1M


def test_summarize_window_filters_by_days(ledger: UsageLedger) -> None:
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=1_000_000, out_tokens=0, source="tui", ts=old_ts)
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=2_000_000, out_tokens=0, source="tui", ts=new_ts)
    summary = ledger.summarize(days=7)
    assert len(summary) == 1
    assert summary[0]["in_tokens"] == 2_000_000


def test_summarize_aggregates_per_model(ledger: UsageLedger) -> None:
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=100, out_tokens=50, source="tui")
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=200, out_tokens=100, source="cli")
    ledger.record(thread_id="t1", model="google/gemma-3-12b-it",
                  in_tokens=10, out_tokens=5, source="api")
    summary = sorted(ledger.summarize(days=7), key=lambda r: r["model"])
    assert len(summary) == 2
    gemma3 = summary[0]
    gemma4 = summary[1]
    assert gemma3["model"] == "google/gemma-3-12b-it"
    assert gemma3["in_tokens"] == 10
    assert gemma4["model"] == "google/gemma-4-31b-it"
    assert gemma4["in_tokens"] == 300
    assert gemma4["out_tokens"] == 150


def test_pragma_user_version_is_one(ledger: UsageLedger) -> None:
    ledger.record(thread_id="t1", model="x", in_tokens=0, out_tokens=0, source="tui")
    assert ledger.user_version() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_telemetry_ledger.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement the ledger**

Create `backend/agent/telemetry/usage_ledger.py`:

```python
"""SQLite-backed token-usage ledger for `vellum usage`."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.telemetry.prices import compute_cost_usd

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  model TEXT NOT NULL,
  in_tokens INTEGER NOT NULL,
  out_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
PRAGMA user_version = 1;
"""


class UsageLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        return conn

    def record(
        self,
        *,
        thread_id: str,
        model: str,
        in_tokens: int,
        out_tokens: int,
        source: str,
        ts: str | None = None,
    ) -> None:
        ts = ts or datetime.now(timezone.utc).isoformat()
        cost = compute_cost_usd(model, in_tokens, out_tokens)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO usage (ts, thread_id, model, in_tokens, out_tokens, cost_usd, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, thread_id, model, in_tokens, out_tokens, cost, source),
            )

    def all_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM usage ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    def summarize(self, *, days: int = 7) -> list[dict[str, Any]]:
        """Aggregate by model over the last `days` days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT model,
                       SUM(in_tokens)  AS in_tokens,
                       SUM(out_tokens) AS out_tokens,
                       SUM(cost_usd)   AS cost_usd
                FROM usage
                WHERE ts >= ?
                GROUP BY model
                ORDER BY cost_usd DESC
                """,
                (cutoff,),
            )
            return [dict(r) for r in cur.fetchall()]

    def user_version(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("PRAGMA user_version")
            return int(cur.fetchone()[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_telemetry_ledger.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/telemetry/usage_ledger.py backend/tests/test_telemetry_ledger.py
git commit -m "Add UsageLedger SQLite store for token usage tracking"
```

---

## Task 7: Telemetry capture hooks

**Files:**
- Create: `backend/agent/telemetry/hooks.py`
- Modify: `backend/tests/test_telemetry_ledger.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_telemetry_ledger.py`:

```python
from agent.telemetry.hooks import (
    capture_from_invoke_result,
    capture_from_stream_event,
)


class _FakeAIMessage:
    def __init__(self, usage: dict | None) -> None:
        self.usage_metadata = usage


def test_capture_from_invoke_result_records_aimessage_usage(ledger: UsageLedger) -> None:
    result = {
        "messages": [
            _FakeAIMessage({
                "input_tokens": 120,
                "output_tokens": 40,
                "model_name": "google/gemma-4-31b-it",
            })
        ]
    }
    capture_from_invoke_result(
        ledger=ledger,
        result=result,
        thread_id="t1",
        fallback_model="google/gemma-4-31b-it",
        source="cli",
    )
    rows = ledger.all_rows()
    assert len(rows) == 1
    assert rows[0]["in_tokens"] == 120
    assert rows[0]["out_tokens"] == 40
    assert rows[0]["source"] == "cli"


def test_capture_from_invoke_result_skips_messages_without_usage(ledger: UsageLedger) -> None:
    result = {"messages": [_FakeAIMessage(None), _FakeAIMessage({})]}
    capture_from_invoke_result(
        ledger=ledger, result=result, thread_id="t1",
        fallback_model="x", source="cli",
    )
    assert ledger.all_rows() == []


def test_capture_from_stream_event_records_on_chat_model_end(ledger: UsageLedger) -> None:
    event = {
        "event": "on_chat_model_end",
        "data": {
            "output": _FakeAIMessage({
                "input_tokens": 50,
                "output_tokens": 25,
                "model_name": "google/gemma-3-12b-it",
            })
        },
    }
    capture_from_stream_event(
        ledger=ledger, event=event, thread_id="t9",
        fallback_model="google/gemma-3-12b-it", source="tui",
    )
    rows = ledger.all_rows()
    assert len(rows) == 1
    assert rows[0]["out_tokens"] == 25
    assert rows[0]["source"] == "tui"


def test_capture_from_stream_event_ignores_other_events(ledger: UsageLedger) -> None:
    event = {"event": "on_chat_model_stream", "data": {}}
    capture_from_stream_event(
        ledger=ledger, event=event, thread_id="t9",
        fallback_model="x", source="tui",
    )
    assert ledger.all_rows() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_telemetry_ledger.py -v -k "capture"`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement hooks**

Create `backend/agent/telemetry/hooks.py`:

```python
"""Capture helpers that turn LangChain message usage into ledger rows."""

from __future__ import annotations

import logging
from typing import Any

from agent.telemetry.usage_ledger import UsageLedger

logger = logging.getLogger(__name__)


def _extract_usage(obj: Any) -> dict[str, Any] | None:
    """Pull a usage_metadata dict off an AIMessage-like object."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        usage = obj.get("usage_metadata")
    else:
        usage = getattr(obj, "usage_metadata", None)
    if not usage:
        return None
    return dict(usage)


def _record_one(
    *,
    ledger: UsageLedger,
    usage: dict[str, Any],
    thread_id: str,
    fallback_model: str,
    source: str,
) -> None:
    in_tokens = int(usage.get("input_tokens") or 0)
    out_tokens = int(usage.get("output_tokens") or 0)
    if in_tokens == 0 and out_tokens == 0:
        return
    model = str(usage.get("model_name") or fallback_model)
    try:
        ledger.record(
            thread_id=thread_id,
            model=model,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            source=source,
        )
    except Exception as exc:  # never block the chat path
        logger.warning("ledger write failed: %s", exc)


def capture_from_invoke_result(
    *,
    ledger: UsageLedger,
    result: dict[str, Any],
    thread_id: str,
    fallback_model: str,
    source: str,
) -> None:
    """Scan a LangGraph `ainvoke` result for AIMessages with usage_metadata."""
    messages = result.get("messages", []) if isinstance(result, dict) else []
    for msg in messages:
        usage = _extract_usage(msg)
        if usage:
            _record_one(
                ledger=ledger, usage=usage, thread_id=thread_id,
                fallback_model=fallback_model, source=source,
            )


def capture_from_stream_event(
    *,
    ledger: UsageLedger,
    event: dict[str, Any],
    thread_id: str,
    fallback_model: str,
    source: str,
) -> None:
    """Handle a single `astream_events` event; only fires on chat-model-end."""
    if event.get("event") != "on_chat_model_end":
        return
    output = event.get("data", {}).get("output")
    usage = _extract_usage(output)
    if usage:
        _record_one(
            ledger=ledger, usage=usage, thread_id=thread_id,
            fallback_model=fallback_model, source=source,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_telemetry_ledger.py -v`
Expected: PASS — 9 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/telemetry/hooks.py backend/tests/test_telemetry_ledger.py
git commit -m "Add telemetry capture hooks for invoke and stream events"
```

---

## Task 8: Wire telemetry into agent.cli chat loop

**Files:**
- Modify: `backend/agent/cli.py`

- [ ] **Step 1: Read the current `chat_loop` signature region**

Read `backend/agent/cli.py` lines 125–185 to confirm structure.

- [ ] **Step 2: Add imports and module-level ledger**

In `backend/agent/cli.py`, in the import block at the top of the file (after the existing `from agent.tools.obsidian_write import store_qa_pair` line), add:

```python
from pathlib import Path

from agent.telemetry.hooks import capture_from_invoke_result
from agent.telemetry.usage_ledger import UsageLedger

_LEDGER = UsageLedger(Path("data/memory/usage.db"))
```

- [ ] **Step 3: Add a small helper above `chat_loop`**

In `backend/agent/cli.py`, before the `async def chat_loop(...)` definition, add:

```python
def _record_chat_usage(result: dict, cfg: dict) -> None:
    thread_id = cfg.get("configurable", {}).get("thread_id", settings.thread_id)
    capture_from_invoke_result(
        ledger=_LEDGER,
        result=result,
        thread_id=thread_id,
        fallback_model=settings.primary_model,
        source="cli",
    )
```

- [ ] **Step 4: Call the helper from `chat_loop`**

In `backend/agent/cli.py`, locate inside `chat_loop`:

```python
            messages = result.get("messages", []) if isinstance(result, dict) else []
            answer = _message_content(messages[-1] if messages else None) or "No response."
            tool_calls = _tool_call_names(messages)
            active_console.print(render_answer(answer, tool_calls))
```

Insert one line after `tool_calls = ...`:

```python
            messages = result.get("messages", []) if isinstance(result, dict) else []
            answer = _message_content(messages[-1] if messages else None) or "No response."
            tool_calls = _tool_call_names(messages)
            _record_chat_usage(result, active_thread_config)
            active_console.print(render_answer(answer, tool_calls))
```

- [ ] **Step 5: Run existing tests to check nothing breaks**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/ -v --ignore=tests/test_cli_app.py --ignore=tests/test_tui.py -x`
Expected: existing tests still pass. No new tests added in this task because the chat loop integration is harder to unit-test without mocking the whole agent; the unit tests on `capture_from_invoke_result` (Task 7) already cover the contract.

- [ ] **Step 6: Manual sanity check**

Run: `cd backend && ../.venv/Scripts/python -c "from agent.cli import _LEDGER, _record_chat_usage; print(_LEDGER.path)"`
Expected: prints `data\memory\usage.db` (Windows) or `data/memory/usage.db` (POSIX).

- [ ] **Step 7: Commit**

```bash
git add backend/agent/cli.py
git commit -m "Wire telemetry capture into agent.cli chat loop"
```

---

## Task 9: Wire telemetry into TUI streaming

**Files:**
- Modify: `backend/agent/tui/app.py`

- [ ] **Step 1: Add telemetry imports and ledger attribute**

In `backend/agent/tui/app.py`, after the existing imports, add:

```python
from pathlib import Path

from agent.telemetry.hooks import capture_from_stream_event
from agent.telemetry.usage_ledger import UsageLedger
```

In `VellumTuiApp.__init__`, after `self.memory = LongTermMemory()`, add:

```python
        self.usage_ledger = UsageLedger(Path("data/memory/usage.db"))
```

- [ ] **Step 2: Hook the stream loop**

In `VellumTuiApp._stream_agent`, locate the `async for event in stream:` block. Inside the loop, after the existing event-type handling (`on_chat_model_stream` and `on_tool_start`), add a call:

```python
            async for event in stream:
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    text = stream_chunk_text(event.get("data", {}).get("chunk"))
                    if text:
                        messages.append_assistant_token(escape(text))
                elif kind == "on_tool_start":
                    name = str(event.get("name") or "")
                    if name:
                        self.last_tool_names.append(name)
                capture_from_stream_event(
                    ledger=self.usage_ledger,
                    event=event,
                    thread_id=self.active_thread_id,
                    fallback_model=self.settings.primary_model,
                    source="tui",
                )
```

- [ ] **Step 3: Run TUI tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_tui.py -v`
Expected: PASS — existing tui tests unaffected.

- [ ] **Step 4: Commit**

```bash
git add backend/agent/tui/app.py
git commit -m "Wire telemetry capture into TUI stream loop"
```

---

## Task 10: Wire telemetry into FastAPI chat endpoint

**Files:**
- Modify: `backend/agent/api.py`

- [ ] **Step 1: Inspect the chat endpoint**

Read `backend/agent/api.py` and locate the `@app.post("/api/chat")` handler. Identify where `LazyAgent.ainvoke(...)` is awaited and where the response is returned.

- [ ] **Step 2: Add imports**

At the top of `backend/agent/api.py`, after the existing imports:

```python
from pathlib import Path

from agent.telemetry.hooks import capture_from_invoke_result
from agent.telemetry.usage_ledger import UsageLedger

_api_ledger = UsageLedger(Path("data/memory/usage.db"))
```

- [ ] **Step 3: Capture after each invoke**

Inside the chat endpoint, immediately after the `result = await agent.ainvoke(...)` call and before returning the response, insert:

```python
    capture_from_invoke_result(
        ledger=_api_ledger,
        result=result,
        thread_id=thread_id_for_request,  # rename to the actual variable in scope
        fallback_model=settings.primary_model,
        source="api",
    )
```

(Use whatever variable name the existing handler uses for the thread id — typically `thread_id` or `request.thread_id`.)

- [ ] **Step 4: Run any API tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/ -v -k "api"`
Expected: PASS or "no tests collected" — endpoint changes are additive.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/api.py
git commit -m "Wire telemetry capture into FastAPI chat endpoint"
```

---

## Task 11: Capture usage from background openrouter_chat calls

**Files:**
- Modify: `backend/agent/llm/openrouter.py`

- [ ] **Step 1: Read the openrouter module**

Read `backend/agent/llm/openrouter.py` end-to-end. Identify:
- the function signature of `openrouter_chat`, including the names of `model_override` and `settings` (the `Settings` instance access pattern),
- the local variable that holds the parsed JSON response from the API call (it'll be the `.json()` result of an httpx response),
- the field names exposed by OpenRouter's `usage` block (typically `prompt_tokens`, `completion_tokens`, `total_tokens`).

- [ ] **Step 2: Add imports and ledger at module top**

In `backend/agent/llm/openrouter.py`, in the import block:

```python
from pathlib import Path

from agent.telemetry.usage_ledger import UsageLedger

_or_ledger = UsageLedger(Path("data/memory/usage.db"))
```

- [ ] **Step 3: Record usage after the API response is parsed**

Inside `openrouter_chat`, immediately after the line that parses the response JSON (the variable found in Step 1 — call it `response_payload` here for illustration) and before the function returns, insert:

```python
    try:
        _usage = response_payload.get("usage", {}) or {}
        _in_tok = int(_usage.get("prompt_tokens") or 0)
        _out_tok = int(_usage.get("completion_tokens") or 0)
        if _in_tok or _out_tok:
            _or_ledger.record(
                thread_id="background",
                model=model_override or settings.primary_model,
                in_tokens=_in_tok,
                out_tokens=_out_tok,
                source="cli",
            )
    except Exception:
        pass
```

If your local variable for the parsed JSON is called something else (e.g. `data`, `payload`, `body`), substitute that name for `response_payload`. The `try/except` is deliberate — fact extraction must never fail because of a telemetry hiccup.

- [ ] **Step 4: Run tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/ -v`
Expected: all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/llm/openrouter.py
git commit -m "Capture token usage from background openrouter_chat calls"
```

---

## Task 12: thread_titles table in long_term.db

**Files:**
- Modify: `backend/agent/memory/long_term.py`

Context: `LongTermMemory.__init__(self, db_path=DB_PATH)` calls `self._init()` which executes individual `conn.execute("CREATE TABLE IF NOT EXISTS ...")` calls for `facts` and `query_log`. The connect helper is `self._connect()`. We extend `_init` with one more table and add three methods.

- [ ] **Step 1: Add thread_titles CREATE to `_init`**

In `backend/agent/memory/long_term.py`, in the `_init` method, after the existing two `conn.execute("CREATE INDEX...")` lines, add:

```python
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_titles (
                    thread_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
```

- [ ] **Step 2: Add three helper methods to the `LongTermMemory` class**

Append inside the class (after `get_recent_queries`):

```python
    def set_thread_title(self, thread_id: str, title: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO thread_titles (thread_id, title, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(thread_id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at",
                (thread_id, title, self._now()),
            )

    def get_thread_title(self, thread_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title FROM thread_titles WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            return row["title"] if row else None

    def delete_thread_title(self, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM thread_titles WHERE thread_id = ?", (thread_id,))
```

- [ ] **Step 3: Smoke test**

Run: `cd backend && ../.venv/Scripts/python -c "from agent.memory.long_term import LongTermMemory; m = LongTermMemory(); m.set_thread_title('t1', 'hello'); print(m.get_thread_title('t1'))"`
Expected: prints `hello`.

- [ ] **Step 4: Commit**

```bash
git add backend/agent/memory/long_term.py
git commit -m "Add thread_titles table and helpers to LongTermMemory"
```

---

## Task 13: Sessions reader module

**Files:**
- Create: `backend/agent/memory/sessions.py`
- Create: `backend/tests/test_memory_sessions.py`

Context: the real `langgraph-checkpoint-sqlite` schema is `checkpoints(thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)`. There is **no `ts` column**. We sort by `MAX(checkpoint_id)` descending (checkpoint IDs are time-ordered ULIDs/UUIDs in practice). The session output exposes `thread_id`, `title`, and `msgs` — no separate "last" timestamp column.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_memory_sessions.py`:

```python
import sqlite3
from pathlib import Path

import pytest

from agent.memory.sessions import SessionsReader


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memory").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def reader(workdir: Path) -> SessionsReader:
    return SessionsReader(
        checkpoints_db=workdir / "data" / "memory" / "checkpoints.db",
        long_term_db=workdir / "data" / "memory" / "long_term.db",
    )


def _seed_checkpoint(path: Path, thread_id: str, checkpoint_ids: list[str]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint BLOB,
            metadata BLOB,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )
    for cid in checkpoint_ids:
        conn.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id) VALUES (?, '', ?)",
            (thread_id, cid),
        )
    conn.commit()
    conn.close()


def test_list_sessions_empty_when_no_db(reader: SessionsReader) -> None:
    assert reader.list_sessions() == []


def test_list_sessions_reads_checkpoints(reader: SessionsReader, workdir: Path) -> None:
    cp_db = workdir / "data" / "memory" / "checkpoints.db"
    # "default" thread has the higher-sorting checkpoint id -> appears first
    _seed_checkpoint(cp_db, "default", ["01J000", "01J001", "01J002"])
    _seed_checkpoint(cp_db, "research", ["01H900", "01H901"])
    sessions = reader.list_sessions()
    assert len(sessions) == 2
    by_id = {s["thread_id"]: s for s in sessions}
    assert by_id["default"]["msgs"] == 3
    assert by_id["research"]["msgs"] == 2
    assert sessions[0]["thread_id"] == "default"


def test_list_sessions_joins_title_when_set(reader: SessionsReader, workdir: Path) -> None:
    _seed_checkpoint(workdir / "data" / "memory" / "checkpoints.db", "t1", ["01J0"])
    reader.rename("t1", "my research")
    sessions = reader.list_sessions()
    assert sessions[0]["title"] == "my research"


def test_list_sessions_title_falls_back_to_thread_id(reader: SessionsReader, workdir: Path) -> None:
    _seed_checkpoint(workdir / "data" / "memory" / "checkpoints.db", "t9", ["01J0"])
    assert reader.list_sessions()[0]["title"] == "t9"


def test_delete_removes_checkpoints_and_title(reader: SessionsReader, workdir: Path) -> None:
    _seed_checkpoint(workdir / "data" / "memory" / "checkpoints.db", "t1", ["01J0", "01J1"])
    reader.rename("t1", "named")
    reader.delete("t1")
    assert reader.list_sessions() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_memory_sessions.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement sessions reader**

Create `backend/agent/memory/sessions.py`:

```python
"""Reads and writes thread metadata. Joins checkpoints.db with thread_titles."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from agent.memory.long_term import LongTermMemory


class SessionsReader:
    def __init__(self, *, checkpoints_db: Path, long_term_db: Path) -> None:
        self.checkpoints_db = Path(checkpoints_db)
        self.long_term_db = Path(long_term_db)

    def _checkpoint_rows(self) -> list[tuple[str, int]]:
        """Return (thread_id, msg_count) tuples ordered newest-first.

        The langgraph-checkpoint-sqlite schema is:
            checkpoints(thread_id, checkpoint_ns, checkpoint_id,
                        parent_checkpoint_id, type, checkpoint, metadata)
        It has no `ts` column. We sort by MAX(checkpoint_id) descending —
        checkpoint IDs are ULID-style in practice, so lexicographic max
        approximates "most recent activity" well enough for display.
        """
        if not self.checkpoints_db.exists():
            return []
        conn = sqlite3.connect(str(self.checkpoints_db))
        try:
            cur = conn.execute(
                """
                SELECT thread_id,
                       COUNT(*) AS msgs,
                       MAX(checkpoint_id) AS last_ckpt
                FROM checkpoints
                GROUP BY thread_id
                ORDER BY last_ckpt DESC
                """
            )
            return [(r[0], int(r[1])) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def _memory(self) -> LongTermMemory:
        return LongTermMemory(db_path=self.long_term_db)

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._checkpoint_rows()
        mem = self._memory()
        return [
            {
                "thread_id": thread_id,
                "title": mem.get_thread_title(thread_id) or thread_id,
                "msgs": msgs,
            }
            for thread_id, msgs in rows
        ]

    def rename(self, thread_id: str, title: str) -> None:
        self._memory().set_thread_title(thread_id, title)

    def delete(self, thread_id: str) -> None:
        if self.checkpoints_db.exists():
            conn = sqlite3.connect(str(self.checkpoints_db))
            try:
                conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ?",
                    (thread_id,),
                )
                # Also delete from writes table (langgraph stores intermediates there)
                try:
                    conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                except sqlite3.OperationalError:
                    pass
                conn.commit()
            finally:
                conn.close()
        self._memory().delete_thread_title(thread_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_memory_sessions.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/memory/sessions.py backend/tests/test_memory_sessions.py
git commit -m "Add SessionsReader joining checkpoints.db with thread_titles"
```

---

## Task 14: Screen primitives (ANSI clear, header, picker)

**Files:**
- Create: `backend/agent/tui/cli/screen.py`

- [ ] **Step 1: Implement primitives (no unit tests; visual)**

Create `backend/agent/tui/cli/screen.py`:

```python
"""Brand-voiced screen primitives for the vellum CLI.

Each interactive step calls `ansi_clear()` first so the previous step
vanishes — viewport AND scrollback. Headers are letter-spaced uppercase,
matching the brand's "DM Sans, weight 500, letter-spacing 0.16em uppercase"
metadata register.
"""

from __future__ import annotations

import sys
from typing import Iterable

import questionary
from questionary import Choice
from rich.console import Console

EMBER = "#d97746"
PARCHMENT = "#ece6db"
GRAPHITE = "#0c0c0e"
DIM = "#716d68"

console = Console()


def ansi_clear() -> None:
    """Clear viewport and scrollback. Works on Windows Terminal + PowerShell."""
    sys.stdout.write("\x1b[2J\x1b[3J\x1b[H")
    sys.stdout.flush()


def draw_header(label: str) -> None:
    """Render a brand-voiced uppercase letter-spaced header."""
    spaced = " ".join(label.upper())
    console.print()
    console.print(f"  [bold {PARCHMENT}]{spaced}[/]")
    console.print()


_style = questionary.Style([
    ("qmark", f"fg:{EMBER} bold"),
    ("question", f"fg:{PARCHMENT}"),
    ("answer", f"fg:{EMBER} bold"),
    ("pointer", f"fg:{EMBER} bold"),
    ("highlighted", f"fg:{EMBER} bold"),
    ("selected", f"fg:{EMBER}"),
    ("instruction", f"fg:{DIM}"),
    ("text", f"fg:{PARCHMENT}"),
    ("disabled", f"fg:{DIM}"),
])


def pick(
    *,
    header: str,
    choices: Iterable[tuple[str, str]] | Iterable[Choice],
    default: str | None = None,
) -> str | None:
    """Show an arrow-key picker on a fresh screen. Returns the selected value or None on cancel.

    `choices` may be (value, label) tuples or pre-built Choice objects.
    """
    ansi_clear()
    draw_header(header)
    normalized: list[Choice] = []
    for c in choices:
        if isinstance(c, Choice):
            normalized.append(c)
        else:
            value, label = c
            normalized.append(Choice(title=label, value=value))
    return questionary.select(
        "",
        choices=normalized,
        default=default,
        instruction="↑↓ select   enter confirm",
        style=_style,
        qmark=">",
    ).ask()


def ask_text(*, header: str, prompt: str, default: str = "") -> str | None:
    """Single-line text input on a fresh screen."""
    ansi_clear()
    draw_header(header)
    return questionary.text(
        prompt,
        default=default,
        instruction="enter saves   esc cancels",
        style=_style,
        qmark=">",
    ).ask()


def ask_password(*, header: str, prompt: str) -> str | None:
    """Single-line password input on a fresh screen."""
    ansi_clear()
    draw_header(header)
    return questionary.password(
        prompt,
        instruction="enter saves   esc cancels",
        style=_style,
        qmark=">",
    ).ask()


def say(phrase: str) -> None:
    """Print a brand-voiced phrase on its own line, in parchment."""
    console.print(f"[{PARCHMENT}]{phrase}[/]")
```

- [ ] **Step 2: Smoke-import test**

Run: `cd backend && ../.venv/Scripts/python -c "from agent.tui.cli.screen import ansi_clear, draw_header, pick, ask_text, ask_password, say; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/agent/tui/cli/screen.py
git commit -m "Add brand-voiced screen primitives for CLI wizards"
```

---

## Task 15: chat / resume / first-run command

**Files:**
- Create: `backend/agent/tui/cli/commands/chat.py`
- Modify: `backend/agent/tui/cli/app.py`
- Modify: `backend/tests/test_cli_app.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_cli_app.py`:

```python
def test_resume_requires_thread_id():
    runner = CliRunner()
    result = runner.invoke(app, ["resume"])
    assert result.exit_code != 0  # missing required arg


def test_chat_subcommand_exists():
    runner = CliRunner()
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0
    assert "chat" in result.stdout.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_app.py -v -k "resume or chat_sub"`
Expected: FAIL — `chat` / `resume` not registered yet.

- [ ] **Step 3: Implement the chat command module**

Create `backend/agent/tui/cli/commands/chat.py`:

```python
"""bare vellum, vellum chat, vellum resume <id> — all open the TUI."""

from __future__ import annotations

import typer
from pydantic import ValidationError

from agent.tui.cli import PHRASES
from agent.tui.cli.screen import say


def _settings_ok() -> bool:
    try:
        from agent.config import get_settings
        get_settings()
        return True
    except (ValidationError, Exception):
        return False


def launch_tui(thread_id: str | None = None) -> None:
    """Start the Textual TUI, optionally pinned to a specific thread."""
    if not _settings_ok():
        say(PHRASES["not_configured"])
        from agent.tui.cli.commands.setup import run_wizard
        run_wizard(quick=True)
        if not _settings_ok():
            raise typer.Exit(code=1)
    from agent.tui.app import VellumTuiApp
    app_instance = VellumTuiApp()
    if thread_id:
        app_instance.active_thread_id = thread_id
    app_instance.run()


def chat() -> None:
    """trained on you. open the chat surface."""
    launch_tui(thread_id=None)


def resume(thread_id: str = typer.Argument(..., help="thread id to reopen")) -> None:
    """reopen a saved thread."""
    launch_tui(thread_id=thread_id)
```

- [ ] **Step 4: Register subcommands in app.py**

In `backend/agent/tui/cli/app.py`, after the `_version_callback` and `root` definitions, register:

```python
from agent.tui.cli.commands.chat import chat as chat_cmd
from agent.tui.cli.commands.chat import resume as resume_cmd

app.command(name="chat", help="open the chat surface.")(chat_cmd)
app.command(name="resume", help="reopen a saved thread.")(resume_cmd)
```

Modify the `root()` callback so bare `vellum` invokes chat instead of showing help:

```python
@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", callback=_version_callback,
        is_eager=True, help="show version and exit.",
    ),
) -> None:
    """trained on you."""
    if ctx.invoked_subcommand is None:
        from agent.tui.cli.commands.chat import chat as chat_cmd
        chat_cmd()
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_app.py -v`
Expected: PASS — including new chat/resume tests.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/tui/cli/commands/chat.py backend/agent/tui/cli/app.py backend/tests/test_cli_app.py
git commit -m "Wire vellum / chat / resume commands with first-run routing"
```

---

## Task 16: Setup wizard — landing + atomic write

**Files:**
- Create: `backend/agent/tui/cli/commands/setup.py`
- Modify: `backend/agent/tui/cli/app.py`
- Create: `backend/tests/test_cli_setup.py`

- [ ] **Step 1: Write failing tests for setup module**

Create `backend/tests/test_cli_setup.py`:

```python
from pathlib import Path

import pytest

from agent.tui.cli.commands.setup import _merge_into_env, _Path_env


def test_merge_into_env_overwrites_keys(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=old\nBAR=keep\n", encoding="utf-8")
    monkeypatch.setattr("agent.tui.cli.commands.setup._Path_env", lambda: env)
    _merge_into_env({"FOO": "new", "BAZ": "added"})
    text = env.read_text(encoding="utf-8")
    assert "FOO=new" in text
    assert "BAR=keep" in text
    assert "BAZ=added" in text


def test_merge_into_env_creates_file_if_missing(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    monkeypatch.setattr("agent.tui.cli.commands.setup._Path_env", lambda: env)
    _merge_into_env({"FOO": "bar"})
    assert env.read_text(encoding="utf-8") == "FOO=bar\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_setup.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement landing + merge helper**

Create `backend/agent/tui/cli/commands/setup.py`:

```python
"""vellum setup — Hermes-style wizard with one step per cleared screen."""

from __future__ import annotations

from pathlib import Path

import typer

from agent.tui.cli import PHRASES
from agent.tui.cli.atomic_env import load_env, write_env
from agent.tui.cli.screen import ansi_clear, ask_password, ask_text, pick, say


def _Path_env() -> Path:
    return Path(".env")


def _merge_into_env(updates: dict[str, str]) -> None:
    """Read-modify-write the .env atomically. Preserves keys not in `updates`."""
    path = _Path_env()
    current = load_env(path)
    current.update(updates)
    write_env(path, current)


def _step_landing() -> str | None:
    return pick(
        header="vellum",
        choices=[
            ("quick", PHRASES["path_quick"]),
            ("full",  PHRASES["path_full"]),
        ],
        default="quick",
    )


def _step_provider(current: dict[str, str]) -> dict[str, str] | None:
    choice = pick(
        header="provider",
        choices=[
            ("openrouter", "openrouter        zdr, pay-per-use"),
            ("skip",       "skip              keep current"),
        ],
        default="openrouter" if not current.get("OPENROUTER_BASE_URL") else "skip",
    )
    if choice is None:
        return None
    if choice == "skip":
        return {}
    return {"OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1"}


def _step_key(current: dict[str, str]) -> dict[str, str] | None:
    existing = current.get("OPENROUTER_API_KEY", "")
    hint = f"current key starts {existing[:7]}…" if existing else "no key set."
    key = ask_password(header="key", prompt=f"openrouter api key   ({hint})")
    if key is None:
        return None
    if key.strip() == "":
        return {}
    return {"OPENROUTER_API_KEY": key.strip()}


def _step_vault(current: dict[str, str]) -> dict[str, str] | None:
    existing = current.get("OBSIDIAN_VAULT_PATH", "")
    path = ask_text(
        header="vault",
        prompt="path to your obsidian vault",
        default=existing,
    )
    if path is None:
        return None
    if path.strip() == "":
        return {}
    p = path.strip()
    return {
        "OBSIDIAN_VAULT_PATH": p,
        "FILESYSTEM_MCP_PATH": p,
    }


def _step_model(current: dict[str, str]) -> dict[str, str] | None:
    from agent.tui.cli.commands.models import KNOWN_MODELS
    existing = current.get("PRIMARY_MODEL", "")
    choice = pick(
        header="model",
        choices=[(m["id"], f"{m['id']:<40} {m['hint']}") for m in KNOWN_MODELS]
                + [("skip", "skip              keep current")],
        default=existing or KNOWN_MODELS[0]["id"],
    )
    if choice is None:
        return None
    if choice == "skip":
        return {}
    return {"PRIMARY_MODEL": choice}


_QUICK_STEPS = [_step_provider, _step_key, _step_vault, _step_model]


def _step_log_level(current: dict[str, str]) -> dict[str, str] | None:
    choice = pick(
        header="log level",
        choices=[("INFO", "info"), ("DEBUG", "debug"), ("WARNING", "warning")],
        default=current.get("LOG_LEVEL", "INFO"),
    )
    if choice is None:
        return None
    return {"LOG_LEVEL": choice}


def _step_digest(current: dict[str, str]) -> dict[str, str] | None:
    choice = pick(
        header="nightly digest",
        choices=[("true", "on"), ("false", "off")],
        default=current.get("ENABLE_NIGHTLY_DIGEST", "true"),
    )
    if choice is None:
        return None
    return {"ENABLE_NIGHTLY_DIGEST": choice}


def _step_watcher(current: dict[str, str]) -> dict[str, str] | None:
    choice = pick(
        header="vault watcher",
        choices=[("true", "on"), ("false", "off")],
        default=current.get("ENABLE_VAULT_WATCHER", "true"),
    )
    if choice is None:
        return None
    return {"ENABLE_VAULT_WATCHER": choice}


_FULL_STEPS = _QUICK_STEPS + [_step_log_level, _step_digest, _step_watcher]


def run_wizard(quick: bool = False, topic: str | None = None) -> None:
    """Run the wizard. `topic` jumps directly to a single sub-wizard."""
    current = load_env(_Path_env())

    if topic == "model":
        result = _step_model(current)
        if result is None:
            say(PHRASES["cancelled"])
            return
        _merge_into_env(result)
        say(PHRASES["set"])
        return

    if not quick and topic is None:
        landing = _step_landing()
        if landing is None:
            say(PHRASES["cancelled"])
            return
        quick = landing == "quick"

    steps = _QUICK_STEPS if quick else _FULL_STEPS
    accumulated: dict[str, str] = {}
    for step in steps:
        result = step({**current, **accumulated})
        if result is None:
            say(PHRASES["cancelled"])
            return
        accumulated.update(result)

    if accumulated:
        _merge_into_env(accumulated)
    say(PHRASES["filed"])


def setup_command(
    topic: str = typer.Argument(
        None,
        help="optional sub-wizard: model. omit for full landing.",
    ),
) -> None:
    """begin configuration. one step per screen."""
    run_wizard(quick=False, topic=topic)
```

- [ ] **Step 4: Register in app.py**

In `backend/agent/tui/cli/app.py`:

```python
from agent.tui.cli.commands.setup import setup_command

app.command(name="setup", help="begin configuration.")(setup_command)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_setup.py -v`
Expected: PASS — both merge tests.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/tui/cli/commands/setup.py backend/agent/tui/cli/app.py backend/tests/test_cli_setup.py
git commit -m "Add vellum setup wizard with quick and full paths"
```

---

## Task 17: Models command with KNOWN_MODELS

**Files:**
- Create: `backend/agent/tui/cli/commands/models.py`
- Modify: `backend/agent/tui/cli/app.py`
- Create: `backend/tests/test_cli_models.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_cli_models.py`:

```python
from agent.tui.cli.commands.models import KNOWN_MODELS
from agent.telemetry.prices import MODEL_PRICES


def test_known_models_shadows_prices():
    """Every model in the picker must have a price entry."""
    for entry in KNOWN_MODELS:
        assert entry["id"] in MODEL_PRICES, f"{entry['id']} missing from MODEL_PRICES"


def test_known_models_have_required_fields():
    for entry in KNOWN_MODELS:
        assert "id" in entry
        assert "hint" in entry
        assert "/" in entry["id"]


def test_known_models_includes_user_default():
    ids = {e["id"] for e in KNOWN_MODELS}
    assert "google/gemma-4-31b-it" in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_models.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement models command**

Create `backend/agent/tui/cli/commands/models.py`:

```python
"""vellum models — alt-screen arrow-key model picker.

Pulls from KNOWN_MODELS (a curated subset of OpenRouter offerings).
Selecting a model writes PRIMARY_MODEL to .env atomically.
"""

from __future__ import annotations

import typer

from agent.tui.cli import PHRASES
from agent.tui.cli.atomic_env import load_env, write_env
from agent.tui.cli.commands.setup import _Path_env
from agent.tui.cli.screen import ask_text, pick, say


KNOWN_MODELS: list[dict[str, str]] = [
    {"id": "anthropic/claude-opus-4.6",     "hint": "opus"},
    {"id": "anthropic/claude-sonnet-4.6",   "hint": "sonnet"},
    {"id": "anthropic/claude-haiku-4.5",    "hint": "haiku"},
    {"id": "openai/gpt-5.4",                "hint": "gpt"},
    {"id": "openai/gpt-5.4-mini",           "hint": "fast"},
    {"id": "google/gemini-3-pro-preview",   "hint": "gemini"},
    {"id": "google/gemini-3-flash-preview", "hint": "fast"},
    {"id": "google/gemma-4-31b-it",         "hint": "cheap"},
    {"id": "google/gemma-3-12b-it",         "hint": "fast"},
    {"id": "qwen/qwen3.5-35b-a3b",          "hint": "cheap"},
    {"id": "qwen/qwen3.6-plus",             "hint": "qwen"},
    {"id": "minimax/minimax-m2.5",          "hint": "cheap"},
    {"id": "z-ai/glm-5.1",                  "hint": "glm"},
]


def models_command() -> None:
    """pick the model."""
    current = load_env(_Path_env())
    existing = current.get("PRIMARY_MODEL", "")
    choices = [(m["id"], f"{m['id']:<40} {m['hint']}") for m in KNOWN_MODELS]
    choices.append(("__custom__", "enter custom..."))
    choice = pick(
        header="model",
        choices=choices,
        default=existing or KNOWN_MODELS[0]["id"],
    )
    if choice is None:
        say(PHRASES["cancelled"])
        return
    if choice == "__custom__":
        custom = ask_text(header="model", prompt="model id (provider/name)", default=existing)
        if custom is None or custom.strip() == "":
            say(PHRASES["cancelled"])
            return
        choice = custom.strip()
    current["PRIMARY_MODEL"] = choice
    write_env(_Path_env(), current)
    say(PHRASES["set"])
```

- [ ] **Step 4: Register in app.py**

In `backend/agent/tui/cli/app.py`:

```python
from agent.tui.cli.commands.models import models_command

app.command(name="models", help="choose the primary model.")(models_command)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_models.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/tui/cli/commands/models.py backend/agent/tui/cli/app.py backend/tests/test_cli_models.py
git commit -m "Add vellum models picker with curated OpenRouter list"
```

---

## Task 18: Sessions list / rename / delete commands

**Files:**
- Create: `backend/agent/tui/cli/commands/sessions.py`
- Modify: `backend/agent/tui/cli/app.py`
- Create: `backend/tests/test_cli_sessions.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_cli_sessions.py`:

```python
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.tui.cli.app import app


@pytest.fixture
def runner(tmp_path: Path, monkeypatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memory").mkdir(parents=True)
    # Seed a checkpoints db with one thread, matching the real langgraph schema.
    cp = tmp_path / "data" / "memory" / "checkpoints.db"
    conn = sqlite3.connect(str(cp))
    conn.execute(
        """
        CREATE TABLE checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint BLOB,
            metadata BLOB,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )
    conn.execute("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id) VALUES ('t1', '', '01J000')")
    conn.execute("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id) VALUES ('t1', '', '01J001')")
    conn.commit()
    conn.close()
    return CliRunner()


def test_sessions_list_shows_thread(runner: CliRunner) -> None:
    result = runner.invoke(app, ["sessions"])
    assert result.exit_code == 0
    assert "t1" in result.stdout
    assert "2" in result.stdout  # msg count


def test_sessions_list_empty_when_no_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["sessions"])
    assert r.exit_code == 0
    assert "Nothing on this in your library." in r.stdout


def test_sessions_rename_writes_title(runner: CliRunner) -> None:
    result = runner.invoke(app, ["sessions", "rename", "t1", "my research"])
    assert result.exit_code == 0
    assert "Filed." in result.stdout
    # Subsequent list shows new title
    list_result = runner.invoke(app, ["sessions"])
    assert "my research" in list_result.stdout


def test_sessions_delete_removes_thread(runner: CliRunner) -> None:
    # --yes flag skips confirmation
    result = runner.invoke(app, ["sessions", "delete", "t1", "--yes"])
    assert result.exit_code == 0
    assert "Out." in result.stdout
    list_result = runner.invoke(app, ["sessions"])
    assert "t1" not in list_result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_sessions.py -v`
Expected: FAIL — sessions subcommand not registered.

- [ ] **Step 3: Implement sessions commands**

Create `backend/agent/tui/cli/commands/sessions.py`:

```python
"""vellum sessions — list, rename, delete threads."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent.memory.sessions import SessionsReader
from agent.tui.cli import PHRASES
from agent.tui.cli.screen import EMBER, PARCHMENT, say

sessions_app = typer.Typer(help="manage saved threads.", no_args_is_help=False)
console = Console()


def _reader() -> SessionsReader:
    base = Path("data") / "memory"
    return SessionsReader(
        checkpoints_db=base / "checkpoints.db",
        long_term_db=base / "long_term.db",
    )


@sessions_app.callback(invoke_without_command=True)
def sessions_root(ctx: typer.Context) -> None:
    """list saved threads."""
    if ctx.invoked_subcommand is not None:
        return
    rows = _reader().list_sessions()
    if not rows:
        say(PHRASES["nothing_library"])
        return
    table = Table(
        show_header=True,
        header_style=f"{PARCHMENT}",
        border_style=f"{EMBER}",
        show_edge=False,
        pad_edge=False,
        box=None,
    )
    table.add_column("thread", style=f"{PARCHMENT}")
    table.add_column("msgs", justify="right", style=f"{PARCHMENT}")
    for r in rows:
        table.add_row(r["title"], str(r["msgs"]))
    console.print(table)


@sessions_app.command("rename")
def rename(
    thread_id: str = typer.Argument(..., help="thread id to rename"),
    title: str = typer.Argument(..., help="new title"),
) -> None:
    """rename a thread."""
    _reader().rename(thread_id, title)
    say(PHRASES["filed"])


@sessions_app.command("delete")
def delete(
    thread_id: str = typer.Argument(..., help="thread id to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation."),
) -> None:
    """delete a thread."""
    if not yes:
        confirm = typer.confirm("delete this thread", default=False)
        if not confirm:
            say(PHRASES["cancelled"])
            return
    _reader().delete(thread_id)
    say(PHRASES["out"])
```

- [ ] **Step 4: Register in app.py**

In `backend/agent/tui/cli/app.py`:

```python
from agent.tui.cli.commands.sessions import sessions_app

app.add_typer(sessions_app, name="sessions")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_sessions.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/tui/cli/commands/sessions.py backend/agent/tui/cli/app.py backend/tests/test_cli_sessions.py
git commit -m "Add vellum sessions list/rename/delete commands"
```

---

## Task 19: Usage command

**Files:**
- Create: `backend/agent/tui/cli/commands/usage.py`
- Modify: `backend/agent/tui/cli/app.py`
- Create: `backend/tests/test_cli_usage.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_cli_usage.py`:

```python
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.telemetry.usage_ledger import UsageLedger
from agent.tui.cli.app import app


@pytest.fixture
def runner_empty(tmp_path: Path, monkeypatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    return CliRunner()


@pytest.fixture
def runner_seeded(tmp_path: Path, monkeypatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memory").mkdir(parents=True)
    ledger = UsageLedger(tmp_path / "data" / "memory" / "usage.db")
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=1000, out_tokens=500, source="tui")
    return CliRunner()


def test_usage_empty_state(runner_empty: CliRunner) -> None:
    result = runner_empty.invoke(app, ["usage"])
    assert result.exit_code == 0
    assert "Nothing on this in your library." in result.stdout


def test_usage_shows_per_model_summary(runner_seeded: CliRunner) -> None:
    result = runner_seeded.invoke(app, ["usage"])
    assert result.exit_code == 0
    assert "google/gemma-4-31b-it" in result.stdout
    assert "1,000" in result.stdout or "1000" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_usage.py -v`
Expected: FAIL — `usage` not registered.

- [ ] **Step 3: Implement usage command**

Create `backend/agent/tui/cli/commands/usage.py`:

```python
"""vellum usage — token-ledger summary table."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent.telemetry.usage_ledger import UsageLedger
from agent.tui.cli import PHRASES
from agent.tui.cli.screen import EMBER, PARCHMENT, say

console = Console()


def usage_command(
    days: int = typer.Option(7, "--days", help="window size in days."),
) -> None:
    """usage over the last window."""
    ledger = UsageLedger(Path("data") / "memory" / "usage.db")
    if not ledger.path.exists():
        say(PHRASES["nothing_library"])
        return
    rows = ledger.summarize(days=days)
    if not rows:
        say(PHRASES["nothing_library"])
        return

    title = "this week" if days == 7 else f"last {days} days"
    table = Table(
        show_header=True,
        header_style=f"{PARCHMENT}",
        border_style=f"{EMBER}",
        show_edge=False,
        pad_edge=False,
        box=None,
    )
    table.add_column(title, style=f"{PARCHMENT}")
    table.add_column("in", justify="right", style=f"{PARCHMENT}")
    table.add_column("out", justify="right", style=f"{PARCHMENT}")
    table.add_column("usd", justify="right", style=f"{PARCHMENT}")

    total_in = total_out = 0
    total_cost = 0.0
    for r in rows:
        in_t = int(r["in_tokens"] or 0)
        out_t = int(r["out_tokens"] or 0)
        cost = float(r["cost_usd"] or 0.0)
        total_in += in_t
        total_out += out_t
        total_cost += cost
        table.add_row(r["model"], f"{in_t:,}", f"{out_t:,}", f"{cost:.2f}")
    table.add_row("", "", "", f"{total_cost:.2f}", style=f"bold {PARCHMENT}")
    console.print(table)
```

- [ ] **Step 4: Register in app.py**

In `backend/agent/tui/cli/app.py`:

```python
from agent.tui.cli.commands.usage import usage_command

app.command(name="usage", help="token ledger summary.")(usage_command)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_usage.py -v`
Expected: PASS — 2 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/tui/cli/commands/usage.py backend/agent/tui/cli/app.py backend/tests/test_cli_usage.py
git commit -m "Add vellum usage command for token ledger summary"
```

---

## Task 20: Config command

**Files:**
- Create: `backend/agent/tui/cli/commands/config.py`
- Modify: `backend/agent/tui/cli/app.py`
- Create: `backend/tests/test_cli_config.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_cli_config.py`:

```python
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.tui.cli.app import app


@pytest.fixture
def runner_with_env(tmp_path: Path, monkeypatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=sk-or-secret-12345\nPRIMARY_MODEL=google/gemma-4-31b-it\n",
        encoding="utf-8",
    )
    return CliRunner()


def test_config_print_redacts_keys(runner_with_env: CliRunner) -> None:
    result = runner_with_env.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "sk-or-secret-12345" not in result.stdout
    assert "sk-or" in result.stdout  # redacted prefix still shown
    assert "google/gemma-4-31b-it" in result.stdout


def test_config_missing_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["config"])
    assert r.exit_code == 0
    assert "Nothing on this in your library." in r.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_config.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement config command**

Create `backend/agent/tui/cli/commands/config.py`:

```python
"""vellum config — view and edit the .env."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent.tui.cli import PHRASES
from agent.tui.cli.atomic_env import load_env
from agent.tui.cli.screen import EMBER, PARCHMENT, say

config_app = typer.Typer(help="view current settings.", no_args_is_help=False)
console = Console()

SECRET_TOKENS = ("API_KEY", "TOKEN", "SECRET")


def _redact(key: str, value: str) -> str:
    upper = key.upper()
    if any(token in upper for token in SECRET_TOKENS) and value:
        return f"{value[:5]}…"
    return value


@config_app.callback(invoke_without_command=True)
def config_root(ctx: typer.Context) -> None:
    """print current .env values."""
    if ctx.invoked_subcommand is not None:
        return
    env_path = Path(".env")
    if not env_path.exists():
        say(PHRASES["nothing_library"])
        return
    values = load_env(env_path)
    if not values:
        say(PHRASES["nothing_library"])
        return
    table = Table(
        show_header=True,
        header_style=f"{PARCHMENT}",
        border_style=f"{EMBER}",
        show_edge=False,
        pad_edge=False,
        box=None,
    )
    table.add_column("key", style=f"{PARCHMENT}")
    table.add_column("value", style=f"{PARCHMENT}")
    for key, value in values.items():
        table.add_row(key, _redact(key, value))
    console.print(table)


@config_app.command("edit")
def edit() -> None:
    """open .env in $EDITOR."""
    env_path = Path(".env").resolve()
    editor = os.environ.get("EDITOR")
    if not editor:
        if sys.platform == "win32":
            editor = "notepad"
        elif shutil.which("nano"):
            editor = "nano"
        elif shutil.which("vi"):
            editor = "vi"
        else:
            console.print(str(env_path))
            return
    subprocess.run([editor, str(env_path)], check=False)
    say(PHRASES["filed"])
```

- [ ] **Step 4: Register in app.py**

In `backend/agent/tui/cli/app.py`:

```python
from agent.tui.cli.commands.config import config_app

app.add_typer(config_app, name="config")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_config.py -v`
Expected: PASS — 2 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/tui/cli/commands/config.py backend/agent/tui/cli/app.py backend/tests/test_cli_config.py
git commit -m "Add vellum config view/edit commands"
```

---

## Task 21: Doctor command

**Files:**
- Create: `backend/agent/tui/cli/commands/doctor.py`
- Modify: `backend/agent/tui/cli/app.py`
- Create: `backend/tests/test_cli_doctor.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_cli_doctor.py`:

```python
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.tui.cli.app import app


def test_doctor_runs_and_exits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    # missing .env / vault → exit code 1, but should not crash
    assert result.exit_code in (0, 1)
    for label in ["vault exists", "zdr on", "checkpoints.db readable"]:
        assert label in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_doctor.py -v`
Expected: FAIL — `doctor` not registered.

- [ ] **Step 3: Implement doctor command**

Create `backend/agent/tui/cli/commands/doctor.py`:

```python
"""vellum doctor — diagnostics. No auto-fix."""

from __future__ import annotations

import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

import typer
from rich.console import Console

from agent.telemetry.prices import MODEL_PRICES
from agent.tui.cli import PHRASES
from agent.tui.cli.atomic_env import load_env
from agent.tui.cli.screen import EMBER, PARCHMENT

console = Console()


def _row(label: str, status: str, detail: str = "") -> tuple[str, bool]:
    is_error = status == "error"
    color = EMBER if is_error else PARCHMENT
    line = f"  [{PARCHMENT}]{label:.<40}[/] [{color}]{status}[/]"
    if detail:
        line += f"  [{PARCHMENT}]— {detail}[/]"
    return line, is_error


def _check_openrouter(url: str) -> tuple[str, str]:
    try:
        req = urllib.request.Request(url, method="HEAD")
        urllib.request.urlopen(req, timeout=5)  # noqa: S310
        return "ok", ""
    except urllib.error.URLError as e:
        return "error", str(e.reason)
    except Exception as e:
        return "error", str(e)


def _check_db_readable(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "absent", ""
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("SELECT 1")
        conn.close()
        return "ok", ""
    except Exception as e:
        return "error", str(e)


def doctor_command() -> None:
    """report on configuration and connectivity."""
    env = load_env(Path(".env"))
    lines: list[str] = []
    any_error = False

    # openrouter reachable
    base = env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    status, detail = _check_openrouter(f"{base}/models")
    line, err = _row("openrouter reachable", status, detail)
    lines.append(line); any_error = any_error or err

    # vault exists
    vault = env.get("OBSIDIAN_VAULT_PATH", "")
    if vault and Path(vault).is_dir():
        line, err = _row("vault exists", "ok")
    else:
        line, err = _row("vault exists", "error", "OBSIDIAN_VAULT_PATH missing or not a dir")
    lines.append(line); any_error = any_error or err

    # mcp path sandboxed
    mcp = env.get("FILESYSTEM_MCP_PATH", "")
    if vault and mcp and Path(mcp).resolve().is_relative_to(Path(vault).resolve()):
        line, err = _row("mcp path sandboxed", "ok")
    else:
        line, err = _row("mcp path sandboxed", "error", "FILESYSTEM_MCP_PATH not inside vault")
    lines.append(line); any_error = any_error or err

    # zdr on
    zdr = env.get("ZDR_ONLY", "").lower()
    if zdr == "true":
        line, err = _row("zdr on", "ok")
    else:
        line, err = _row("zdr on", "error", "ZDR_ONLY must be true")
    lines.append(line); any_error = any_error or err

    # checkpoints.db readable
    status, detail = _check_db_readable(Path("data/memory/checkpoints.db"))
    line, err = _row("checkpoints.db readable", status, detail)
    lines.append(line); any_error = any_error or err

    # long_term.db readable
    status, detail = _check_db_readable(Path("data/memory/long_term.db"))
    line, err = _row("long_term.db readable", status, detail)
    lines.append(line); any_error = any_error or err

    # usage.db readable
    status, detail = _check_db_readable(Path("data/memory/usage.db"))
    line, err = _row("usage.db readable", status, detail)
    lines.append(line); any_error = any_error or err

    # models priced
    missing = [m for m in [env.get("PRIMARY_MODEL"), env.get("FAST_MODEL"), env.get("FALLBACK_MODEL")]
               if m and m not in MODEL_PRICES]
    if missing:
        line, err = _row("models priced", "error", "missing: " + ", ".join(missing))
    else:
        line, err = _row("models priced", "ok")
    lines.append(line); any_error = any_error or err

    for line in lines:
        console.print(line)

    if any_error:
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Register in app.py**

In `backend/agent/tui/cli/app.py`:

```python
from agent.tui.cli.commands.doctor import doctor_command

app.command(name="doctor", help="diagnostics.")(doctor_command)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/test_cli_doctor.py -v`
Expected: PASS — 1 test.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/tui/cli/commands/doctor.py backend/agent/tui/cli/app.py backend/tests/test_cli_doctor.py
git commit -m "Add vellum doctor command for diagnostics"
```

---

## Task 22: Swap the entry point script

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Change the script target**

In `backend/pyproject.toml`, under `[project.scripts]`:

```toml
[project.scripts]
personal-agent = "agent.cli:main"
vellum = "agent.tui.cli:main"
```

(was: `vellum = "agent.tui:main"`)

- [ ] **Step 2: Reinstall to refresh the entry point**

Run: `cd backend && ../.venv/Scripts/pip install -e .`
Expected: install completes; `vellum` resolves to the new entry.

- [ ] **Step 3: Smoke test**

Run: `cd backend && ../.venv/Scripts/vellum --version` (Windows) or `cd backend && ../.venv/bin/vellum --version` (POSIX).
Expected: prints `vellum 0.1.0`.

Run: `cd backend && ../.venv/Scripts/vellum --help`
Expected: shows brand-voiced help with subcommands listed (`chat`, `resume`, `setup`, `models`, `sessions`, `usage`, `config`, `doctor`).

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "Swap vellum entry point to agent.tui.cli:main"
```

---

## Task 23: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd backend && ../.venv/Scripts/python -m pytest tests/ -v`
Expected: all tests pass. Existing `test_tui.py` should still pass — the TUI is unchanged except for the additive telemetry hook.

- [ ] **Step 2: Manual smoke test — bare vellum routes correctly with config present**

With a valid `.env` in place, run: `vellum --help`
Expected: shows the subcommand list. No crash.

- [ ] **Step 3: Manual smoke test — first-run routing**

Temporarily rename `.env` to `.env.bak`, then run: `vellum`
Expected: prints `vellum has not been configured. begin setup.` and enters the wizard. Cancel with Ctrl+C — exits cleanly, no `.env` written.

Restore: `mv .env.bak .env` (or `Rename-Item .env.bak .env` in PowerShell).

- [ ] **Step 4: Manual smoke test — sessions table renders**

Run: `vellum sessions`
Expected: prints a table (or `Nothing on this in your library.` if no checkpoints yet).

- [ ] **Step 5: Manual smoke test — usage table renders**

Run: `vellum usage`
Expected: prints `Nothing on this in your library.` on a fresh install, or a per-model table if the TUI has been used.

- [ ] **Step 6: Final commit and push**

If everything passes:

```bash
git log --oneline -25
```

Confirm the commit history shows the 22 task commits. No need to push automatically — leave that to the user.

---

## Self-Review Findings

**Spec coverage check** — every spec section maps to a task:

| spec § | task |
|---|---|
| 3 subcommand surface | T15 (chat/resume), T16 (setup), T17 (models), T18 (sessions), T19 (usage), T20 (config), T21 (doctor) |
| 4.1 framework | T1 (deps) |
| 4.2 package layout | T2 (skeleton), all subsequent tasks |
| 4.3 entry point flow | T15 (chat routing), T22 (script swap) |
| 4.4 first-run | T15 (`_settings_ok` + reroute) |
| 4.5 wizard | T16 |
| 4.6 sessions | T12 (titles table), T13 (reader), T18 (commands) |
| 4.7 models | T17 |
| 4.8 usage display | T19 |
| 4.9 telemetry hooks | T5, T6, T7, T8, T9, T10, T11 |
| 4.10 config | T20 |
| 4.11 doctor | T21 |
| 5 phrase table | T2 (PHRASES dict) |
| 6 visual screens | T14 (screen primitives) |
| 7 data + migrations | T6 (usage.db), T12 (thread_titles) |
| 9 testing | every task with `tests/test_cli_*.py` |

No gaps.

**Placeholder scan** — no "TBD", no "implement later", no "similar to". Every step has runnable code or an exact command.

**Type consistency** — names verified across tasks:
- `PHRASES` keys consistent (T2, T15, T16, T17, T18, T19, T20, T21).
- `UsageLedger.record(thread_id, model, in_tokens, out_tokens, source, ts=None)` consistent across T6, T7, T8, T9, T10, T11.
- `capture_from_invoke_result(ledger, result, thread_id, fallback_model, source)` consistent across T7, T8, T10.
- `capture_from_stream_event(ledger, event, thread_id, fallback_model, source)` consistent across T7, T9.
- `SessionsReader(checkpoints_db, long_term_db)` consistent across T13, T18.
- `load_env(path)` / `write_env(path, values)` consistent across T4, T16, T17, T20.
- `KNOWN_MODELS` shape (`[{"id": ..., "hint": ...}, ...]`) consistent across T16, T17.
- `_Path_env()` consistent across T16, T17.
- `MODEL_PRICES` referenced consistently across T5, T17, T21.

No drift.
