"""vellum setup — Hermes-style wizard with one step per cleared screen."""

from __future__ import annotations

from pathlib import Path

import typer

from agent.tui.cli import PHRASES
from agent.tui.cli.atomic_env import load_env, write_env
from agent.tui.cli.screen import ask_password, ask_text, pick, say


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
