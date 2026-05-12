"""Core ReAct agent using LangGraph's create_react_agent."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

from agent.config import get_settings
from agent.tools.apify import search_amazon
from agent.tools.filesystem import list_files, read_file
from agent.tools.obsidian_write import append_to_note, create_note
from agent.tools.vault_search import search_my_notes
from agent.tools.web import web_search

VELLUM_SYSTEM_PROMPT = """You are Vellum, a self-learning personal archivist for one person.

Tools:
1. search_my_notes - Search the user's private Obsidian vault. Always use this first.
2. web_search - Search the web only when vault search is insufficient and the query is public/current.
3. search_amazon - Search Amazon only when the user asks about buying, pricing, or product comparisons.
4. read_file - Read a specific local file.
5. list_files - List files in a vault directory.
6. create_note - Create a new Obsidian note.
7. append_to_note - Append to an existing Obsidian note.

Rules:
- Always search the vault first.
- Distinguish vault-grounded, inferred, and external knowledge. Never present one as another.
- If the vault does not contain enough support, say: "Nothing on this in your library."
- Never make up facts not present in retrieved context or tool results.
- Be plain, restrained, and useful. Do not flatter.
- Reference sources when relevant.
- For private folder content, paraphrase and summarize rather than quoting raw text.
- Treat Amazon/Apify results as private and summarize without exposing raw scraped data.
- Offer to save useful insights when appropriate.
- Do not write outside the Agent/ folder in the Obsidian vault.
"""

CHECKPOINT_DB = Path("data/memory/checkpoints.db")


def build_llm(model: str | None = None):
    settings = get_settings()
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("langchain-openai is required to build the ReAct agent.") from exc

    return ChatOpenAI(
        model=model or settings.primary_model,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        temperature=0.3,
        max_tokens=2048,
        default_headers={
            "HTTP-Referer": "http://localhost",
            "X-Title": "PersonalAgent",
        },
        extra_body={
            "provider": {
                "data_collection": "deny",
                "order": ["Fireworks", "Together", "DeepInfra"],
                "zdr": settings.zdr_only,
            }
        },
    )


def build_checkpointer() -> SqliteSaver:
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


async def build_async_checkpointer() -> AsyncSqliteSaver:
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    try:
        import aiosqlite
    except ImportError as exc:
        raise RuntimeError("aiosqlite is required for async LangGraph checkpointing.") from exc

    conn = await aiosqlite.connect(str(CHECKPOINT_DB))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver


def build_agent(model: str | None = None):
    return create_react_agent(
        model=build_llm(model),
        tools=[
            search_my_notes,
            web_search,
            search_amazon,
            read_file,
            list_files,
            create_note,
            append_to_note,
        ],
        checkpointer=build_checkpointer(),
        prompt=VELLUM_SYSTEM_PROMPT,
    )


async def build_async_agent(model: str | None = None):
    return create_react_agent(
        model=build_llm(model),
        tools=[
            search_my_notes,
            web_search,
            search_amazon,
            read_file,
            list_files,
            create_note,
            append_to_note,
        ],
        checkpointer=await build_async_checkpointer(),
        prompt=VELLUM_SYSTEM_PROMPT,
    )


class LazyAgent:
    def __init__(self):
        self._agent = None
        self._async_agent = None

    def _get(self):
        if self._agent is None:
            self._agent = build_agent()
        return self._agent

    async def _aget(self):
        if self._async_agent is None:
            self._async_agent = await build_async_agent()
        return self._async_agent

    async def ainvoke(self, *args, **kwargs):
        return await (await self._aget()).ainvoke(*args, **kwargs)

    async def astream_events(self, *args, **kwargs):
        target = await self._aget()
        async for event in target.astream_events(*args, **kwargs):
            yield event

    def invoke(self, *args, **kwargs):
        return self._get().invoke(*args, **kwargs)

    async def aclose(self) -> None:
        if self._async_agent is not None:
            checkpointer = getattr(self._async_agent, "checkpointer", None)
            conn = getattr(checkpointer, "conn", None)
            if conn is not None:
                await conn.close()
            self._async_agent = None


agent = LazyAgent()
