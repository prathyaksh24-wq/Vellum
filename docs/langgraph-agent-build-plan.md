# Personal LangGraph Agent — Full Build Plan
> Privacy-first, Obsidian-native, self-learning agent using LangGraph + OpenRouter
> Paste this into Claude Code or Codex as your project specification.

---

## SUGGESTIONS BEFORE BUILDING

Before diving into code, here are recommended additions based on your requirements:

### ✅ Additions Recommended

1. **Confidence Threshold Node** — If retrieval score is below a threshold (e.g. 0.65 cosine similarity), the agent explicitly says "I don't have enough information about this in my vault" instead of hallucinating. This is critical since you want answers ONLY from your data.

2. **Folder Access Policy as a Graph Node** — A dedicated `access_control` node in the LangGraph graph that checks which Obsidian folders are allowed per query. Sports is accessible; X, YouTube, Books, Feedback are private-only (stored + learned from, but never sent to OpenRouter raw).

3. **Query Deduplication** — Before storing a query to Obsidian + vector DB, check if a very similar query already exists (cosine similarity > 0.92). Avoids vault pollution with near-duplicate entries.

4. **Apify Data Privacy Wrapper** — Amazon scraper results contain product names, prices, ASINs. Strip or hash identifiers before any of that data touches the LLM prompt. The scraped data lives locally; only sanitized summaries go to OpenRouter.

5. **LangGraph Checkpointing** — Use LangGraph's built-in `SqliteSaver` checkpointer so conversation threads persist across sessions. You can resume any conversation by thread ID. This is what gives it the ChatGPT-like memory feel.

6. **Local Cross-Encoder Reranker** — After vector retrieval, run a local cross-encoder (`ms-marco-MiniLM-L-6-v2`, ~80MB) to rerank chunks by true relevance before sending to LLM. Dramatically improves answer quality with no API cost.

7. **Web Search Privacy Gate** — A graph node that evaluates query importance before deciding whether to use Apify for web search. Uses a simple local classifier: high-importance = search allowed, low-importance = vault only. You define the rules.

8. **Async streaming CLI** — Since no frontend, use `rich` library for a clean terminal chat interface with streaming output. Feels professional and lets you see tool calls live.

9. **Self-learning via nightly digest** — A background job that runs on a schedule, reads recent interactions from SQLite, extracts structured insights using a cheap fast model (e.g. Gemma 4 12B via OpenRouter), and writes summary notes back to your Obsidian vault in a `/Agent` folder.

### ⚠️ One Important Constraint to Clarify

Since the agent answers **only from Obsidian + vector DB**, you need to pre-populate your vault well. The agent will be as good as your notes. The self-learning loop helps this grow over time — every good Q&A pair becomes a note that future queries can retrieve.

---

## TECH STACK

| Layer | Tool | Reason |
|---|---|---|
| Agent Framework | **LangGraph 0.2+** | Stateful graph, native tool calling, checkpointing |
| LLM Orchestration | **LangChain Core** | Works alongside LangGraph, model wrappers |
| LLM API | **OpenRouter** | Access Gemma 4 31B / Qwen3.5, ZDR enforced |
| Vector DB | **Qdrant** (Docker) | Local, fast, namespace/collection per folder |
| Embedding | **BGE-M3** (local HuggingFace) | No API, multilingual, best-in-class retrieval |
| Reranker | **cross-encoder/ms-marco-MiniLM-L-6-v2** | Local, fast reranking |
| PII Scrubber | **Microsoft Presidio** | 100% local, production-grade |
| Obsidian I/O | **Python pathlib + watchdog** | Watch vault for changes, read/write notes |
| MCP Servers | **Filesystem MCP** + **Apify MCP** | Tool connectors |
| MCP Client | **mcp Python SDK** | Connect to MCP servers from LangGraph |
| Persistence | **SqliteSaver** (LangGraph) | Conversation checkpointing |
| Memory DB | **SQLite** | Long-term learned facts, query history |
| CLI Interface | **rich** + **asyncio** | Terminal chat with streaming |
| Config | **pydantic-settings** + **python-dotenv** | Type-safe settings |
| Scheduler | **APScheduler** | Nightly self-learning digest |
| Language | **Python 3.11+** | LangGraph's primary language |

---

