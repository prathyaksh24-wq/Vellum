# How Hermes Implements Tool Search (Progressive Tool Disclosure)

Reference: Hermes repo cloned at `C:\Users\User\AppData\Local\Temp\opencode\hermes-agent`.
Primary sources: `website/docs/user-guide/features/tool-search.md` and `tools/tool_search.py` (implemented by OpenClaw).

## 1. The problem

When many MCP / plugin tools are attached, their JSON schemas all get serialized
into the model-visible tools array every turn. That consumes context and degrades
tool selection quality. Hermes solves it with **progressive disclosure**: the
model only ever sees the tools it needs; the rest are hidden behind a searchable
bridge and loaded on demand.

## 2. The bridge tools

The model-visible tools array is replaced with three bridge tools:

- `tool_search(query, limit?)` — BM25 search over the deferred-tool catalog.
  Returns ranked matches (name, short description, required params).
- `tool_describe(name)` — full schema for one tool (only its schema, no body).
- `tool_call(name, arguments)` — executes a deferred tool by name; arguments
  are validated against the tool's own args schema.

Core agent tools **never defer** (they are always in the visible array, Tier 0).
Only MCP / non-core plugin tools defer.

## 3. Classification and assembly

`classify_tools` puts every tool def into a tier:

- **Tier 0** — core tools: passed through untouched.
- **Tier 1** — deferred tools fit the listing budget: bridge + compact listing.
- **Tier 2** — deferred tools that don't fit: bare bridge + per-source summary
  (the listing is dropped, sources are summarized instead).

The listing budget is `min(threshold_pct of context length (~5%), listing_max_tokens)`.
If the full listing doesn't fit, it degrades gracefully: full listing → names-only → nothing.

`should_activate` checks the config (`enabled: auto|true|false`) and the
deferred-token estimate. `estimate_tokens_from_schemas` estimates token cost of
the serialized defs so the decision can be made before the model sees anything.

The assembly entry point produces an `AssemblyResult` recording what happened:
`activated`, `tier`, `deferred_count`, `deferred_tokens`, `threshold_tokens`,
`listing_form` (full/names/none), plus the final `tool_defs` list.

## 4. The catalog (BM25 retrieval)

A `CatalogEntry` is built per deferred tool:

- Searchable text = lowercased name (snake/dot/dash split into words) +
  description + top-level parameter names.
- Schema bodies are excluded from the index.
- Scoring is standard BM25 (no TF-IDF needed; small corpus).
- `search_catalog(catalog, query, limit)` returns ranked entries; when nothing
  matches, it returns the available sources (e.g. "github", "slack") as hints
  so the model can retry with a different wording.

The catalog is rebuilt **statelessly on every assembly** — nothing is cached
across turns. (OpenClaw learned this the hard way: a cached catalog went stale
when plugin tools changed between turns and broke the cron runtime —
openclaw/openclaw#84141.)

## 5. Config

`ToolSearchConfig.from_raw` accepts `True`, `False`, or a dict
(`{"enabled": "auto", ...}`). `enabled: "auto"` means: activate only when the
estimated deferred token count justifies it. Threshold and listing budget are
separate fields.

## 6. What Vellum already has

- `backend/agent/graph/agent.py` — `core_tool_registry()` (ToolRegistry with
  permission wrappers), `core_tools()` (registry-backed `StructuredTool`s),
  `portable_agent_tools()` (Spotify plugin tools), `build_agent()` /
  `build_async_agent()` using `create_react_agent(model, tools, checkpointer,
  prompt=vellum_prompt)`, and `LazyAgent` caching per model/reasoning-mode.
- The deferrable surface in Vellum is small and well-defined: **`plugin_mcp`**
  (single dispatcher for plugin MCP connectors; read-only annotated tools run
  automatically, mutating tools require confirmation) plus **Spotify portable
  tools** (plugin-registered, via `as_langchain_tool`). Everything else in
  `core_tools()` is a core Hermes-style tool and must stay eager.
- `vellum_prompt(state, config)` is a callable prompt that returns the full
  message list (SystemMessage + state messages) — it must keep being used as
  the model-node prompt.
- `backend/agent/api.py` streams LangGraph events (`on_tool_start` /
  `on_tool_end`) into activity items; `_activity_for` + `_ACTIVITY_LABELS`
  produce labels. A bridge `tool_call` must be **unwrapped** to the inner tool
  name so labels, `_pending_tool_calls` repair, and memory tool attribution
  keep working.
- Tests: `backend/tests/test_openrouter.py` patches `react_agent.create_react_agent`
  in 3 wiring tests — the seam moves to `_build_agent_runtime` instead.
- Settings UI: a tabs system (`SECTIONS` array + `{tab === 'Petdex' && (...)}`
  blocks) in the single HTML page; a new "Tools" tab follows the same pattern.

## 7. Design decisions for Vellum

1. **Manual StateGraph replaces `create_react_agent`.** The prebuilt helper
   binds every tool to the model — impossible to hide defs. Build an equivalent
   graph: `model` node (bound model + `vellum_prompt`) → `tools_condition` →
   `ToolNode` (all real tools + the 3 bridge tools as executable `StructuredTool`s).
2. **One new module** `backend/agent/tools/tool_search.py` holds all pure logic
   (config, classification, token estimate, BM25, catalog, assembly, bridge
   builders). `graph/agent.py` imports it; no langgraph dependency in the module.
3. **Deferral set**: `{"plugin_mcp"} | {t.name for t in portable_agent_tools()}`,
   computed at build time. Catalog entries for deferred tools also tag their
   source (`mcp` / `plugin` / `other`).
4. **Bridge `tool_call` dispatches to the registry wrapper** (the same
   `StructuredTool`s ToolNode would have used), so permission checks and
   `confirm=True` flows are preserved; the ToolMessage returns under the bridge
   call id.
5. **UI**: a "Tools" settings tab showing live assembly status (visible vs
   deferred counts, tier, listing form, budget) and a searchable full catalog
   (scope=all for the user, scope=deferred for the model bridge). A mode
   toggle (auto/on/off) persists to a runtime config JSON and invalidates the
   agent cache.
6. **Context length** comes from `TOOL_SEARCH_CONTEXT_LENGTH` (0 → use a
   128k default; the provider registry exposes per-model context at runtime in
   Hermes, but Vellum's routing layer doesn't need that dependency).

## 8. Implementable takeaways for Vellum

- Bridge tools `tool_search` / `tool_describe` / `tool_call` with the same
  contracts; core tools never defer.
- BM25 catalog keyed on name words + description + top-level param names;
  schema bodies excluded; stateless rebuild per assembly.
- Listing budget = `min(5% of context, listing_max_tokens)`; degrade
  full → names → none.
- Activity unwrap for `tool_call` so the UI shows the real tool, not the bridge.
- Settings: `TOOL_SEARCH_ENABLED` (auto default), `TOOL_SEARCH_THRESHOLD_RATIO`,
  `TOOL_SEARCH_LISTING_MAX_TOKENS`, `TOOL_SEARCH_CONTEXT_LENGTH`; runtime JSON
  override persisted under `data/tool_search.config.json`, `agent.invalidate()`.
- Tests: unit tests for assembly/BM25/bridge + wiring tests on the new seam +
  a frontend test asserting the Tools tab exists + a Playwright QA harness.
