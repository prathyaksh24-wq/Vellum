# Build Plan — Changes Only
> Apply these changes on top of `langgraph-agent-build-plan.md`
> Everything not mentioned here stays exactly the same.

---

## WHAT STAYS UNCHANGED

- Phase 1 — `.env` + `agent/config.py` + `docker-compose.yml`
- Phase 2 — `agent/obsidian/folder_policy.py` (all folder policies)
- Phase 5 — `agent/llm/openrouter.py`
- Phase 6 — `agent/mcp/filesystem_tools.py` + `agent/mcp/apify_tools.py`
- Phase 7 — `agent/obsidian/vault.py` + `agent/obsidian/ingester.py`
- Phase 8 — `agent/rag/embedder.py` + `agent/rag/store.py`
- Phase 9 — `agent/memory/long_term.py`
- Phase 10 — `agent/scheduler/digest.py`
- All tests

---

## WHAT CHANGES

### 1. DELETE — Phase 3 entirely (LangGraph State + Graph)

Remove these files completely — they are replaced:
```
agent/graph/state.py        ← DELETE
agent/graph/graph.py        ← DELETE
agent/graph/edges.py        ← DELETE
```

### 2. DELETE — Phase 4 entirely (all graph nodes)

Remove these files completely — the logic moves INTO the tools:
```
agent/graph/nodes/intake.py           ← DELETE
agent/graph/nodes/access_control.py   ← DELETE
agent/graph/nodes/classifier.py       ← DELETE
agent/graph/nodes/retriever.py        ← DELETE
agent/graph/nodes/reranker.py         ← DELETE
agent/graph/nodes/confidence_check.py ← DELETE
agent/graph/nodes/tool_router.py      ← DELETE
agent/graph/nodes/llm_answer.py       ← DELETE
agent/graph/nodes/store_response.py   ← DELETE
agent/graph/nodes/learner.py          ← DELETE
```

### 3. DELETE — Phase 11 `agent/cli.py`
Replaced below with a much simpler version.

---

## WHAT REPLACES THEM

### NEW — `agent/graph/agent.py`
> This single file replaces the entire `graph/` folder.
> The LLM now decides tool calls dynamically — no hardcoded routing.

```python
"""
Core agent using LangGraph's create_react_agent.
The LLM reads tool descriptions and decides what to call, when, and how many times.
This is the same loop ChatGPT / Claude / Gemini use internally.
"""
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_openai import ChatOpenAI
from agent.tools.vault_search import search_my_notes
from agent.tools.web import web_search
from agent.tools.filesystem import read_file, list_files
from agent.tools.apify import search_amazon
from agent.tools.obsidian_write import create_note, append_to_note
from agent.config import settings

# ── System prompt = your agent's "skills" and personality ──────────────
SYSTEM_PROMPT = """You are a private personal AI assistant. You have access to:

1. search_my_notes     — Search the user's private Obsidian knowledge vault.
                         ALWAYS check this first before any other tool.
2. web_search          — Search the web for current/recent information.
                         Only use when vault has insufficient info AND the query
                         is genuinely time-sensitive or factual (not personal).
3. search_amazon       — Search Amazon for product info, prices, reviews.
                         Use only when user explicitly asks about buying something.
4. read_file           — Read a specific file from the local filesystem.
5. list_files          — List files in a directory.
6. create_note         — Write a new note into the Obsidian vault.
7. append_to_note      — Add content to an existing Obsidian note.

Rules:
- Always search the vault first. Most answers live there.
- If vault search returns nothing relevant, say so clearly, then decide if
  web search is appropriate.
- Never make up facts not present in retrieved context or tool results.
- Be conversational and natural — like ChatGPT, not a database query tool.
- Reference your source when relevant ("Based on your notes on F1...",
  "From your Books folder...", "Web search shows...").
- For private folder content (X, youtube, Books, feedback), use it to answer
  but do not quote it verbatim — paraphrase and summarize.
- For Amazon/Apify results: always treat as private, summarize findings
  without exposing raw scraped data.
- After answering, if the interaction contains something worth remembering,
  offer to save it as a note ("Want me to save this to your vault?").
"""

# ── OpenRouter via LangChain's OpenAI-compatible wrapper ───────────────
def build_llm(model: str = None):
    return ChatOpenAI(
        model=model or settings.PRIMARY_MODEL,
        openai_api_key=settings.OPENROUTER_API_KEY,
        openai_api_base=settings.OPENROUTER_BASE_URL,
        temperature=0.3,
        max_tokens=2048,
        default_headers={
            "HTTP-Referer": "http://localhost",
            "X-Title": "PersonalAgent",
        },
        model_kwargs={
            "provider": {
                "data_collection": "deny",  # ZDR enforced
                "order": ["Fireworks", "Together", "DeepInfra"],
            }
        },
    )

# ── Build the agent ────────────────────────────────────────────────────
def build_agent():
    llm = build_llm()
    checkpointer = SqliteSaver.from_conn_string("data/memory/checkpoints.db")

    tools = [
        search_my_notes,
        web_search,
        search_amazon,
        read_file,
        list_files,
        create_note,
        append_to_note,
    ]

    agent = create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
        state_modifier=SYSTEM_PROMPT,
    )

    return agent

# Singleton
agent = build_agent()
```

