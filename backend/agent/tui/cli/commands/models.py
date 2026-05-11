"""vellum models — alt-screen arrow-key model picker.

Pulls from KNOWN_MODELS (a curated subset of OpenRouter offerings).
Selecting a model writes PRIMARY_MODEL to .env atomically.
"""

from __future__ import annotations

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
