from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from agent import cli


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, payload, config=None):
        self.calls.append((payload, config))
        message = SimpleNamespace(content="Fake answer", tool_calls=[{"name": "search_my_notes"}])
        return {"messages": [message]}


@pytest.mark.parametrize("command", ["/quit", "/exit", "quit", "exit"])
def test_chat_loop_quit_commands(command):
    output = StringIO()
    console = Console(file=output, force_terminal=False)
    prompts = iter([command])

    import asyncio

    asyncio.run(cli.chat_loop(active_agent=FakeAgent(), active_console=console, prompt=lambda _: next(prompts)))

    assert "Personal Agent" in output.getvalue()


def test_chat_loop_invokes_agent_once(monkeypatch):
    output = StringIO()
    console = Console(file=output, force_terminal=False)
    prompts = iter(["What is in my NBA notes?", "/quit"])
    fake_agent = FakeAgent()
    background_calls = []

    async def fake_background(query, answer, thread_id="default"):
        background_calls.append((query, answer, thread_id))

    class DoneTask:
        pass

    def fake_create_task(coro):
        coro.close()
        return DoneTask()

    monkeypatch.setattr(cli, "_background_learn", fake_background)
    monkeypatch.setattr(cli.asyncio, "create_task", fake_create_task)

    import asyncio

    asyncio.run(cli.chat_loop(active_agent=fake_agent, active_console=console, prompt=lambda _: next(prompts)))

    assert len(fake_agent.calls) == 1
    assert fake_agent.calls[0][0]["messages"][0]["content"] == "What is in my NBA notes?"
    assert fake_agent.calls[0][1]["configurable"]["thread_id"]
    assert "Fake answer" in output.getvalue()
    assert "search_my_notes" in output.getvalue()


def test_memory_command_prints_recent_facts(monkeypatch):
    output = StringIO()
    console = Console(file=output, force_terminal=False)

    class FakeMemory:
        def recent_documents(self, limit=15):
            return [{"content": "Q: old\nA: Fact one"}]

    monkeypatch.setattr(cli, "memory", FakeMemory())

    import asyncio

    handled, _ = asyncio.run(cli.handle_command("/memory", console))

    assert handled is True
    assert "Fact one" in output.getvalue()


def test_reindex_command_prints_chunk_count(monkeypatch):
    output = StringIO()
    console = Console(file=output, force_terminal=False)

    class FakeIngester:
        def ingest(self, force=False):
            assert force is True
            return 12

    monkeypatch.setattr(cli, "VaultIngester", FakeIngester)

    import asyncio

    handled, _ = asyncio.run(cli.handle_command("/reindex", console))

    assert handled is True
    assert "12 chunks" in output.getvalue()


def test_thread_command_switches_config():
    output = StringIO()
    console = Console(file=output, force_terminal=False)

    import asyncio

    handled, config = asyncio.run(cli.handle_command("/thread research", console))

    assert handled is True
    assert config["configurable"]["thread_id"] == "research"