---

### NEW — `agent/tools/` folder
> Each tool is a self-contained function. Privacy + RAG + folder policy
> live INSIDE each tool — not as separate graph nodes.
> The LLM calls these by reading their docstrings.

```
agent/tools/
├── __init__.py
├── vault_search.py     ← RAG + privacy + folder policy
├── web.py              ← DuckDuckGo, privacy-gated
├── apify.py            ← Amazon scraper, always private
├── filesystem.py       ← Local file read/list
└── obsidian_write.py   ← Create/append Obsidian notes
```

---

### `agent/tools/vault_search.py`
```python
"""
Tool: search_my_notes
The LLM calls this automatically when it needs info from the user's vault.
Contains the full RAG pipeline + privacy layer + folder access policy.
Runs entirely locally — no data leaves the machine here.
"""
from langchain_core.tools import tool
from agent.rag.embedder import Embedder
from agent.rag.store import VectorStore
from agent.privacy.scrubber import PrivacyScrubber
from agent.privacy.classifier import classify, DataClass
from agent.privacy.metadata_strip import strip_obsidian_metadata
from agent.obsidian.vault import ObsidianVault
from agent.obsidian.folder_policy import can_send_to_llm, needs_scrubbing
from agent.memory.long_term import LongTermMemory
from sentence_transformers import CrossEncoder
from agent.config import settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# All local — no API calls
embedder = Embedder()
vector_store = VectorStore()
scrubber = PrivacyScrubber()
vault = ObsidianVault(settings.OBSIDIAN_VAULT_PATH)
memory = LongTermMemory()
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

MIN_SCORE = settings.MIN_RETRIEVAL_SCORE
MAX_CHUNKS = settings.MAX_CONTEXT_CHUNKS


@tool
def search_my_notes(query: str) -> str:
    """Search the user's private Obsidian knowledge vault for relevant notes
    and personal data. Use this for any question about personal notes, books,
    sports data, research, preferences, or anything the user may have written.
    Always call this before attempting web search."""

    # 1. Classify query — block RED data
    data_class, reason = classify(query)
    if data_class == DataClass.RED:
        logger.warning(f"[TOOL:vault] Blocked RED query: {reason}")
        return f"⛔ Query blocked for privacy reasons: {reason}. Please rephrase without sensitive personal identifiers."

    # 2. Scrub query before embedding (YELLOW data)
    if data_class == DataClass.YELLOW:
        clean_query, _ = scrubber.scrub(query)
    else:
        clean_query = query

    # 3. Store query to Obsidian + Qdrant (intake step, now inside tool)
    _store_query(query)

    # 4. Embed + retrieve from local Qdrant
    query_embedding = embedder.embed(clean_query)
    results = vector_store.search(
        collection="obsidian_vault",
        embedding=query_embedding,
        top_k=12,
        score_threshold=0.40,
    )

    if not results:
        return "No relevant notes found in vault for this query."

    # 5. Cross-encoder rerank (local, no API)
    pairs = [(clean_query, r["text"]) for r in results]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(scores, results), key=lambda x: x[0], reverse=True)
    top_score = ranked[0][0] if ranked else 0.0

    # 6. Confidence gate
    if top_score < MIN_SCORE:
        return (
            f"No sufficiently relevant notes found (best match score: {top_score:.2f}, "
            f"threshold: {MIN_SCORE}). I don't have enough information about this in your vault."
        )

    # 7. Filter by folder access policy + scrub private chunks
    allowed_chunks = []
    for _, chunk in ranked[:MAX_CHUNKS * 2]:  # grab more before filtering
        folder = chunk["metadata"].get("folder", "")

        if not can_send_to_llm(folder):
            # Private folder — skip from LLM context
            logger.info(f"[TOOL:vault] Skipping private folder: {folder}")
            continue

        text = chunk["text"]
        if needs_scrubbing(folder):
            text, _ = scrubber.scrub(text)

        allowed_chunks.append({
            "text": text,
            "folder": folder,
            "score": chunk["score"],
        })

        if len(allowed_chunks) >= MAX_CHUNKS:
            break

    if not allowed_chunks:
        return "Found relevant notes but they are in private folders and cannot be surfaced directly. Try rephrasing or asking about a specific accessible topic."

    # 8. Build readable context string
    context_parts = []
    for i, chunk in enumerate(allowed_chunks, 1):
        context_parts.append(f"[Note {i} — {chunk['folder']}]\n{chunk['text']}")

    context = "\n\n---\n\n".join(context_parts)

    # Token cap
    max_chars = settings.MAX_CONTEXT_TOKENS * 4
    if len(context) > max_chars:
        context = context[:max_chars] + "\n[TRUNCATED]"

    logger.info(f"[TOOL:vault] Returning {len(allowed_chunks)} chunks, top score: {top_score:.3f}")
    return context


def _store_query(query: str):
    """Store query to Obsidian + vector DB for self-learning (dedup check first)."""
    q_embedding = embedder.embed(query)
    existing = vector_store.search(
        collection="agent_queries",
        embedding=q_embedding,
        top_k=1,
        score_threshold=0.92,
    )
    if existing:
        return  # Near-duplicate, skip

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    vault.create_note(
        folder=f"{settings.AGENT_NOTES_FOLDER}/Queries",
        title=f"Query {datetime.now().strftime('%Y%m%d_%H%M%S')}",
        content=f"**Query logged at {timestamp}**\n\n{query}",
    )
    vector_store.upsert(
        collection="agent_queries",
        text=query,
        embedding=q_embedding,
        metadata={"timestamp": timestamp, "type": "query"},
    )
```