## PROJECT STRUCTURE

```
personal-agent/
├── .env                              # Secrets — never committed
├── .gitignore
├── docker-compose.yml                # Qdrant only
├── requirements.txt
├── pyproject.toml                    # Project metadata
│
├── agent/
│   ├── __init__.py
│   ├── cli.py                        # Replaced terminal chat interface
│   ├── config.py                     # Pydantic settings loader
│   │
│   ├── graph/
│   │   └── agent.py                  # ReAct agent wiring via create_react_agent
│   │
│   ├── tools/                        # LLM-callable tools; privacy lives inside tools
│   │   ├── __init__.py
│   │   ├── vault_search.py           # RAG + privacy + folder policy
│   │   ├── web.py                    # DuckDuckGo, privacy-gated
│   │   ├── apify.py                  # Amazon scraper, always private
│   │   ├── filesystem.py             # File read/list
│   │   └── obsidian_write.py         # Create/append + Q&A storage
│   │
│   ├── privacy/
│   │   ├── __init__.py
│   │   ├── scrubber.py               # Presidio PII anonymizer
│   │   ├── classifier.py             # RED/YELLOW/GREEN with folder awareness
│   │   └── metadata_strip.py         # Strip Obsidian frontmatter, paths, tags
│   │
│   ├── obsidian/
│   │   ├── __init__.py
│   │   ├── vault.py                  # Read/write/search Obsidian notes
│   │   ├── ingester.py               # Bulk ingest vault into Qdrant
│   │   ├── watcher.py                # watchdog: auto-reindex on vault changes
│   │   └── folder_policy.py          # Folder access rules (private/accessible)
│   │
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── embedder.py               # BGE-M3 embedding wrapper
│   │   ├── store.py                  # Qdrant client wrapper
│   │   ├── retriever.py              # Semantic search + dedup
│   │   └── reranker.py               # Cross-encoder reranker
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   └── openrouter.py             # LangChain-compatible OpenRouter client (ZDR)
│   │
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── client.py                 # MCP client manager (connects to servers)
│   │   ├── filesystem_tools.py       # Filesystem MCP tool wrappers
│   │   └── apify_tools.py            # Apify MCP tool wrappers (Amazon scraper)
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── short_term.py             # LangGraph checkpointer (SqliteSaver)
│   │   └── long_term.py              # SQLite learned facts, query log
│   │
│   └── scheduler/
│       ├── __init__.py
│       └── digest.py                 # Nightly self-learning background job
│
├── data/
│   ├── memory/
│   │   ├── checkpoints.db            # LangGraph thread checkpoints
│   │   ├── long_term.db              # Learned facts, preferences
│   │   └── audit_log.jsonl           # Local API call audit (no content)
│   └── embeddings/                   # Qdrant Docker volume
│
├── scripts/
│   ├── setup.sh                      # First-time setup script
│   └── ingest_vault.py               # One-time bulk ingestion
│
└── tests/
    ├── test_privacy.py               # PII leak tests (run before every deploy)
    ├── test_tools.py                 # Tool behavior and privacy tests
    ├── test_retrieval.py             # RAG quality tests
    └── test_access_control.py        # Folder policy tests
```

---

## PHASE 1 — CONFIGURATION

### `.env`
```env
# OpenRouter
OPENROUTER_API_KEY=your_key_here
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
PRIMARY_MODEL=google/gemma-4-31b-it
FALLBACK_MODEL=qwen/qwen3.5-35b-a3b
FAST_MODEL=google/gemma-3-12b-it       # Used for classify/learn tasks

# Obsidian
OBSIDIAN_VAULT_PATH=/absolute/path/to/your/vault
AGENT_NOTES_FOLDER=Agent               # Where agent writes learned notes

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Privacy
ENABLE_PII_SCRUBBING=true
ZDR_ONLY=true
MIN_RETRIEVAL_SCORE=0.65               # Confidence threshold
MAX_CONTEXT_CHUNKS=5
MAX_CONTEXT_TOKENS=3000

# MCP Servers
FILESYSTEM_MCP_PATH=/absolute/path/to/filesystem-mcp
APIFY_API_TOKEN=your_apify_token_here

# Agent
THREAD_ID=default                      # Conversation thread (change for new sessions)
LOG_LEVEL=INFO
ENABLE_NIGHTLY_DIGEST=true
```

