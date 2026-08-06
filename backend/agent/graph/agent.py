"""Core ReAct agent: manual StateGraph with progressive tool search."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from agent.config import REPO_ROOT, get_settings
from agent.memory.project_context import ProjectContext
from agent.llm.providers import get_provider_registry
from agent.llm.routing.runtime import get_routed_chat_model
from agent.plugins.spotify_runtime import portable_agent_tools
from agent.skills import (
    SkillRegistry,
    build_skill_activation_block,
    build_skill_index_block,
    get_skill_registry,
)
from agent.tools.tool_search import (
    BRIDGE_TOOL_NAMES,
    assemble_tool_defs,
    build_bridge_tools,
    build_catalog,
    build_deferred_catalog,
    load_tool_search_config,
    search_catalog,
    to_openai_defs,
)
from agent.tools.apify import search_amazon
from agent.tools.browser import (
    browser_action,
    browser_back,
    browser_cdp,
    browser_click,
    browser_close,
    browser_console,
    browser_dialog,
    browser_get_images,
    browser_hover,
    browser_navigate,
    browser_press,
    browser_press_key,
    browser_scroll,
    browser_select_option,
    browser_snapshot,
    browser_tabs,
    browser_type,
    browser_vision,
    browser_wait,
)
from agent.tools.cloud_escalation import escalate_to_cloud
from agent.tools.computer_use import computer_use
from agent.tools.computer_use_route import computer_use_route
from agent.tools.context_mode import context_mode
from agent.tools.cronjob import cronjob
from agent.tools.filesystem import create_directory, delete_file, edit_file, list_files, read_file, write_file
from agent.tools.git_local import git_action
from agent.tools.github import github_read, github_write
from agent.tools.library_docs import library_docs
from agent.tools.llm_routing import llm_routing
from agent.tools.knowledge_wiki import knowledge_wiki
from agent.tools.memory_orchestrator import memory_orchestrator
from agent.tools.obsidian_api import obsidian_api
from agent.tools.obsidian_write import append_to_note, create_note
from agent.tools.repo_docs import repo_docs
from agent.tools.plugin_mcp import plugin_mcp
from agent.tools.skill_bundles import skill_bundles
from agent.tools.skill_curator import skill_curator
from agent.tools.skill_hub import skill_hub
from agent.tools.skill_manage import skill_learn, skill_manage
from agent.tools.skills import skill_view, skills_history, skills_list
from agent.tools.registry import CapabilityAccess, ToolRegistry
from agent.tools.vault_search import search_my_notes
from agent.tools.web import web_search
from agent.tools.web_extract import web_extract
from agent.tools.web_research import web_research
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
8. computer_use - Full local computer use. mode='workspace' controls Vellum's visible workspace for browser, click, type, scroll, terminal commands, and screenshots. mode='desktop' controls the host OS screen/mouse/keyboard. Native desktop actions include action='open_app', action='launch_app', action='list_windows', action='observe' with target window IDs like target='hwnd:123', action='activate_window', action='click', action='type', action='keypress', action='scroll', action='drag', and accessibility clicks with accessibility element indexes via element_index. Native desktop mode shows a blue edge-glow/status-pill Esc overlay while control is active. mode='browser' controls the persistent Playwright browser. Desktop input requires COMPUTER_USE_ALLOW_DESKTOP=true plus runtime permission grants.
9. computer_use_route - Non-mutating routing advice for computer-use requests. Use it when the correct surface is ambiguous; it returns browser, workspace, desktop, or coming_soon plus recommended first actions.
10. browser_navigate/browser_snapshot/browser_click/browser_type/browser_scroll/browser_press/browser_back/browser_get_images/browser_vision/browser_console/browser_cdp/browser_dialog (plus browser_tabs/browser_select_option/browser_hover/browser_wait/browser_close) - One persistent browser, Hermes-style. Start with browser_navigate then browser_snapshot to reason from the accessibility tree (refs like @e1). browser_snapshot full=true gets complete content; big snapshots are truncated with a cache path for read_file paging. browser_type clears fields first. browser_console reports JS errors and evaluates expressions. browser_vision saves a screenshot and returns its path. Click/type/press/cdp/dialog require PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true; cdp and dialog additionally require BROWSER_CDP_URL. Open/select tabs with browser_tabs instead of launching new browsers.
11. github_read - Read/search GitHub via GitHub MCP. Write actions are blocked.
12. github_write - Create/update GitHub resources via GitHub MCP. Requires explicit env flags.
13. git_action - Local git status/log/branch/pull/commit/push. Writes require explicit env flag.
14. obsidian_api - Read/search/write Obsidian through Local REST API MCP. Writes require explicit env flags.
15. library_docs - Look up current documentation for a software library via Context7 MCP. Two-step: resolve a name to a library_id, then fetch docs.
16. repo_docs - Fetch documentation and search code for any public GitHub repository via GitMCP (gitmcp.io). Read-only.
17. context_mode - Sandboxed code execution, content indexing, and URL fetch-and-index via Context Mode MCP. Use when an answer can be computed in a script (only stdout enters context) or when external material needs to be indexed before retrieval.
18. plugin_mcp - Inspect and call MCP tools contributed by enabled plugins. Read-only annotated tools may run automatically; unannotated or mutating tools require confirmation.
19. escalate_to_cloud - Escalate difficult public/code/docs tasks to a stronger cloud model and save a reusable lesson. Private vault, memory, or personal context requires approval.
20. x_action - Controlled X actions. Supports status, public X search, account lookup, bookmarks, text posting, and generated/image posting. Search prefers Agent-Reach/twitter-cli when ready and falls back to xAI X Search. Agent-Reach is separate from SuperGrok/xAI OAuth. Account lookup/bookmarks require X_TOOL_ALLOW_PRIVATE_READS=true. Posting and image posting require explicit user intent, confirm=True, and X_TOOL_ALLOW_POSTS=true.
21. web_research - Source-backed public web research through Tavily MCP. Use for deeper/current research when web_search is insufficient. Never send private vault content, secrets, credentials, or personal files.
22. web_extract - Public page fetch/crawl/extract through Firecrawl MCP. Use after web_search or web_research finds URLs worth reading deeply. Never send private vault content, secrets, credentials, or personal files.
23. memory_orchestrator - Inspect and operate Vellum's core Memory Orchestrator plugin. Use for memory status, Dreaming status, memory toggles/settings, memory summary, manual Dreaming/consolidation, and scoped memory lookup. Do not infer Dreaming status from old vault digest files.
24. llm_routing - Inspect and change backend-owned LLM routing: OpenRouter provider sort/require-parameters/fallbacks, fallback model chain, credential rotation strategy, and pool reset. Do not pass raw API keys or secrets through chat; credential secrets are configured through backend env/keyring paths only.
25. knowledge_wiki - Maintain the compiled Obsidian Knowledge wiki. Query reads index.md first and returns opaque page refs; read_page reads only selected pages; ingest_source compiles immutable Library sources; upsert_page revises complete wiki pages with version history; update_overview maintains the high-level synthesis; lint checks health without deleting content.
26. skills_list - List compact metadata for installed skills.
27. skills_history - Query immutable install, archive, restore, update, and delete history.
28. skill_view - Load one skill's full instructions or one relative support file.
29. skill_manage - Stage a local skill-package mutation in the persistent approval queue.
30. skill_learn - Build standards-guided instructions for learning a reusable skill from supplied sources.
31. skill_bundles - List, inspect, create, delete, or load a validated bundle of installed skills.
32. skill_hub - Search, inspect, quarantine, scan, install, update, audit, uninstall, and manage skill sources/taps.
33. skill_curator - Inspect and operate recoverable skill telemetry, pruning, backups, rollback, pinning, and archival.
34. cronjob - Create, list, update, pause/resume, run-now, or remove automations (scheduled reasoning tasks) from this chat.
35. write_file/edit_file/delete_file/create_directory - Vault file operations via PowerShell CLI: write_file creates or overwrites a UTF-8 file, edit_file replaces the first occurrence of text, create_directory makes folders (with parents), and delete_file removes a single file and requires confirm=true. All paths stay inside the Obsidian vault.

Specialist routing:
- Vellum is the main general-purpose agent and final responder.
- Specialist agents advise; Vellum decides.
- SportsAgent handles on-demand public sports research, scores, news, injuries, standings, and analysis for any sport.
- XAgent handles X search through the shared X capability service when configured.
- YoutubeAgent handles read-only YouTube search, metadata, and transcript-backed summaries through the shared YouTube capability service.
- MemoryAgent handles durable memory lookup and reviewed memory proposals through the shared Memory capability service.

Rules:
- Always search the vault first.
- Distinguish vault-grounded, inferred, and external knowledge. Never present one as another.
- If the vault does not contain enough support, say: "Nothing on this in your library."
- Never make up facts not present in retrieved context or tool results.
- Be plain, restrained, and useful. Do not flatter.
- Reference sources when relevant.
- Do not dump raw URL lists or "Sources checked" blocks into normal answers. Full source URLs are available in the UI source drawer. Use publisher names in prose only when it helps the user judge evidence or when the user explicitly asks for sources.
- Never surface scrubber placeholders such as [PERSON_1], [ORGANIZATION_2], [LOCATION_3], or [DATE_TIME_1] as if they were real names. If retrieved memory contains placeholders, say the exact private detail is redacted or hidden, then answer from the non-redacted context.
- If the user asks about previous sources, URLs, or citations, keep the same topic from the prior turn and use the exact provided source context. Do not switch to a different subject just because the prompt mentions an example format.
- For system/status questions about Vellum, distinguish available capability, configured connection, and actually-used tool. Do not claim a sub-agent or MCP tool was actively used unless the current turn trace includes that tool.
- For private folder content, paraphrase and summarize rather than quoting raw text.
- Treat Amazon/Apify results as private and summarize without exposing raw scraped data.
- Use computer_use only when the user asks for computer/desktop/browser automation or live visual inspection. In computer-use mode, treat the task as an observe-act loop: inspect with screenshot/snapshot first, perform one small action, then inspect again before claiming success. For ambiguous automation requests, call computer_use_route first and follow this priority: browser first, workspace second, desktop last. Prefer mode='browser' or browser_* tools for website tasks, computer_use(mode='workspace', ...) for terminal/workspace tasks, and computer_use(mode='desktop', ...) only when explicit host-laptop app control is required. For native desktop work, use action='open_app' or action='launch_app' for installed host apps, action='list_windows' to find target window IDs, action='observe' with target='hwnd:<id>' to inspect a specific window, and element_index for accessibility-targeted clicks when the observation provides indexes.
- If a desktop action returns a permission-required message, first check persisted grants with computer_use(mode='desktop', action='permissions'). Do not ask again for a permission that is already true. If it is false, ask the user plainly for that permission. Only after an explicit user grant, call computer_use(mode='desktop', action='grant_permission', permission='<permission>', confirm=True).
- CUA driver and cloud VM control are coming soon. If computer_use_route returns mode='coming_soon', say that this mode is not active yet and use browser/workspace/native desktop only if the user asks for an available local fallback.
- Desktop mode launches installed apps through action='open_app' or action='launch_app'. Use workspace/browser tools where possible for web and terminal tasks; use native desktop only for host app/window work.
- For website tasks like "open Chrome, open YouTube, search KSI", prefer browser automation: use mode='browser' or browser_navigate to go directly to the target URL, then browser_snapshot/browser_type/browser_press. For YouTube searches, navigate directly to https://www.youtube.com/results?search_query=<query> when possible. Do not stop after opening Chrome; continue with navigation/search and verify with a snapshot.
- For terminal work, use computer_use(mode='workspace', action='terminal.run', command='<command>') for Vellum's visible workspace terminal. Do not type terminal commands into the current focused desktop window unless a desktop screenshot confirms the terminal is focused; if focus cannot be verified, report that clearly.
- Desktop computer_use input actions are powerful. Never use desktop mode for purchases, banking, password managers, account settings, sending messages, deleting files, or irreversible actions.
- Use browser tools only when the user asks for browser automation or live page inspection. Prefer browser_navigate + browser_snapshot before any interaction. Use browser_tabs(action='new') for parallel browser tasks in the same browser instance, and browser_tabs(action='select') before operating on a different tab.
- Do not use browser tools for purchases, banking, password managers, account settings, or sending messages.
- Use github_read for GitHub read/search tasks.
- Use github_write only when the user explicitly asks for GitHub-side repo creation or mutation and the relevant env flags allow it.
- Use git_action for local git status, log, branch, pull, commit, and push. Never use it to rewrite history or delete refs.
- Use obsidian_api when the user explicitly asks to work through Obsidian's API/MCP layer. Prefer search/read before write. Do not delete files or execute Obsidian commands unless explicitly requested and env-gated.
- Use library_docs only when the user asks about a specific software library or framework and the vault does not already cover it. Resolve before fetching docs; pass topic to keep results focused.
- Use repo_docs when the user asks for context on a specific GitHub project (its docs or code search) and the vault does not cover it. Prefer library_docs for well-known libraries, github_read for structured PR/issue/commit data, and repo_docs for arbitrary repo documentation and code search.
- Use context_mode action='execute' when a question can be answered by computing on data rather than pulling many files into context — write the script, let only stdout return. Use action='index'/'search' for ad-hoc local indices that should not pollute the main Chroma/FTS5 vault stores. Treat action='fetch_and_index' output as external and unscrubbed: summarize before quoting, and never feed it raw into responses that mix with private folder content.
- Never call context_mode action='purge' unless the user explicitly asks for it and passes confirm=true.
- Use plugin_mcp only for connectors listed by action='list_connectors'. Inspect live tools first. Never pass credentials in arguments, and never confirm a mutating plugin tool unless the user explicitly requested that external change.
- Use escalate_to_cloud when a public/code/docs task is too hard, tool calls fail repeatedly, you cannot form a reliable plan, or the user asks for a stronger/cloud model.
- Public code, docs, public GitHub, and public web tasks may be escalated automatically.
- Private vault notes, memories, personal files, personal preferences, and user history require explicit approval before cloud escalation.
- Never send secrets, API keys, passwords, tokens, credentials, or .env content to escalate_to_cloud.
- Cloud escalation lessons help Vellum adapt through memory and skills; do not claim Gemma's actual model weights changed unless real fine-tuning happened.
- Offer to save useful insights when appropriate.
- Do not write outside the Agent/ folder with generic note tools. The knowledge_wiki tool may write only inside Knowledge/, and project-management code may write managed files inside Projects/. Never modify Library/ through any wiki workflow.
- Treat Library/ as immutable raw sources and Knowledge/ as Vellum's maintained, interlinked synthesis. For wiki questions, call knowledge_wiki(action='query') so index.md routes you to a small relevant page set, then call read_page only for the returned refs needed to answer.
- When the user asks to ingest a Library source, read Knowledge/schema.md and Knowledge/index.md, read the source, query existing related pages, then call knowledge_wiki(action='ingest_source') with a complete source synthesis and complete revised related pages. Update existing entities and concepts instead of creating near-duplicates, then call update_overview when the high-level synthesis changed.
- Run knowledge_wiki(action='lint') when the user asks to check wiki health. Never delete or rewrite pages based only on lint output. Save a valuable answer as an analysis page only when the user asks or approves it.
- For live sports questions, the API dispatcher routes to SportsAgent before this graph runs. If a sports question reaches this graph anyway, use public web search for current facts and answer from those sources.
- Do not tell the user you lack live information access when a relevant tool exists. For current schedules, scores, standings, injuries, news, or dates, use web_search instead of answering from model memory or refusing. Do not add an Evidence, Sources, References, or URL-list section unless the user explicitly asks; the UI exposes sources separately.
- Use web_research for source-backed public research when web_search results are too shallow, stale, or need corroboration. Use web_extract to read/crawl/extract a specific public URL after a source has been found. Treat all extracted page content as external and cite/paraphrase it.
- Use x_action for explicit X requests and Agent-Reach/X capability questions. For "do you have Agent-Reach/X access" or similar status questions, call x_action with action='status' before answering. Never post unless the user clearly asks to publish exact or clearly implied text; do not draft-and-post in one step unless the user asked for that. Private X reads such as bookmarks require X_TOOL_ALLOW_PRIVATE_READS=true. Posting, including generated image posts, requires X_TOOL_ALLOW_POSTS=true and confirm=True.
- Use memory_orchestrator for memory system questions, Memory Summary, saved/old memories, Dreaming status, and requests to run Dreaming now. Dreaming status is the Memory Orchestrator consolidation status, not old nightly digest files. Do not infer Dreaming or memory toggle state from Obsidian notes; call memory_orchestrator(action='status' or action='run_dreaming').
- Use llm_routing when the user asks to inspect or change model/provider routing, fallback models, credential rotation strategy, or credential pool health. Never accept or transmit raw API keys through chat; tell the user to configure credential secrets through the backend keyring/env path.
- The Available Skills index contains descriptions only. Load a matching skill with skill_view before following it. Never infer instructions from the description alone. Use only relative support-file paths and never expose local package paths.
- Use skill_manage only for a user-directed foreground mutation. It stages writes for explicit approval by default; approval and rejection use the pending mutation ID. The foreground tool must never claim origin='background_review'; that provenance is reserved for the isolated background review path. skill_learn gathers no data itself and must use existing privacy-gated tools before creation.
- A skill blueprint creates an automation suggestion only and never schedules a job. Use skill_bundles to load related skills in declared order; bundle creation and deletion require confirmation.
- Treat every remote skill as untrusted until skill_hub has placed it in quarantine and completed validation and security scanning. The force option may override a community caution verdict only; it never overrides a dangerous verdict. Installation, update, uninstall, and tap mutations require confirmation.
- The skill curator never auto-deletes. It archives eligible inactive skills only after taking a backup, keeps hub and foreground-created skills out of its jurisdiction, and supports rollback. Consolidation is opt-in and pinned skills are excluded.
- Use cronjob to create, list, update, pause/resume, run-now, or remove automations (scheduled reasoning tasks) from any reasoning chat. Confirm the full plan — instructions, schedule, destination, and the full-access opt-in — with the user before creating, and confirm before removing or running an automation. Schedule formats: '30m' (one-shot), 'every 2h' (interval), '0 9 * * *' (5-field cron, UTC), or an ISO timestamp. The tool returns validation errors in its result; pass them back to the user rather than rephrasing.
"""