---

### `agent/tools/web.py`
```python
"""
Tool: web_search
Privacy-gated DuckDuckGo search. No API key, no tracking.
LLM only calls this when vault search is insufficient AND query warrants it.
"""
from langchain_core.tools import tool
from agent.privacy.classifier import classify, DataClass
from agent.privacy.scrubber import PrivacyScrubber
from duckduckgo_search import DDGS
import logging

logger = logging.getLogger(__name__)
scrubber = PrivacyScrubber()


@tool
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo for current or factual information
    not found in the vault. Only use for time-sensitive queries, recent news,
    live sports scores, or verifiable public facts. Do NOT use for personal
    questions that should stay private."""

    data_class, reason = classify(query)
    if data_class == DataClass.RED:
        return f"⛔ Web search blocked for privacy: {reason}"

    # Scrub PII from query before it hits the web
    clean_query, _ = scrubber.scrub(query)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(clean_query, max_results=5))

        if not results:
            return "No web results found."

        formatted = []
        for r in results:
            formatted.append(f"**{r['title']}**\n{r['body']}\n{r['href']}")

        return "\n\n---\n\n".join(formatted)

    except Exception as e:
        logger.error(f"[TOOL:web] DuckDuckGo error: {e}")
        return f"Web search failed: {str(e)}"
```

---

