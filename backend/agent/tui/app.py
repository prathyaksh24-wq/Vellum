from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from agent.config import get_settings
from agent.graph.agent import agent
from agent.memory.fts5 import FTS5Memory
from agent.obsidian.ingester import VaultIngester
from agent.privacy.classifier import DataClass, classify
from agent.scheduler.digest import start_scheduler
from agent.telemetry.hooks import capture_from_stream_event
from agent.telemetry.usage_ledger import UsageLedger
from agent.tui.screens import LedgerScreen
from agent.tui.slash_commands import resolve_command
from agent.tui.widgets import LedgerSidebar, MessageList, SlashCommandPalette, ThreadsSidebar, VellumHeader, VellumInput


def thread_config(thread_id: str | None = None) -> dict[str, dict[str, str]]:
    settings = get_settings()
    return {"configurable": {"thread_id": thread_id or settings.thread_id}}


def stream_chunk_text(chunk: Any) -> str:
    if chunk is None:
        return ""
    content = chunk.get("content", "") if isinstance(chunk, dict) else getattr(chunk, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


class HelpOverlay(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "close")]

    def compose(self) -> ComposeResult:
        yield Static(
            "[italic #ece6db]vellum keys[/]\n\n"
            "enter             send message\n"
            "shift+enter       newline in input\n"
            "esc               close panel, then focus input\n\n"
            "[                  threads\n"
            "]                  ledger\n"
            "ctrl+n             new thread\n"
            "ctrl+k             jump to thread\n"
            "ctrl+p             previous thread\n"
            "ctrl+shift+p       next thread\n\n"
            "ctrl+s             save response to Agent/Saved/\n"
            "ctrl+r             regenerate response\n"
            "ctrl+e             explore footnotes\n"
            "ctrl+y             yank response\n\n"
            "ctrl+z             zen mode\n"
            "ctrl+w             compose in editor\n\n"
            "f1                 help\n"
            "f2                 ledger view\n"
            "f3                 faculties\n"
            "f4                 model picker\n\n"
            "[#716d68]esc closes[/]",
            classes="help",
        )

    def action_dismiss(self) -> None:
        self.dismiss()


class VellumTuiApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "vellum"
    SUB_TITLE = "trained on you"

    BINDINGS = [
        ("escape", "focus_input", "input"),
        ("[", "toggle_threads", "threads"),
        ("]", "toggle_ledger", "ledger"),
        ("ctrl+n", "new_thread", "new thread"),
        ("ctrl+k", "jump_thread", "jump thread"),
        ("ctrl+p", "previous_thread", "previous thread"),
        ("ctrl+shift+p", "next_thread", "next thread"),
        ("ctrl+s", "save_latest", "save"),
        ("ctrl+r", "regenerate", "regenerate"),
        ("ctrl+e", "explore_footnote", "footnotes"),
        ("ctrl+y", "yank_latest", "yank"),
        ("ctrl+z", "toggle_zen", "zen"),
        ("ctrl+w", "compose_editor", "editor"),
        ("f1", "help", "help"),
        ("f2", "ledger_view", "ledger view"),
        ("f3", "faculties", "faculties"),
        ("f4", "model_picker", "model"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.settings = get_settings()
        self.active_thread_id = self.settings.thread_id
        self.last_user_input = ""
        self.last_tool_names: list[str] = []
        self.streaming_task: asyncio.Task[None] | None = None
        self.memory = FTS5Memory()
        self.usage_ledger = UsageLedger(Path("data/memory/usage.db"))

    def compose(self) -> ComposeResult:
        yield Vertical(
            VellumHeader(id="header"),
            Horizontal(
                ThreadsSidebar(id="threads"),
                Vertical(
                    MessageList(id="messages"),
                    Vertical(
                        SlashCommandPalette(),
                        Static("--------------------------------------------------------------------------------", id="input-rule-top"),
                        VellumInput(),
                        Static("--------------------------------------------------------------------------------", id="input-rule-bottom"),
                        Static("faculties  .  model  .  memory  .  ledger        0 tokens    trained on you", id="footer-line"),
                        id="input-wrap",
                    ),
                    id="stage",
                ),
                LedgerSidebar(id="ledger"),
                id="body",
            ),
            id="root",
        )

    def on_mount(self) -> None:
        start_scheduler()
        header = self.query_one(VellumHeader)
        header.model_name = self.settings.primary_model
        header.thread_title = self.active_thread_id
        self.query_one(SlashCommandPalette).hide()
        self.query_one(VellumInput).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        palette = self.query_one(SlashCommandPalette)
        value = event.value.strip()
        if value.startswith("/"):
            palette.show_for(value.split(" ", 1)[0])
        else:
            palette.hide()

    def on_key(self, event) -> None:
        palette = self.query_one(SlashCommandPalette)
        if not palette.display:
            return
        if event.key in {"down", "j"}:
            palette.move_selection(1)
            event.stop()
        elif event.key in {"up", "k"}:
            palette.move_selection(-1)
            event.stop()
        elif event.key == "escape":
            palette.hide()
            event.stop()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            event.input.value = ""
            return
        palette = self.query_one(SlashCommandPalette)
        if palette.display:
            selected = palette.selected_command()
            if selected is not None and selected.accepts_argument and " " not in value:
                event.input.value = f"{selected.name} "
                event.input.cursor_position = len(event.input.value)
                palette.hide()
                return
            if selected is not None and value.split(" ", 1)[0].casefold() != selected.name.casefold():
                value = selected.name
        event.input.value = ""
        palette.hide()
        if await self._handle_slash_command(value):
            return
        await self.send_prompt(value)

    async def send_prompt(self, prompt: str) -> None:
        if self.streaming_task and not self.streaming_task.done():
            return
        self.last_user_input = prompt
        self.last_tool_names = []
        self._set_attending(True)
        self._tint_input(prompt)
        messages = self.query_one(MessageList)
        messages.add_user_message(escape(prompt))
        messages.begin_assistant_message()
        self.streaming_task = asyncio.create_task(self._stream_agent(prompt))
        await self.streaming_task

    async def _stream_agent(self, prompt: str) -> None:
        messages = self.query_one(MessageList)
        try:
            stream = agent.astream_events(
                {"messages": [{"role": "user", "content": prompt}]},
                config=thread_config(self.active_thread_id),
                version="v2",
            )
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
            messages.finish_assistant_message(self.last_tool_names)
        except Exception:
            messages.append_assistant_token("Unreachable.")
            messages.finish_assistant_message()
        finally:
            self._set_attending(False)
            self.query_one(VellumInput).focus()

    async def _handle_slash_command(self, value: str) -> bool:
        command = value.casefold()
        slash_command = resolve_command(value)
        if slash_command is None:
            return False
        if slash_command.action == "quit":
            self.exit()
            return True
        if slash_command.action == "ledger":
            self.action_ledger_view()
            return True
        if slash_command.action == "thread":
            new_thread = value.split(" ", 1)[1].strip()
            if new_thread:
                self.active_thread_id = new_thread
                header = self.query_one(VellumHeader)
                header.thread_title = new_thread
            else:
                self.notify("usage: /thread <id>", timeout=2)
            return True
        if slash_command.action == "help":
            self.action_help()
            return True
        if slash_command.action == "new_thread":
            self.action_new_thread()
            return True
        if slash_command.action == "model":
            self.action_model_picker()
            return True
        if slash_command.action == "faculties":
            self.action_faculties()
            return True
        if slash_command.action == "memory":
            rows = self.memory.recent_documents(limit=15)
            text = "\n".join(f"i. {row['content'][:240]}" for row in rows) if rows else "No indexed exchanges yet."
            self.query_one(MessageList).add_vellum_note(escape(text), source="memory")
            return True
        if slash_command.action == "reindex":
            self.query_one(MessageList).add_vellum_note("Reading.", source="library")
            count = await asyncio.to_thread(VaultIngester().ingest, True)
            self.query_one(MessageList).add_vellum_note(f"Indexed {count} chunks.", source="library")
            return True
        return False

    def _set_attending(self, attending: bool) -> None:
        self.query_one(VellumHeader).attending = attending

    def _tint_input(self, prompt: str) -> None:
        data_class, _reason = classify(prompt)
        top = self.query_one("#input-rule-top", Static)
        bottom = self.query_one("#input-rule-bottom", Static)
        if data_class == DataClass.RED:
            color = "[#d97746]"
        elif data_class == DataClass.YELLOW:
            color = "[#a76645]"
        else:
            color = "[#24211f]"
        rule = f"{color}--------------------------------------------------------------------------------[/]"
        top.update(rule)
        bottom.update(rule)

    def action_focus_input(self) -> None:
        self.query_one(VellumInput).focus()

    def action_toggle_threads(self) -> None:
        self.query_one(ThreadsSidebar).toggle_open()

    def action_toggle_ledger(self) -> None:
        self.query_one(LedgerSidebar).toggle_open()

    def action_new_thread(self) -> None:
        self.active_thread_id = "untitled"
        self.query_one(VellumHeader).thread_title = "untitled"
        self.query_one(MessageList).show_landing()

    def action_jump_thread(self) -> None:
        self.notify("thread search pending", timeout=2)

    def action_previous_thread(self) -> None:
        self.notify("previous thread pending", timeout=2)

    def action_next_thread(self) -> None:
        self.notify("next thread pending", timeout=2)

    def action_save_latest(self) -> None:
        response = self.query_one(MessageList).latest_assistant_response()
        if not response:
            self.notify("Nothing to file.", timeout=2)
            return
        target_dir = self.settings.obsidian_vault_path / "Agent" / "Saved"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"vellum-{self.active_thread_id.replace(' ', '-')}.md"
        path = target_dir / filename
        path.write_text(response + "\n", encoding="utf-8")
        self.notify(f"Filed. {path.name}", timeout=2)

    async def action_regenerate(self) -> None:
        if self.last_user_input:
            await self.send_prompt(self.last_user_input)

    def action_explore_footnote(self) -> None:
        self.notify("footnotes pending", timeout=2)

    def action_yank_latest(self) -> None:
        response = self.query_one(MessageList).latest_assistant_response()
        if not response:
            self.notify("Nothing to yank.", timeout=2)
            return
        try:
            self.copy_to_clipboard(response)
            self.notify("Copied.", timeout=2)
        except Exception:
            self.notify("Clipboard unavailable.", timeout=2)

    def action_toggle_zen(self) -> None:
        self.query_one(VellumHeader).display = not self.query_one(VellumHeader).display
        self.query_one("#input-wrap").display = not self.query_one("#input-wrap").display
        self.query_one(ThreadsSidebar).remove_class("open")
        self.query_one(LedgerSidebar).remove_class("open")

    def action_compose_editor(self) -> None:
        self.notify("editor compose pending", timeout=2)

    def action_help(self) -> None:
        self.push_screen(HelpOverlay())

    def action_ledger_view(self) -> None:
        self.push_screen(LedgerScreen())

    def action_faculties(self) -> None:
        self.notify("faculties pending", timeout=2)

    def action_model_picker(self) -> None:
        self.notify(self.settings.primary_model, timeout=3)

    async def on_unmount(self) -> None:
        close = getattr(agent, "aclose", None)
        if close is not None:
            await close()