### `agent/config.py`
```python
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    # OpenRouter
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    PRIMARY_MODEL: str = "google/gemma-4-31b-it"
    FALLBACK_MODEL: str = "qwen/qwen3.5-35b-a3b"
    FAST_MODEL: str = "google/gemma-3-12b-it"

    # Obsidian
    OBSIDIAN_VAULT_PATH: str
    AGENT_NOTES_FOLDER: str = "Agent"

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Privacy
    ENABLE_PII_SCRUBBING: bool = True
    ZDR_ONLY: bool = True
    MIN_RETRIEVAL_SCORE: float = 0.65
    MAX_CONTEXT_CHUNKS: int = 5
    MAX_CONTEXT_TOKENS: int = 3000

    # MCP
    FILESYSTEM_MCP_PATH: str = ""
    APIFY_API_TOKEN: str = ""

    # Agent
    THREAD_ID: str = "default"
    LOG_LEVEL: str = "INFO"
    ENABLE_NIGHTLY_DIGEST: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## PHASE 2 — FOLDER ACCESS POLICY

This is the core of your privacy model. Every node checks this before touching any data.

### `agent/obsidian/folder_policy.py`
```python
"""
Defines which Obsidian folders can be:
- STORED: query/response written as a note
- INDEXED: embedded into Qdrant for retrieval
- SENT_TO_LLM: chunks from this folder allowed in LLM prompt context
- TOOL_ACCESSIBLE: Apify/web search allowed for topics in this folder

Private folders are stored + indexed locally, but chunks are NEVER
sent to OpenRouter raw. They are used only for local retrieval answers
or anonymized before any cloud call.
"""
from enum import Enum
from typing import Set
from dataclasses import dataclass

class FolderPermission(Enum):
    STORED = "stored"           # Saved to Obsidian
    INDEXED = "indexed"         # Embedded in Qdrant
    SENT_TO_LLM = "sent_to_llm"  # Context chunks sent to OpenRouter
    TOOL_ACCESSIBLE = "tool_accessible"  # Web/Apify search allowed

@dataclass
class FolderPolicy:
    name: str
    permissions: Set[FolderPermission]
    requires_scrubbing: bool = True

# ============================================================
# DEFINE YOUR FOLDER POLICIES HERE
# ============================================================
FOLDER_POLICIES: dict[str, FolderPolicy] = {
    # Private folders — stored + indexed locally ONLY
    # Chunks are NEVER sent to OpenRouter in raw form
    "X": FolderPolicy(
        name="X",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED},
        requires_scrubbing=True,
    ),
    "youtube": FolderPolicy(
        name="youtube",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED},
        requires_scrubbing=True,
    ),
    "Books": FolderPolicy(
        name="Books",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED},
        requires_scrubbing=True,
    ),
    "feedback": FolderPolicy(
        name="feedback",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED},
        requires_scrubbing=True,
    ),

    # Sports folder — accessible (can send chunks to LLM + allow web search)
    "Sports": FolderPolicy(
        name="Sports",
        permissions={
            FolderPermission.STORED,
            FolderPermission.INDEXED,
            FolderPermission.SENT_TO_LLM,
            FolderPermission.TOOL_ACCESSIBLE,
        },
        requires_scrubbing=False,  # Sports data generally not PII-heavy
    ),
    # Sports sub-folders inherit Sports policy
    "Sports/NBA": FolderPolicy(
        name="Sports/NBA",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED,
                     FolderPermission.SENT_TO_LLM, FolderPermission.TOOL_ACCESSIBLE},
        requires_scrubbing=False,
    ),
    "Sports/Formula One": FolderPolicy(
        name="Sports/Formula One",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED,
                     FolderPermission.SENT_TO_LLM, FolderPermission.TOOL_ACCESSIBLE},
        requires_scrubbing=False,
    ),
    "Sports/football": FolderPolicy(
        name="Sports/football",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED,
                     FolderPermission.SENT_TO_LLM, FolderPermission.TOOL_ACCESSIBLE},
        requires_scrubbing=False,
    ),
    "Sports/Tennis": FolderPolicy(
        name="Sports/Tennis",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED,
                     FolderPermission.SENT_TO_LLM, FolderPermission.TOOL_ACCESSIBLE},
        requires_scrubbing=False,
    ),
    # Agent-generated notes — always accessible
    "Agent": FolderPolicy(
        name="Agent",
        permissions={FolderPermission.STORED, FolderPermission.INDEXED,
                     FolderPermission.SENT_TO_LLM},
        requires_scrubbing=False,
    ),
}