### `agent/tools/apify.py`
```python
"""
Tool: search_amazon
Apify Amazon scraper via MCP. ALWAYS private.
Results stored locally first, scrubbed before returning to LLM.
"""
from langchain_core.tools import tool
from agent.mcp.apify_tools import run_tool as apify_run
from agent.privacy.scrubber import PrivacyScrubber
from agent.memory.long_term import LongTermMemory
import logging

logger = logging.getLogger(__name__)
scrubber = PrivacyScrubber()
memory = LongTermMemory()


@tool
def search_amazon(query: str) -> str:
    """Search Amazon for product information, prices, and reviews using Apify.
    Use only when the user explicitly asks about purchasing, pricing, or
    product comparisons. Results are kept private."""

    import asyncio
    raw = asyncio.run(apify_run({"query": query}))

    # Store raw result locally FIRST (before scrubbing)
    memory.store_fact(f"Amazon search '{query}': {str(raw)[:500]}", category="amazon_search")

    # Scrub before returning to LLM
    clean, replacements = scrubber.scrub(str(raw))
    logger.info(f"[TOOL:apify] Scrubbed {len(replacements)} entities from Amazon results")

    return clean if clean else "No Amazon results found."
```

---

### `agent/tools/filesystem.py`
```python
"""
Tools: read_file, list_files
Filesystem MCP wrapper. Restricted to vault path only.
"""
from langchain_core.tools import tool
from agent.mcp.filesystem_tools import run_tool as fs_run
import asyncio


@tool
def read_file(path: str) -> str:
    """Read the contents of a specific file from the local filesystem or
    Obsidian vault. Provide the relative path from the vault root."""
    return asyncio.run(fs_run({"query": path}))


@tool
def list_files(directory: str = "") -> str:
    """List files in a directory within the Obsidian vault or local filesystem.
    Useful for browsing available notes or files."""
    from agent.obsidian.vault import ObsidianVault
    from agent.config import settings
    vault = ObsidianVault(settings.OBSIDIAN_VAULT_PATH)
    results = vault.search("", folder=directory or None)
    if not results:
        return f"No files found in '{directory or 'vault root'}'"
    return "\n".join(f"- {r['path']}" for r in results)
```

---

### `agent/tools/obsidian_write.py`
```python
"""
Tools: create_note, append_to_note
Let the LLM write back to the vault — for saving answers, insights, summaries.
Also handles Q&A pair storage (replaces store_response node).
"""
from langchain_core.tools import tool
from agent.obsidian.vault import ObsidianVault
from agent.rag.embedder import Embedder
from agent.rag.store import VectorStore
from agent.config import settings
from datetime import datetime

vault = ObsidianVault(settings.OBSIDIAN_VAULT_PATH)
embedder = Embedder()
vector_store = VectorStore()


@tool
def create_note(title: str, content: str, folder: str = "Agent/Saved") -> str:
    """Create a new note in the Obsidian vault. Use this when the user asks to
    save something, or when you want to preserve an insight, answer, or summary
    for future reference. Folder defaults to Agent/Saved."""

    path = vault.create_note(folder=folder, title=title, content=content)

    # Also embed it so future searches can find it
    embedding = embedder.embed(content)
    vector_store.upsert(
        collection="obsidian_vault",
        text=content,
        embedding=embedding,
        metadata={
            "folder": folder,
            "source_hash": title,
            "type": "saved_note",
            "timestamp": datetime.now().isoformat(),
            "can_send_to_llm": True,
        }
    )

    return f"✅ Note '{title}' saved to {folder}/"


@tool
def append_to_note(filename: str, content: str) -> str:
    """Append new content to an existing Obsidian note. Use when updating
    an existing note rather than creating a new one."""

    vault.append_to_note(filename, content)
    return f"✅ Appended to '{filename}'"


def store_qa_pair(query: str, answer: str, source: str = "agent"):
    """
    Called internally after each response to persist Q&A pairs.
    NOT a LLM-callable tool — called from cli.py after each turn.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"## Question\n{query}\n\n## Answer\n{answer}"
    title = f"QA {datetime.now().strftime('%Y%m%d_%H%M%S')}"

    vault.create_note(
        folder=f"{settings.AGENT_NOTES_FOLDER}/Responses",
        title=title,
        content=f"---\ntype: agent-response\nsource: {source}\ndate: {timestamp}\n---\n\n{content}",
    )

    combined = f"Q: {query}\nA: {answer}"
    embedding = embedder.embed(combined)
    vector_store.upsert(
        collection="obsidian_vault",
        text=combined,
        embedding=embedding,
        metadata={
            "folder": f"{settings.AGENT_NOTES_FOLDER}/Responses",
            "source": source,
            "timestamp": timestamp,
            "type": "qa_pair",
            "can_send_to_llm": True,
        }
    )
```

