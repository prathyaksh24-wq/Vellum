from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from agent.llm.routing.chat_model import RoutedChatModel


class FakeEngine:
    def __init__(self) -> None:
        self.last_primary = ""
        self.last_tools = []
        self.last_thread_id = ""

    async def ainvoke(self, *, primary_model, tools, **kwargs):
        self.last_primary = primary_model
        self.last_tools = list(tools)
        self.last_thread_id = str(kwargs.get("thread_id") or "")
        return AIMessage(
            content="",
            tool_calls=[{"name": "lookup", "args": {}, "id": "call-1"}],
        )

    async def astream(self, *, primary_model, tools, **kwargs):
        self.last_primary = primary_model
        self.last_tools = list(tools)
        self.last_thread_id = str(kwargs.get("thread_id") or "")
        yield AIMessageChunk(content="hello")


def test_routed_model_binds_tools_and_resolves_primary_per_invocation() -> None:
    async def scenario() -> None:
        engine = FakeEngine()
        selected = {"model": "google/primary"}
        model = RoutedChatModel(
            engine=engine,
            primary_model_resolver=lambda: selected["model"],
        )
        tool = {
            "type": "function",
            "function": {"name": "lookup", "parameters": {"type": "object"}},
        }
        bound = model.bind_tools([tool])
        result = await bound.ainvoke(
            [HumanMessage(content="use lookup")],
            config={"configurable": {"thread_id": "thread-7"}},
        )

        assert result.tool_calls[0]["name"] == "lookup"
        assert engine.last_tools == [tool]
        assert engine.last_primary == "google/primary"
        assert engine.last_thread_id == "thread-7"

        selected["model"] = "qwen/new-primary"
        await bound.ainvoke([HumanMessage(content="again")])
        assert engine.last_primary == "qwen/new-primary"

    asyncio.run(scenario())


def test_routed_model_preserves_stream_chunks() -> None:
    async def scenario() -> None:
        engine = FakeEngine()
        model = RoutedChatModel(
            engine=engine,
            primary_model_resolver=lambda: "google/primary",
        )

        chunks = [
            chunk
            async for chunk in model.astream(
                [HumanMessage(content="hello")],
                config={"configurable": {"thread_id": "stream-thread"}},
            )
        ]

        assert "".join(str(chunk.content) for chunk in chunks) == "hello"

        assert engine.last_thread_id == "stream-thread"
    asyncio.run(scenario())