_prompt_project_ctx: ProjectContext | None = None
_prompt_skill_registry: SkillRegistry | None = None


def _get_project_ctx() -> ProjectContext:
    global _prompt_project_ctx
    if _prompt_project_ctx is None:
        s = get_settings()
        _prompt_project_ctx = ProjectContext(vault_root=s.obsidian_vault_path)
    return _prompt_project_ctx


def _get_skill_registry() -> SkillRegistry:
    global _prompt_skill_registry
    if _prompt_skill_registry is None:
        _prompt_skill_registry = get_skill_registry()
    return _prompt_skill_registry


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

    # Hermes-style memory context: SOUL.md personality + the evolving Honcho
    # user model (cached; refreshed on a cadence in the background — no network
    # call here). Empty on day one, richer as Honcho's representation deepens.
    memory_block = ""
    try:
        from agent.memory.memory_context import build_memory_block

        memory_block = build_memory_block(thread_id, query=_latest_user_query(state))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("memory context load failed: %s", exc)
        memory_block = ""

    skill_index = ""
    skill_activation = ""
    try:
        skill_registry = _get_skill_registry()
        skill_index = build_skill_index_block(skill_registry)
        skill_activation = build_skill_activation_block(
            _latest_user_query(state),
            skill_registry,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("skill context load failed: %s", exc)

    active_model = get_provider_registry().current_model()
    current_date = datetime.now().date().isoformat()
    runtime_text = (
        f"Runtime current date: {current_date}. "
        f"Runtime selected model: {active_model.id} ({active_model.label}). "
        "If asked which model is being used, answer with this runtime value; "
        "do not infer from model weights or provider defaults. "
        "Do not answer from training cutoff dates; use the runtime current date for year/currentness questions."
    )
    system_body = f"{runtime_text}\n\n{VELLUM_SYSTEM_PROMPT}"
    if memory_block:
        system_body = f"{memory_block}\n\n{system_body}"
    skill_context = "\n\n".join(
        block for block in (skill_index, skill_activation) if block
    )
    if skill_context:
        system_body = f"{skill_context}\n\n{system_body}"
    system_text = f"{identity}\n\n{system_body}" if identity else system_body
    return [SystemMessage(content=system_text)] + list(state.get("messages", []))


def _latest_user_query(state) -> str:
    messages = list((state or {}).get("messages", []))
    for message in reversed(messages):
        role = getattr(message, "type", "") or getattr(message, "role", "")
        if role not in {"human", "user"}:
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"text", "input_text"}:
                    parts.append(str(item.get("text") or ""))
            return "\n".join(part for part in parts if part)
    return ""