---

### NEW — `agent/cli.py` (replaces Phase 11)
```python
"""
Terminal chat interface — ChatGPT-like conversation loop.
Streaming output via rich. Full conversation memory via SqliteSaver.
"""
import asyncio
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from agent.graph.agent import agent
from agent.tools.obsidian_write import store_qa_pair
from agent.tools.vault_search import _store_query
from agent.memory.long_term import LongTermMemory
from agent.obsidian.ingester import VaultIngester
from agent.scheduler.digest import start_scheduler
from agent.config import settings
import logging

logging.basicConfig(level=settings.LOG_LEVEL)
console = Console()
memory = LongTermMemory()

THREAD_CONFIG = {"configurable": {"thread_id": settings.THREAD_ID}}

HELP_TEXT = """
[bold cyan]Commands:[/bold cyan]
  [green]/memory[/green]    — Show recently learned facts
  [green]/reindex[/green]   — Re-index your Obsidian vault
  [green]/thread <id>[/green] — Switch conversation thread (fresh context)
  [green]/help[/green]      — Show this message
  [green]/quit[/green]      — Exit
"""

async def chat():
    console.print(Panel.fit(
        "[bold cyan]Personal Agent[/bold cyan]\n"
        "[dim]Vault-first · Privacy-first · OpenRouter[/dim]\n"
        "[dim]Type /help for commands[/dim]",
        border_style="cyan",
    ))

    thread_config = THREAD_CONFIG

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        # ── Commands ─────────────────────────────────────────────────
        if user_input.strip().lower() in ["/quit", "/exit", "quit"]:
            break

        if user_input.strip().lower() == "/help":
            console.print(HELP_TEXT)
            continue

        if user_input.strip().lower() == "/memory":
            facts = memory.get_recent_facts(limit=15)
            if facts:
                console.print(Panel(
                    "\n".join(f"• {f}" for f in facts),
                    title="[bold]Recently Learned[/bold]",
                    border_style="yellow",
                ))
            else:
                console.print("[dim]No learned facts yet.[/dim]")
            continue

        if user_input.strip().lower() == "/reindex":
            with console.status("[yellow]Re-indexing vault...[/yellow]"):
                VaultIngester().ingest(force=True)
            console.print("[green]✅ Vault re-indexed.[/green]")
            continue

        if user_input.strip().lower().startswith("/thread "):
            new_thread = user_input.strip().split(" ", 1)[1].strip()
            thread_config = {"configurable": {"thread_id": new_thread}}
            console.print(f"[cyan]Switched to thread: {new_thread}[/cyan]")
            continue

        # ── Agent call ───────────────────────────────────────────────
        console.print()
        answer = ""
        tool_calls_made = []

        try:
            with console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                result = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": user_input}]},
                    config=thread_config,
                )

            # Extract final message
            messages = result.get("messages", [])
            final = messages[-1] if messages else None
            answer = final.content if final else "No response."

            # Collect tool calls for display
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls_made.append(tc.get("name", "unknown"))

        except Exception as e:
            answer = f"Error: {str(e)}"
            console.print(f"[red]{answer}[/red]")
            continue

        # ── Display response ─────────────────────────────────────────
        subtitle = ""
        if tool_calls_made:
            tools_str = " · ".join(f"[dim]{t}[/dim]" for t in tool_calls_made)
            subtitle = f"Tools used: {tools_str}"

        console.print(Panel(
            Markdown(answer),
            title="[bold blue]Agent[/bold blue]",
            subtitle=subtitle or None,
            border_style="blue",
        ))

        # ── Background: store Q&A pair + learn ──────────────────────
        if answer and "⛔" not in answer:
            asyncio.create_task(_background_learn(user_input, answer))


async def _background_learn(query: str, answer: str):
    """Fire-and-forget: store Q&A + extract learned facts. Doesn't block chat."""
    try:
        store_qa_pair(query, answer)
        await _extract_facts(query, answer)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Background learn failed: {e}")


async def _extract_facts(query: str, answer: str):
    """Extract learnable facts from the interaction using the fast model."""
    from agent.llm.openrouter import openrouter_chat
    from agent.memory.long_term import LongTermMemory
    import json

    mem = LongTermMemory()
    prompt = f"""Extract 0-2 concise facts worth remembering from this exchange.
Return ONLY a JSON array of short strings. Return [] if nothing notable.

Q: {query}
A: {answer[:400]}

JSON:"""

    try:
        raw = await openrouter_chat(
            system="Extract facts. Return only a JSON array of strings.",
            user=prompt,
            model_override=settings.FAST_MODEL,
            max_tokens=150,
        )
        raw = raw.strip().replace("```json", "").replace("```", "")
        facts = json.loads(raw)
        for fact in facts[:2]:
            if isinstance(fact, str) and len(fact) > 5:
                mem.store_fact(fact, category="interaction")
    except Exception:
        pass  # Non-critical


def main():
    start_scheduler()
    asyncio.run(chat())


if __name__ == "__main__":
    main()
```

