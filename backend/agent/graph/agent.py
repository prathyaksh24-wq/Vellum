"""Core ReAct agent using LangGraph's create_react_agent."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

from agent.config import get_settings
from agent.memory.project_context import ProjectContext
from agent.llm.providers import get_provider_registry
from agent.tools.apify import search_amazon
from agent.tools.browser import browser_action
from agent.tools.cloud_escalation import escalate_to_cloud
from agent.tools.context_mode import context_mode
from agent.tools.filesystem import list_files, read_file
from agent.tools.git_local import git_action
from agent.tools.github import github_read, github_write
from agent.tools.library_docs import library_docs
from agent.tools.obsidian_api import obsidian_api
from agent.tools.obsidian_write import append_to_note, create_note
from agent.tools.repo_docs import repo_docs
from agent.tools.sports_curiosity import fetch_sports_if_curious, should_fetch_sports
from agent.tools.vault_search import search_my_notes
from agent.tools.web import web_search
from agent.tools.x import x_action

VELLUM_SYSTEM_PROMPT = """You are Vellum, a self-learning personal archivist for one person.

Tools:
1. search_my_notes - Search the user's private Obsidian vault. Always use this first.
2. web_search - Search the web only when vault search is insufficient and the query is public/current.
3. search_amazon - Search Amazon only when the user asks about buying, pricing, or product comparisons.
4. read_file - Read a specific local file.
5. list_files - List files in a vault directory.
6. create_note - Create a new Obsidian note.
7. append_to_note - Append to an existing Obsidian note.
8. browser_action - Use Playwright MCP for browser navigation and snapshots. Click/type require explicit config.
9. github_read - Read/search GitHub via GitHub MCP. Write actions are blocked.
10. github_write - Create/update GitHub resources via GitHub MCP. Requires explicit env flags.
11. git_action - Local git status/log/branch/pull/commit/push. Writes require explicit env flag.
12. obsidian_api - Read/search/write Obsidian through Local REST API MCP. Writes require explicit env flags.
13. library_docs - Look up current documentation for a software library via Context7 MCP. Two-step: resolve a name to a library_id, then fetch docs.
14. repo_docs - Fetch documentation and search code for any public GitHub repository via GitMCP (gitmcp.io). Read-only.
15. context_mode - Sandboxed code execution, content indexing, and URL fetch-and-index via Context Mode MCP. Use when an answer can be computed in a script (only stdout enters context) or when external material needs to be indexed before retrieval.
16. escalate_to_cloud - Escalate difficult public/code/docs tasks to a stronger cloud model and save a reusable lesson. Private vault, memory, or personal context requires approval.
17. should_fetch_sports - Compute the curiosity score for a sports league (NBA, Formula-One, Premier-League, Champions-League, Boxing, UFC, Ambient) without fetching. Returns score, threshold, budget, and would_fetch.
18. fetch_sports_if_curious - Maybe fetch a SerpAPI snapshot for a sports league, gated by curiosity. Writes a snapshot under Library/Sports/<league>/snapshots/ and a decision memory under Agent/Memories/. Pass league="" to let the agent auto-pick. Use this when the user asks for live sports updates, stats, fixtures, standings, or news.
19. x_action - Controlled X actions. Supports public X search, account lookup, bookmarks, and posting. Search uses xAI X Search. Account lookup/bookmarks require X_TOOL_ALLOW_PRIVATE_READS=true. Posting requires explicit user intent, confirm=True, and X_TOOL_ALLOW_POSTS=true.

