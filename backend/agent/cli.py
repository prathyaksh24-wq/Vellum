"""Rich terminal CLI for the ReAct personal agent."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from pathlib import Path

from agent.config import get_settings
from agent.graph.agent import agent
from agent.memory.long_term import LongTermMemory
from agent.obsidian.ingester import VaultIngester
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber
from agent.scheduler.digest import start_scheduler
from agent.telemetry.hooks import capture_from_invoke_result
from agent.telemetry.usage_ledger import UsageLedger
from agent.tools.obsidian_write import store_qa_pair

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)
console = Console()
memory = LongTermMemory()
_LEDGER = UsageLedger(Path("data/memory/usage.db"))


def _record_chat_usage(result: dict, cfg: dict) -> None:
    thread_id = cfg.get("configurable", {}).get("thread_id", settings.thread_id)
    capture_from_invoke_result(
        ledger=_LEDGER,
        result=result,
        thread_id=thread_id,
        fallback_model=settings.primary_model,
        source="cli",
    )

HELP_TEXT = """
[bold cyan]Commands:[/bold cyan]
  [green]/memory[/green]      - Show recently learned facts
  [green]/reindex[/green]     - Re-index your Obsidian vault
  [green]/thread <id>[/green] - Switch conversation thread
  [green]/help[/green]        - Show this message
  [green]/quit[/green]        - Exit
"""


def thread_config(thread_id: str | None = None) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id or settings.thread_id}}


def _message_content(message: Any) -> str:
    if message is None:
        return ""
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    return str(content or "").strip()


def _tool_call_names(messages: list[Any]) -> list[str]:
    names: list[str] = []
    for message in messages:
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        for call in tool_calls or []:
            if isinstance(call, dict):
                name = call.get("name")
            else:
                name = getattr(call, "name", None)
            if name:
                names.append(str(name))
    return names


def render_answer(answer: str, tool_calls: list[str] | None = None) -> Panel:
    subtitle = None
    if tool_calls:
        subtitle = "Tools used: " + " | ".join(tool_calls)
    return Panel(
        Markdown(answer or "No response."),
        title="[bold blue]Agent[/bold blue]",
        subtitle=subtitle,
        border_style="blue",
    )


async def handle_command(
    user_input: str,
    active_console: Console = console,
    *,
    current_thread_config: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    command = user_input.strip()
    normalized = command.casefold()

    if normalized == "/help":
        active_console.print(HELP_TEXT)
        return True, current_thread_config

    if normalized == "/memory":
        facts = memory.get_recent_facts(limit=15)
        body = "\n".join(f"- {fact}" for fact in facts) if facts else "No learned facts yet."
        active_console.print(Panel(body, title="[bold]Recently Learned[/bold]", border_style="yellow"))
        return True, current_thread_config

    if normalized == "/reindex":
        with active_console.status("[yellow]Re-indexing vault...[/yellow]"):
            count = VaultIngester().ingest(force=True)
        active_console.print(f"[green]Vault re-indexed: {count} chunks.[/green]")
        return True, current_thread_config

    if normalized.startswith("/thread "):
        new_thread = command.split(" ", 1)[1].strip()
        if not new_thread:
            active_console.print("[red]Usage: /thread <id>[/red]")
            return True, current_thread_config
        new_config = thread_config(new_thread)
        active_console.print(f"[cyan]Switched to thread: {new_thread}[/cyan]")
        return True, new_config

    return False, current_thread_config


async def chat_loop(
    *,
    active_agent=agent,
    active_console: Console = console,
    prompt=Prompt.ask,
) -> None:
    try:
        active_console.print(
            Panel.fit(
                "[bold cyan]Personal Agent[/bold cyan]\n"
                "[dim]Vault-first | Privacy-first | OpenRouter[/dim]\n"
                "[dim]Type /help for commands[/dim]",
                border_style="cyan",
            )
        )

        active_thread_config = thread_config()

        while True:
            try:
                user_input = prompt("\n[bold green]You[/bold green]")
            except (KeyboardInterrupt, EOFError):
                active_console.print("\n[dim]Goodbye.[/dim]")
                break

            if user_input.strip().casefold() in {"/quit", "/exit", "quit", "exit"}:
                break

            handled, maybe_config = await handle_command(
                user_input,
                active_console,
                current_thread_config=active_thread_config,
            )
            if maybe_config is not None:
                active_thread_config = maybe_config
            if handled:
                continue

            active_console.print()
            try:
                with active_console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                    result = await active_agent.ainvoke(
                        {"messages": [{"role": "user", "content": user_input}]},
                        config=active_thread_config,
                    )
            except Exception as exc:
                active_console.print(f"[red]Error: {exc}[/red]")
                continue

            messages = result.get("messages", []) if isinstance(result, dict) else []
            answer = _message_content(messages[-1] if messages else None) or "No response."
            tool_calls = _tool_call_names(messages)
            _record_chat_usage(result, active_thread_config)
            active_console.print(render_answer(answer, tool_calls))

            if answer and "blocked for privacy" not in answer.casefold():
                asyncio.create_task(_background_learn(user_input, answer))
    finally:
        close = getattr(active_agent, "aclose", None)
        if close is not None:
            await close()


async def chat() -> None:
    start_scheduler()
    await chat_loop()


async def _background_learn(query: str, answer: str) -> None:
    """Store Q&A and extract facts without blocking chat."""
    try:
        data_class, reason = classify(query)
        if data_class == DataClass.RED:
            logger.warning("Skipping background learning for RED query: %s", reason)
            return

        scrubber = PrivacyScrubber()
        clean_query = scrubber.scrub(query)[0] if data_class == DataClass.YELLOW else query
        clean_answer = scrubber.scrub(answer)[0] if data_class == DataClass.YELLOW else answer
        store_qa_pair(clean_query, clean_answer)
        await _extract_facts(clean_query, clean_answer)
    except Exception as exc:
        logger.warning("Background learn failed: %s", exc)


async def _extract_facts(query: str, answer: str) -> None:
    """Extract concise learnable facts from an interaction using the fast model."""
    from agent.llm.openrouter import openrouter_chat

    prompt = f"""Extract 0-2 concise facts worth remembering from this exchange.
Return only a JSON array of short strings. Return [] if nothing notable.

Q: {query}
A: {answer[:400]}

JSON:"""
    try:
        raw = await openrouter_chat(
            system="Extract facts. Return only a JSON array of strings.",
            user=prompt,
            model_override=settings.fast_model,
            max_tokens=150,
        )
        cleaned = raw.strip().replace("```json", "").replace("```", "")
        facts = json.loads(cleaned)
    except Exception as exc:
        logger.debug("Fact extraction skipped: %s", exc)
        return

    if not isinstance(facts, list):
        return
    for fact in facts[:2]:
        if isinstance(fact, str) and len(fact) > 5:
            memory.store_fact(fact, category="interaction")


def main() -> None:
    asyncio.run(chat())


if __name__ == "__main__":
    main()