---

## UPDATED PROJECT STRUCTURE

Replace the `graph/` and `tools/` sections in the original plan with:

```
agent/
├── graph/
│   └── agent.py              ← NEW: replaces entire graph/ folder
│
├── tools/                    ← NEW: replaces graph/nodes/
│   ├── __init__.py
│   ├── vault_search.py       ← RAG + privacy + folder policy (was 4 nodes)
│   ├── web.py                ← DuckDuckGo (was tool_router node)
│   ├── apify.py              ← Amazon scraper (was tool_router node)
│   ├── filesystem.py         ← File read/list (was tool_router node)
│   └── obsidian_write.py     ← Create/append + Q&A storage (was store_response node)
│
├── privacy/                  ← UNCHANGED
├── obsidian/                 ← UNCHANGED
├── rag/                      ← UNCHANGED
├── llm/                      ← UNCHANGED
├── mcp/                      ← UNCHANGED
├── memory/                   ← UNCHANGED
├── scheduler/                ← UNCHANGED
└── cli.py                    ← REPLACED (simpler version above)
```

---

## UPDATED IMPLEMENTATION ORDER

Replace Phase 3, 4, 11 in the original order with:

```
1.  .env + config.py + docker-compose.yml
2.  agent/obsidian/folder_policy.py           ← access rules first
3.  agent/privacy/ (all 3 files)              ← privacy layer
4.  agent/rag/embedder.py + store.py          ← vector DB
5.  agent/obsidian/ingester.py → ingest vault ← verify in Qdrant
6.  agent/obsidian/vault.py
7.  agent/llm/openrouter.py → test one call
8.  agent/tools/vault_search.py               ← most important tool
9.  agent/tools/web.py
10. agent/tools/apify.py
11. agent/tools/filesystem.py
12. agent/tools/obsidian_write.py
13. agent/mcp/filesystem_tools.py
14. agent/mcp/apify_tools.py
15. agent/memory/long_term.py
16. agent/graph/agent.py                      ← wire everything together
17. agent/cli.py                              ← run it
18. agent/scheduler/digest.py
19. tests/
```

---

## UPDATED `requirements.txt` DELTA

Add these two lines (rest stays the same):
```
langchain-openai==0.1.22     # ChatOpenAI wrapper for OpenRouter
asyncio-compat==0.1.2        # asyncio.create_task inside non-async context
```

Remove this line (no longer needed):
```
# langchain-community   ← only needed if using LangChain-specific loaders
```

---

## KEY BEHAVIOUR DIFFERENCES FROM OLD PLAN

| Old (custom graph) | New (create_react_agent) |
|---|---|
| Routing hardcoded in `edges.py` | LLM decides which tool to call |
| Must predict every possible flow | LLM handles unexpected queries naturally |
| Confidence check as a node | LLM naturally says "I don't know" |
| Tool router as a node | LLM reads docstrings, decides itself |
| 10 files for graph logic | 1 file (`agent.py`) |
| Fixed execution order | Dynamic, multi-step tool chains |
| Can't chain tools unless coded | LLM can call vault → web → create_note in one turn |
| Hard to add new capability | Add one `@tool` function, agent learns it automatically |
```