Rules:
- Always search the vault first.
- Distinguish vault-grounded, inferred, and external knowledge. Never present one as another.
- If the vault does not contain enough support, say: "Nothing on this in your library."
- Never make up facts not present in retrieved context or tool results.
- Be plain, restrained, and useful. Do not flatter.
- Reference sources when relevant.
- For private folder content, paraphrase and summarize rather than quoting raw text.
- Treat Amazon/Apify results as private and summarize without exposing raw scraped data.
- Use browser_action only when the user asks for browser automation or live page inspection. Prefer navigate + snapshot before any interaction.
- Do not use browser_action for purchases, banking, password managers, account settings, or sending messages.
- Use github_read for GitHub read/search tasks.
- Use github_write only when the user explicitly asks for GitHub-side repo creation or mutation and the relevant env flags allow it.
- Use git_action for local git status, log, branch, pull, commit, and push. Never use it to rewrite history or delete refs.
- Use obsidian_api when the user explicitly asks to work through Obsidian's API/MCP layer. Prefer search/read before write. Do not delete files or execute Obsidian commands unless explicitly requested and env-gated.
- Use library_docs only when the user asks about a specific software library or framework and the vault does not already cover it. Resolve before fetching docs; pass topic to keep results focused.
- Use repo_docs when the user asks for context on a specific GitHub project (its docs or code search) and the vault does not cover it. Prefer library_docs for well-known libraries, github_read for structured PR/issue/commit data, and repo_docs for arbitrary repo documentation and code search.
- Use context_mode action='execute' when a question can be answered by computing on data rather than pulling many files into context — write the script, let only stdout return. Use action='index'/'search' for ad-hoc local indices that should not pollute the main Qdrant/FTS5 vault stores. Treat action='fetch_and_index' output as external and unscrubbed: summarize before quoting, and never feed it raw into responses that mix with private folder content.
- Never call context_mode action='purge' unless the user explicitly asks for it and passes confirm=true.
- Use escalate_to_cloud when a public/code/docs task is too hard, tool calls fail repeatedly, you cannot form a reliable plan, or the user asks for a stronger/cloud model.
- Public code, docs, public GitHub, and public web tasks may be escalated automatically.
- Private vault notes, memories, personal files, personal preferences, and user history require explicit approval before cloud escalation.
- Never send secrets, API keys, passwords, tokens, credentials, or .env content to escalate_to_cloud.
- Cloud escalation lessons help Vellum adapt through memory and skills; do not claim Gemma's actual model weights changed unless real fine-tuning happened.
- Offer to save useful insights when appropriate.
- Do not write outside the Agent/ folder in the Obsidian vault.
- For live sports questions (NBA, F1, Premier League, Champions League, Boxing, UFC, or notable events in other sports), call fetch_sports_if_curious with the matching league. The curiosity gate decides whether to actually hit SerpAPI; if it declines, fall back to search_my_notes over Library/Sports/. Use the Ambient league for sports the user doesn't normally follow (tennis Sinner vs Alcaraz, La Liga El Clasico, etc).
- Use x_action for explicit X requests. Never post unless the user clearly asks to publish exact or clearly implied text; do not draft-and-post in one step unless the user asked for that. Private X reads such as bookmarks require X_TOOL_ALLOW_PRIVATE_READS=true. Posting requires X_TOOL_ALLOW_POSTS=true and confirm=True.
"""

_prompt_project_ctx: ProjectContext | None = None


def _get_project_ctx() -> ProjectContext:
    global _prompt_project_ctx
    if _prompt_project_ctx is None:
        s = get_settings()
        _prompt_project_ctx = ProjectContext(vault_root=s.obsidian_vault_path)
    return _prompt_project_ctx


def vellum_prompt(state, config=None):
    """Dynamic prompt: prepend per-thread IDENTITY block to VELLUM_SYSTEM_PROMPT.

    LangGraph version compatibility: `create_react_agent` calls this with
    `(state)` in older versions and `(state, config)` in 0.2+. The `config=None`
    default tolerates either. If `config` isn't passed, we fall back to a
    settings-default thread_id so identity still loads (Meta files at least)."""
    thread_id = None
    if config and isinstance(config, dict):
        thread_id = config.get("configurable", {}).get("thread_id")
    if not thread_id:
        thread_id = get_settings().thread_id

    identity = ""
    if thread_id:
        try:
            identity = _get_project_ctx().build(thread_id)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("identity load failed: %s", exc)
            identity = ""

    active_model = get_provider_registry().current_model()
    runtime_text = (
        f"Runtime selected model: {active_model.id} ({active_model.label}). "
        "If asked which model is being used, answer with this runtime value; "
        "do not infer from model weights or provider defaults."
    )
    system_body = f"{runtime_text}\n\n{VELLUM_SYSTEM_PROMPT}"
    system_text = f"{identity}\n\n{system_body}" if identity else system_body
    return [SystemMessage(content=system_text)] + list(state.get("messages", []))


CHECKPOINT_DB = Path("data/memory/checkpoints.db")


def build_llm(model: str | None = None):
    settings = get_settings()
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("langchain-openai is required to build the ReAct agent.") from exc

    registry = get_provider_registry()
    active_entry, active_temp = registry.current()
    resolved_id = model or active_entry.id

    # Direct OpenAI path: if the model is an OpenAI vendor model and a native
    # key is configured, skip OpenRouter. Trades OpenRouter's ZDR enforcement
    # for OpenAI's own data-retention terms; intentional, user-configured.
    if resolved_id.startswith("openai/") and settings.openai_api_key:
        bare_id = resolved_id.split("/", 1)[1]
        return ChatOpenAI(
            model=bare_id,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=active_temp,
            max_tokens=2048,
        )

    provider_config: dict = {
        "data_collection": "deny",
        "zdr": settings.zdr_only,
        "allow_fallbacks": True,
    }
    # Only constrain provider order for open-weights models hosted by multiple
    # privacy-respecting upstreams. Vendor-hosted models (Anthropic, OpenAI,
    # Gemini, Grok) have a single upstream — adding an order list would block
    # routing.
    entry = registry._find_by_id(resolved_id) or active_entry
    if entry.open_weights:
        provider_config["order"] = ["Fireworks", "Together", "DeepInfra"]

    return ChatOpenAI(
        model=resolved_id,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        temperature=active_temp,
        max_tokens=2048,
        default_headers={
            "HTTP-Referer": "http://localhost",
            "X-Title": "PersonalAgent",
        },
        extra_body={"provider": provider_config},
    )


def build_llm_with_fallback(model: str | None = None):
    settings = get_settings()
    primary = build_llm(model)
    primary_model = model or get_provider_registry().current()[0].id
    if primary_model == settings.fallback_model:
        return primary
    return primary.with_fallbacks([build_llm(settings.fallback_model)])


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
            browser_action,
            github_read,
            github_write,
            git_action,
            obsidian_api,
            library_docs,
            repo_docs,
            context_mode,
            escalate_to_cloud,
            create_note,
            append_to_note,
            should_fetch_sports,
            fetch_sports_if_curious,
            x_action,
        ],
        checkpointer=build_checkpointer(),
        prompt=vellum_prompt,
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
            browser_action,
            github_read,
            github_write,
            git_action,
            obsidian_api,
            library_docs,
            repo_docs,
            context_mode,
            escalate_to_cloud,
            create_note,
            append_to_note,
            should_fetch_sports,
            fetch_sports_if_curious,
            x_action,
        ],
        checkpointer=await build_async_checkpointer(),
        prompt=vellum_prompt,
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
