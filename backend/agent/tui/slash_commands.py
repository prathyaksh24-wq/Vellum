from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    name: str
    action: str
    description: str
    aliases: tuple[str, ...] = ()
    accepts_argument: bool = False

    def matches(self, query: str) -> bool:
        normalized = query.strip().casefold()
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        candidates = (self.name, *self.aliases)
        return any(candidate.casefold().startswith(normalized) for candidate in candidates)


COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("/help", "help", "show the key map"),
    SlashCommand("/ledger", "ledger", "open usage ledger"),
    SlashCommand("/usage", "ledger", "open usage ledger"),
    SlashCommand("/tokens", "ledger", "open usage ledger"),
    SlashCommand("/memory", "memory", "show recent memory"),
    SlashCommand("/reindex", "reindex", "re-index your library"),
    SlashCommand("/thread", "thread", "switch thread", accepts_argument=True),
    SlashCommand("/new", "new_thread", "start a new thread", aliases=("/new-thread",)),
    SlashCommand("/model", "model", "show active model"),
    SlashCommand("/faculties", "faculties", "show faculties"),
    SlashCommand("/quit", "quit", "close vellum", aliases=("/exit",)),
)


def filter_commands(query: str) -> list[SlashCommand]:
    normalized = query.strip()
    if normalized in {"", "/"}:
        return list(COMMANDS)
    return [command for command in COMMANDS if command.matches(normalized)]


def resolve_command(value: str) -> SlashCommand | None:
    command_name = value.strip().split(" ", 1)[0].casefold()
    for command in COMMANDS:
        candidates = (command.name, *command.aliases)
        if command_name in {candidate.casefold() for candidate in candidates}:
            return command
    return None