DEFAULT_POLICY = FolderPolicy(
    name="default",
    permissions={FolderPermission.STORED, FolderPermission.INDEXED},
    requires_scrubbing=True,
)

def get_policy(folder_path: str) -> FolderPolicy:
    """Get policy for a folder path. Checks exact match then parent folders."""
    if folder_path in FOLDER_POLICIES:
        return FOLDER_POLICIES[folder_path]
    # Check parent folders
    parts = folder_path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        parent = "/".join(parts[:i])
        if parent in FOLDER_POLICIES:
            return FOLDER_POLICIES[parent]
    return DEFAULT_POLICY

def can_send_to_llm(folder_path: str) -> bool:
    return FolderPermission.SENT_TO_LLM in get_policy(folder_path).permissions

def can_use_tools(folder_path: str) -> bool:
    return FolderPermission.TOOL_ACCESSIBLE in get_policy(folder_path).permissions

def needs_scrubbing(folder_path: str) -> bool:
    return get_policy(folder_path).requires_scrubbing
```

---

## PHASE 3 — REACT AGENT + TOOLS

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

## PHASE 5 — LLM LAYER

### `agent/llm/openrouter.py`
```python
"""
OpenRouter async client.
ZDR enforced on every call. Minimal headers. Local audit log.
"""
import httpx
import json
import logging
from datetime import datetime
from agent.config import settings

logger = logging.getLogger(__name__)