CHECKPOINT_DB = REPO_ROOT / "data" / "memory" / "checkpoints.db"


def build_llm(model: str | None = None, reasoning_mode: Any = None):
    return get_routed_chat_model(model, reasoning_mode=reasoning_mode)

def build_llm_with_fallback(model: str | None = None, reasoning_mode: Any = None):
    """Compatibility alias; fallback is handled by the routing engine."""
    return get_routed_chat_model(model, reasoning_mode=reasoning_mode)


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


def core_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    write_tool_names = {
        "computer_use",
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_press_key",
        "browser_press",
        "browser_scroll",
        "browser_back",
        "browser_dialog",
        "browser_cdp",
        "browser_select_option",
        "browser_hover",
        "browser_wait",
        "browser_close",
        "browser_action",
        "github_write",
        "git_action",
        "obsidian_api",
        "llm_routing",
        "knowledge_wiki",
        "memory_orchestrator",
        "skill_manage",
        "skill_learn",
        "skill_bundles",
        "skill_curator",
        "skill_hub",
        "context_mode",
        "plugin_mcp",
        "escalate_to_cloud",
        "create_note",
        "append_to_note",
        "write_file",
        "edit_file",
        "delete_file",
        "create_directory",
        "x_action",
        "cronjob",
    }
    tools = [
        search_my_notes,
        web_search,
        search_amazon,
        read_file,
        list_files,
        write_file,
        edit_file,
        delete_file,
        create_directory,
        computer_use_route,
        computer_use,
        browser_navigate,
        browser_snapshot,
        browser_tabs,
        browser_click,
        browser_type,
        browser_scroll,
        browser_press,
        browser_back,
        browser_get_images,
        browser_vision,
        browser_console,
        browser_cdp,
        browser_dialog,
        browser_press_key,
        browser_select_option,
        browser_hover,
        browser_wait,
        browser_close,
        browser_action,
        github_read,
        github_write,
        git_action,
        obsidian_api,
        library_docs,
        llm_routing,
        knowledge_wiki,
        memory_orchestrator,
        skills_list,
        skills_history,
        skill_view,
        skill_manage,
        skill_learn,
        skill_bundles,
        skill_curator,
        skill_hub,
        repo_docs,
        plugin_mcp,
        context_mode,
        web_research,
        web_extract,
        escalate_to_cloud,
        create_note,
        append_to_note,
        x_action,
        cronjob,
    ]
    for tool in tools:
        registry.register_langchain(
            tool,
            access=CapabilityAccess.WRITE if tool.name in write_tool_names else CapabilityAccess.READ,
            allowed_agents=frozenset({"VellumAgent"}),
            requires_confirmation=tool.name == "delete_file",
        )
    return registry