async def openrouter_chat(
    system: str,
    user: str,
    model_override: str = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> str:
    model = model_override or settings.PRIMARY_MODEL

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "provider": {
            "data_collection": "deny",   # Never allow provider training on our data
            "order": ["Fireworks", "Together", "DeepInfra"],
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "PersonalAgent",
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            resp = await client.post(
                f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            _audit(model=model, prompt_len=len(user), resp_len=len(answer))
            return answer

        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter error: {e}. Trying fallback model.")
            if model != settings.FALLBACK_MODEL:
                return await openrouter_chat(system, user, settings.FALLBACK_MODEL, max_tokens, temperature)
            raise

def _audit(model: str, prompt_len: int, resp_len: int):
    """Write metadata-only audit log locally. NO content logged."""
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "model": model,
        "prompt_tokens_approx": prompt_len // 4,
        "resp_tokens_approx": resp_len // 4,
    }
    with open("data/memory/audit_log.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
```

---

## PHASE 6 — MCP TOOL INTEGRATIONS

### `agent/mcp/filesystem_tools.py`
```python
"""
Filesystem MCP tool wrapper.
Connects to the official @modelcontextprotocol/server-filesystem MCP server.
Allowed paths: Obsidian vault only.
"""
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from agent.config import settings
import logging

logger = logging.getLogger(__name__)

SERVER_PARAMS = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", settings.OBSIDIAN_VAULT_PATH],
    env=None,
)

async def run_tool(params: dict) -> str:
    query = params.get("query", "")

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]

            # Try to read a file if query looks like a path
            if "/" in query or ".md" in query:
                if "read_file" in tool_names:
                    result = await session.call_tool("read_file", {"path": query})
                    return result.content[0].text if result.content else "File not found."

            # Otherwise list files
            if "list_directory" in tool_names:
                result = await session.call_tool(
                    "list_directory",
                    {"path": settings.OBSIDIAN_VAULT_PATH}
                )
                return result.content[0].text if result.content else "No files found."

    return "Filesystem tool: no matching operation."
```

### `agent/mcp/apify_tools.py`
```python
"""
Apify MCP tool wrapper — Amazon Product Scraper.
All Apify results are PRIVATE: stored locally, scrubbed before any LLM call.
"""
from mcp import ClientSession
from mcp.client.sse import sse_client
from agent.privacy.scrubber import PrivacyScrubber
from agent.memory.long_term import LongTermMemory
from agent.config import settings
import logging
import json

logger = logging.getLogger(__name__)
scrubber = PrivacyScrubber()
memory = LongTermMemory()

APIFY_MCP_URL = f"https://mcp.apify.com/sse?token={settings.APIFY_API_TOKEN}"

async def run_tool(params: dict) -> str:
    query = params.get("query", "")
    logger.info(f"[APIFY] Running Amazon search for: {query[:50]}")

    try:
        async with sse_client(APIFY_MCP_URL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call Apify Amazon scraper actor via MCP
                result = await session.call_tool(
                    "apify/amazon-product-scraper",
                    {
                        "searchQuery": query,
                        "maxItems": 5,
                        "scrapeProductDetails": False,
                    }
                )

                raw_text = result.content[0].text if result.content else "No results."

                # Parse + store full results LOCALLY before any scrubbing
                memory.store_fact(
                    f"Amazon search '{query}': {raw_text[:500]}",
                    category="amazon_search"
                )

                # Scrub PII + identifiers before returning (goes to LLM next)
                clean_text, replacements = scrubber.scrub(raw_text)
                logger.info(f"[APIFY] Scrubbed {len(replacements)} entities from Amazon results")

                return clean_text

    except Exception as e:
        logger.error(f"[APIFY] Error: {e}")
        return f"Apify search failed: {str(e)}"
```

---

## PHASE 7 — OBSIDIAN VAULT I/O

### `agent/obsidian/vault.py`
```python
"""
Read/write Obsidian notes. All I/O stays local.
"""
from pathlib import Path
from datetime import datetime
import re

class ObsidianVault:
    def __init__(self, vault_path: str):
        self.root = Path(vault_path)

    def create_note(self, folder: str, title: str, content: str) -> Path:
        target_dir = self.root / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r'[<>:"/\\|?*]', "-", title)
        target = target_dir / f"{safe_title}.md"
        target.write_text(content, encoding="utf-8")
        return target

    def read_note(self, relative_path: str) -> str:
        target = self.root / relative_path
        if not target.exists():
            return ""
        return target.read_text(encoding="utf-8", errors="ignore")

    def search(self, keyword: str, folder: str = None) -> list[dict]:
        search_root = self.root / folder if folder else self.root
        results = []
        for md in search_root.glob("**/*.md"):
            content = md.read_text(encoding="utf-8", errors="ignore")
            if keyword.lower() in content.lower():
                rel = md.relative_to(self.root)
                results.append({
                    "file": md.name,
                    "path": str(rel),
                    "folder": str(rel.parent),
                    "preview": content[:300],
                })
        return results[:10]

    def append_to_note(self, relative_path: str, content: str):
        target = self.root / relative_path
        if target.exists():
            with open(target, "a", encoding="utf-8") as f:
                f.write(f"\n\n{content}")
```

### `agent/obsidian/ingester.py`
```python
"""
Bulk ingest entire Obsidian vault into Qdrant.
Respects folder policies — all folders are indexed,
but metadata tracks which folder each chunk came from
so the reranker can enforce access control at query time.
"""
from pathlib import Path
from agent.rag.embedder import Embedder
from agent.rag.store import VectorStore
from agent.privacy.metadata_strip import strip_obsidian_metadata, safe_chunk_id
from agent.privacy.scrubber import PrivacyScrubber
from agent.obsidian.folder_policy import get_policy, FolderPermission
from agent.config import settings
import logging

logger = logging.getLogger(__name__)

CHUNK_SIZE = 400   # tokens approximate (chars / 4)
CHUNK_OVERLAP = 50

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), size - overlap):
        chunk = " ".join(words[i:i + size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks

class VaultIngester:
    def __init__(self):
        self.embedder = Embedder()
        self.store = VectorStore()
        self.scrubber = PrivacyScrubber()
        self.vault_root = Path(settings.OBSIDIAN_VAULT_PATH)

    def ingest(self, force: bool = False):
        md_files = list(self.vault_root.glob("**/*.md"))
        logger.info(f"Ingesting {len(md_files)} notes...")

        for md_file in md_files:
            rel_path = md_file.relative_to(self.vault_root)
            folder = str(rel_path.parent)
            policy = get_policy(folder)

            # All folders get indexed — policy controls LLM access, not indexing
            if FolderPermission.INDEXED not in policy.permissions:
                continue

            raw = md_file.read_text(encoding="utf-8", errors="ignore")
            clean = strip_obsidian_metadata(raw, str(md_file))

            if not clean.strip():
                continue

            # Scrub PII from private folder content before embedding
            if policy.requires_scrubbing:
                clean, _ = self.scrubber.scrub(clean)

            chunks = chunk_text(clean)
            for i, chunk in enumerate(chunks):
                embedding = self.embedder.embed(chunk)
                self.store.upsert(
                    collection="obsidian_vault",
                    text=chunk,
                    embedding=embedding,
                    metadata={
                        "folder": folder,
                        "source_hash": safe_chunk_id(str(md_file), i),
                        "chunk_index": i,
                        "can_send_to_llm": FolderPermission.SENT_TO_LLM in policy.permissions,
                    }
                )

        logger.info("Vault ingestion complete.")
```

---

## PHASE 8 — RAG COMPONENTS

### `agent/rag/embedder.py`
```python
"""BGE-M3 local embedding. Runs fully offline."""
from sentence_transformers import SentenceTransformer
import numpy as np

class Embedder:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.model = SentenceTransformer("BAAI/bge-m3")
        return cls._instance

    def embed(self, text: str) -> list[float]:
        vec = self.model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vecs = self.model.encode(texts, normalize_embeddings=True, batch_size=32)
        return vecs.tolist()
```

### `agent/rag/store.py`
```python
"""Qdrant vector store wrapper. Local Docker instance."""
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter,
    FieldCondition, MatchValue, ScoredPoint,
)
from agent.config import settings
import uuid
import logging

logger = logging.getLogger(__name__)
VECTOR_SIZE = 1024  # BGE-M3 dimension

class VectorStore:
    def __init__(self):
        self.client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        self._ensure_collections()

    def _ensure_collections(self):
        existing = [c.name for c in self.client.get_collections().collections]
        for name in ["obsidian_vault", "agent_queries"]:
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                logger.info(f"Created Qdrant collection: {name}")

    def upsert(self, collection: str, text: str, embedding: list[float], metadata: dict):
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={"text": text, **metadata},
        )
        self.client.upsert(collection_name=collection, points=[point])

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 10,
        score_threshold: float = 0.0,
    ) -> list[dict]:
        results = self.client.search(
            collection_name=collection,
            query_vector=embedding,
            limit=top_k,
            score_threshold=score_threshold,
        )
        return [
            {"text": r.payload.get("text", ""), "score": r.score, "metadata": r.payload}
            for r in results
        ]
```

---

## PHASE 9 — MEMORY

### `agent/memory/long_term.py`
```python
"""SQLite long-term memory. Stores learned facts, preferences, search results."""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data/memory/long_term.db")

class LongTermMemory:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    category TEXT,
                    content TEXT,
                    access_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    query TEXT,
                    answer_source TEXT,
                    confidence REAL
                )
            """)

    def store_fact(self, content: str, category: str = "general"):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO facts (timestamp, category, content) VALUES (?, ?, ?)",
                (datetime.utcnow().isoformat(), category, content)
            )

    def log_query(self, query: str, source: str, confidence: float):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO query_log (timestamp, query, answer_source, confidence) VALUES (?, ?, ?, ?)",
                (datetime.utcnow().isoformat(), query, source, confidence)
            )

    def get_recent_facts(self, category: str = None, limit: int = 20) -> list[str]:
        with sqlite3.connect(DB_PATH) as conn:
            if category:
                rows = conn.execute(
                    "SELECT content FROM facts WHERE category=? ORDER BY id DESC LIMIT ?",
                    (category, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT content FROM facts ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [r[0] for r in rows]
```

---

## PHASE 10 — NIGHTLY DIGEST (Self-Learning)

### `agent/scheduler/digest.py`
```python
"""
Nightly self-learning batch job.
Reads recent Q&A pairs from SQLite, extracts structured knowledge,
writes summary notes back to Obsidian/Agent/Digests/.
Runs at 2am locally via APScheduler.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from agent.memory.long_term import LongTermMemory
from agent.obsidian.vault import ObsidianVault
from agent.llm.openrouter import openrouter_chat
from agent.config import settings
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)
memory = LongTermMemory()
vault = ObsidianVault(settings.OBSIDIAN_VAULT_PATH)