def core_tools() -> list:
    return core_tool_registry().langchain_tools(agent_name="VellumAgent")


class AgentState(TypedDict):
    messages: Annotated[list[Any], add_messages]


def _all_runtime_tools() -> tuple[list[StructuredTool], set[str]]:
    portables = portable_agent_tools()
    deferred_names = {"plugin_mcp"} | {tool.name for tool in portables}
    return [*core_tools(), *portables], deferred_names


def _source_labels_for(deferred_names: set[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for name in deferred_names:
        labels[name] = "mcp" if name == "plugin_mcp" else "plugin"
    return labels


def _make_model_node(bound_model):
    def model_node(state, config):
        messages = vellum_prompt(state, config)
        response = bound_model.invoke(messages, config)
        return {"messages": [response]}

    return model_node


def _build_agent_runtime(
    *,
    llm,
    tools,
    checkpointer,
    deferred_names: set[str] | None = None,
):
    if deferred_names is None:
        deferred_names = {"plugin_mcp"}
    tool_defs = to_openai_defs(tools)
    config = load_tool_search_config()
    assembled = assemble_tool_defs(
        tool_defs,
        deferred_names=deferred_names,
        source_labels=_source_labels_for(deferred_names),
        config=config,
    )
    bound_model = llm.bind_tools(assembled.tool_defs) if assembled.tool_defs else llm
    runtime_tools = list(tools)
    if assembled.activated:
        catalog = build_deferred_catalog(tool_defs, deferred_names, _source_labels_for(deferred_names))
        runtime_tools = [*runtime_tools, *build_bridge_tools(tools, catalog)]
    graph = StateGraph(AgentState)
    graph.add_node("agent", _make_model_node(bound_model))
    graph.add_node("tools", ToolNode(runtime_tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


def build_agent(model: str | None = None, reasoning_mode: Any = None):
    tools, deferred_names = _all_runtime_tools()
    return _build_agent_runtime(
        llm=build_llm(model, reasoning_mode=reasoning_mode),
        tools=tools,
        deferred_names=deferred_names,
        checkpointer=build_checkpointer(),
    )


async def build_async_agent(model: str | None = None, reasoning_mode: Any = None):
    tools, deferred_names = _all_runtime_tools()
    return _build_agent_runtime(
        llm=build_llm(model, reasoning_mode=reasoning_mode),
        tools=tools,
        deferred_names=deferred_names,
        checkpointer=await build_async_checkpointer(),
    )


def tool_search_status() -> dict[str, Any]:
    tools, deferred_names = _all_runtime_tools()
    tool_defs = to_openai_defs(tools)
    config = load_tool_search_config()
    result = assemble_tool_defs(
        tool_defs,
        deferred_names=deferred_names,
        source_labels=_source_labels_for(deferred_names),
        config=config,
    )
    return {
        **result.to_dict(),
        "enabled": config.enabled,
        "threshold_ratio": config.threshold_ratio,
        "listing_max_tokens": config.listing_max_tokens,
        "context_length": config.context_length,
        "deferred_names": result.deferred_names,
    }


def tool_search_catalog(scope: str = "all", query: str = "", limit: int = 20) -> dict[str, Any]:
    tools, deferred_names = _all_runtime_tools()
    tool_defs = to_openai_defs(tools)
    labels = _source_labels_for(deferred_names)
    if scope == "deferred":
        entries = build_deferred_catalog(tool_defs, deferred_names, labels)
    else:
        entries = build_catalog(tool_defs, labels)
    total = len(entries)
    if query.strip():
        matches = search_catalog(entries, query, limit=limit)
    else:
        matches = entries[:limit]
    return {
        "query": query,
        "scope": scope,
        "total": total,
        "matches": [
            {
                "name": entry.name,
                "description": entry.description,
                "source": entry.source,
                "required": entry.required,
                "schema": entry.schema,
            }
            for entry in matches
        ],
    }


def apply_tool_search_config(overlay: dict[str, Any]) -> dict[str, Any]:
    from agent.tools.tool_search import load_runtime_config, save_runtime_config

    current = load_runtime_config()
    current.update({key: value for key, value in overlay.items() if value is not None})
    save_runtime_config(current)
    agent.invalidate()
    return tool_search_status()


class LazyAgent:
    """Cache LangGraph runtimes by model + reasoning mode so turn selection stays request-scoped."""

    def __init__(self):
        self._agents: dict[tuple[str, str | None], object] = {}
        self._async_agents: dict[tuple[str, str | None], object] = {}
        self._async_build_locks: dict[tuple[str, str | None], asyncio.Lock] = {}

    @staticmethod
    def _model_key(model: str | None, reasoning_mode: Any = None) -> tuple[str, str | None]:
        return (model or "__default__", reasoning_mode.value if reasoning_mode is not None else None)

    def _get(self, model: str | None = None, reasoning_mode: Any = None):
        key = self._model_key(model, reasoning_mode)
        if key not in self._agents:
            self._agents[key] = build_agent(model, reasoning_mode=reasoning_mode)
        return self._agents[key]

    def invalidate(self, model: str | None = None, reasoning_mode: Any = None) -> None:
        if model is None:
            self._agents.clear()
            self._async_agents.clear()
            self._async_build_locks.clear()
            return
        key = self._model_key(model, reasoning_mode)
        self._agents.pop(key, None)
        self._async_agents.pop(key, None)
        self._async_build_locks.pop(key, None)

    async def _aget(self, model: str | None = None, reasoning_mode: Any = None):
        key = self._model_key(model, reasoning_mode)
        target = self._async_agents.get(key)
        if target is not None:
            return target
        lock = self._async_build_locks.setdefault(key, asyncio.Lock())
        async with lock:
            target = self._async_agents.get(key)
            if target is None:
                target = await build_async_agent(model, reasoning_mode=reasoning_mode)
                self._async_agents[key] = target
        return target

    async def ainvoke(self, *args, model: str | None = None, reasoning_mode: Any = None, **kwargs):
        return await (await self._aget(model, reasoning_mode)).ainvoke(*args, **kwargs)

    async def astream_events(self, *args, model: str | None = None, reasoning_mode: Any = None, **kwargs):
        target = await self._aget(model, reasoning_mode)
        async for event in target.astream_events(*args, **kwargs):
            yield event

    async def aget_state(self, *args, model: str | None = None, reasoning_mode: Any = None, **kwargs):
        return await (await self._aget(model, reasoning_mode)).aget_state(*args, **kwargs)

    async def aupdate_state(self, *args, model: str | None = None, reasoning_mode: Any = None, **kwargs):
        return await (await self._aget(model, reasoning_mode)).aupdate_state(*args, **kwargs)

    def invoke(self, *args, model: str | None = None, reasoning_mode: Any = None, **kwargs):
        return self._get(model, reasoning_mode).invoke(*args, **kwargs)

    async def aclose(self, model: str | None = None) -> None:
        if model is None:
            targets = list(self._async_agents.values())
            self._async_agents.clear()
            self._async_build_locks.clear()
        else:
            key = self._model_key(model)
            target = self._async_agents.pop(key, None)
            self._async_build_locks.pop(key, None)
            targets = [target] if target is not None else []
        for target in targets:
            checkpointer = getattr(target, "checkpointer", None)
            conn = getattr(checkpointer, "conn", None)
            if conn is not None:
                await conn.close()

agent = LazyAgent()