async def run_digest():
    logger.info("[DIGEST] Starting nightly self-learning digest...")

    facts = memory.get_recent_facts(limit=50)
    if not facts:
        logger.info("[DIGEST] No new facts to digest.")
        return

    facts_text = "\n".join(f"- {f}" for f in facts)
    prompt = f"""Summarize these learned facts into 3-5 key insights about the user's interests and knowledge gaps.
Return a clean markdown summary.

Facts:
{facts_text}

Summary:"""

    summary = await openrouter_chat(
        system="You summarize knowledge into concise markdown insights.",
        user=prompt,
        model_override=settings.FAST_MODEL,
    )

    date_str = datetime.now().strftime("%Y-%m-%d")
    vault.create_note(
        folder=f"{settings.AGENT_NOTES_FOLDER}/Digests",
        title=f"Digest {date_str}",
        content=f"# Knowledge Digest — {date_str}\n\n{summary}",
    )

    logger.info(f"[DIGEST] Digest written to Obsidian for {date_str}")

def start_scheduler():
    if not settings.ENABLE_NIGHTLY_DIGEST:
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_digest, "cron", hour=2, minute=0)
    scheduler.start()
    logger.info("[DIGEST] Nightly digest scheduler started (runs at 2:00 AM)")
```

---

## PHASE 11 — CLI ENTRY POINT

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

## PHASE 12 — REQUIREMENTS + SETUP

### `requirements.txt`
```
# LangGraph + LangChain
langgraph==0.2.28
langchain-core==0.2.38
langchain-openai==0.1.22     # ChatOpenAI wrapper for OpenRouter
asyncio-compat==0.1.2        # asyncio.create_task inside non-async context

# OpenRouter (via httpx directly)
httpx==0.27.0

# Vector DB
qdrant-client==1.9.1

# Embeddings + Reranking
sentence-transformers==3.0.1
torch==2.3.0           # CPU build is fine for embedding/reranking

# Privacy
presidio-analyzer==2.2.354
presidio-anonymizer==2.2.354
spacy==3.7.4

# MCP
mcp==1.0.0

# Obsidian file watching
watchdog==4.0.0

# Memory + Persistence
sqlalchemy==2.0.30

# Scheduling
apscheduler==3.10.4

# CLI
rich==13.7.1

# Config
pydantic-settings==2.2.1
python-dotenv==1.0.1

# Testing
pytest==8.2.0
pytest-asyncio==0.23.7
```

### `scripts/setup.sh`
```bash
#!/bin/bash
set -e
echo "🚀 Setting up Personal Agent..."

# Python deps
pip install -r requirements.txt

# spaCy model for Presidio
python -m spacy download en_core_web_lg

# MCP filesystem server
npm install -g @modelcontextprotocol/server-filesystem

# Start Qdrant
docker compose up -d qdrant
echo "Waiting for Qdrant..."
sleep 3

# Create data dirs
mkdir -p data/memory data/embeddings

# First-time vault ingestion
python scripts/ingest_vault.py

echo ""
echo "✅ Setup complete!"
echo "Run: python -m agent.cli"
```

### `scripts/ingest_vault.py`
```python
import asyncio
from agent.obsidian.ingester import VaultIngester

if __name__ == "__main__":
    ingester = VaultIngester()
    ingester.ingest(force=True)
    print("Done.")
```

---

## IMPLEMENTATION ORDER

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

---

## CRITICAL IMPLEMENTATION RULES

- **Never** send raw Obsidian note content to OpenRouter — always scrub first
- **Never** log prompt content to `audit_log.jsonl` — metadata only (token counts, timestamps, model name)
- **Always** check `can_send_to_llm()` before adding any chunk to `context_string`
- **Always** set `"data_collection": "deny"` in every single OpenRouter request
- **Apify results** must be stored locally first, then scrubbed, before any LLM sees them
- **Folder policies** are the source of truth — no hardcoded folder names anywhere else
- **BGE-M3** and **cross-encoder** both run offline — never call external embedding APIs
- **SqliteSaver** checkpointer gives you full conversation history across sessions via `thread_id`
- Run `tests/test_privacy.py` and `tests/test_access_control.py` after every change to privacy or policy code
