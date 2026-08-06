"""Progressive tool search (Hermes-style) for Vellum.

Defers MCP/plugin tool schemas behind three bridge tools so the model-visible
tools array stays small: `tool_search`, `tool_describe`, `tool_call`.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field as PydanticField

from agent.config import REPO_ROOT

TOOL_SEARCH_NAME = "tool_search"
TOOL_DESCRIBE_NAME = "tool_describe"
TOOL_CALL_NAME = "tool_call"

BRIDGE_TOOL_NAMES = frozenset({TOOL_SEARCH_NAME, TOOL_DESCRIBE_NAME, TOOL_CALL_NAME})

DEFAULT_ENABLED = "auto"
DEFAULT_THRESHOLD_RATIO = 0.05
DEFAULT_LISTING_MAX_TOKENS = 4000
DEFAULT_CONTEXT_LENGTH = 128_000
DEFAULT_SEARCH_LIMIT = 8
MAX_SEARCH_LIMIT = 20

RUNTIME_CONFIG_PATH = REPO_ROOT / "data" / "tool_search.config.json"

_WORD_RE = re.compile(r"[a-z0-9]+")
_BM25_K1 = 1.5
_BM25_B = 0.75


@dataclass(frozen=True)
class ToolSearchConfig:
    enabled: str = DEFAULT_ENABLED
    threshold_ratio: float = DEFAULT_THRESHOLD_RATIO
    listing_max_tokens: int = DEFAULT_LISTING_MAX_TOKENS
    context_length: int = DEFAULT_CONTEXT_LENGTH

    @classmethod
    def from_raw(cls, raw: Any, **overrides) -> ToolSearchConfig:
        if raw is True:
            fields = {"enabled": "on"}
        elif raw is False:
            fields = {"enabled": "off"}
        elif isinstance(raw, dict):
            fields = dict(raw)
        elif raw is None:
            fields = {}
        else:
            fields = {"enabled": str(raw)}
        fields.update(overrides)
        return cls(
            enabled=str(fields.get("enabled", DEFAULT_ENABLED)).casefold(),
            threshold_ratio=float(fields.get("threshold_ratio", DEFAULT_THRESHOLD_RATIO)),
            listing_max_tokens=int(fields.get("listing_max_tokens", DEFAULT_LISTING_MAX_TOKENS)),
            context_length=int(fields.get("context_length", DEFAULT_CONTEXT_LENGTH)),
        )


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(unicodedata.normalize("NFKD", str(text)).casefold())


def load_runtime_config() -> dict[str, Any]:
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_runtime_config(overlay: dict[str, Any]) -> None:
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG_PATH.write_text(json.dumps(overlay, indent=2), encoding="utf-8")


def load_tool_search_config() -> ToolSearchConfig:
    from agent.config import get_settings

    settings = get_settings()
    overlay = load_runtime_config()
    merged: dict[str, Any] = {
        "enabled": settings.tool_search_enabled,
        "threshold_ratio": settings.tool_search_threshold_ratio,
        "listing_max_tokens": settings.tool_search_listing_max_tokens,
        "context_length": settings.tool_search_context_length or DEFAULT_CONTEXT_LENGTH,
    }
    merged.update({key: value for key, value in overlay.items() if value is not None})
    return ToolSearchConfig.from_raw(merged)


def _def_name(tool_def: dict[str, Any]) -> str:
    function = tool_def.get("function") or {}
    return str(function.get("name") or tool_def.get("name") or "")


def _def_description(tool_def: dict[str, Any]) -> str:
    function = tool_def.get("function") or {}
    return str(function.get("description") or "")


def _def_parameters(tool_def: dict[str, Any]) -> dict[str, Any]:
    function = tool_def.get("function") or {}
    parameters = function.get("parameters")
    if isinstance(parameters, dict):
        return parameters
    return {}


def estimate_tokens_from_schemas(tool_defs: list[dict[str, Any]]) -> int:
    total = 0
    for tool_def in tool_defs:
        total += max(8, len(json.dumps(tool_def, separators=(",", ":"))) // 4)
    return total


def is_deferrable_tool_name(name: str, deferred_names: set[str]) -> bool:
    return name in deferred_names and name not in BRIDGE_TOOL_NAMES


def classify_tools(
    tool_defs: list[dict[str, Any]],
    deferred_names: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    core: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for tool_def in tool_defs:
        name = _def_name(tool_def)
        if is_deferrable_tool_name(name, deferred_names):
            deferred.append(tool_def)
        else:
            core.append(tool_def)
    return core, deferred


def _entry_search_text(tool_def: dict[str, Any]) -> str:
    name = _def_name(tool_def)
    parts = [name.replace("_", " ").replace("-", " ").replace(".", " "), _def_description(tool_def)]
    parameters = _def_parameters(tool_def)
    properties = parameters.get("properties")
    if isinstance(properties, dict):
        parts.append(" ".join(str(key) for key in properties.keys()))
    return " ".join(part for part in parts if part)


def _classify_source(name: str, source_labels: dict[str, str]) -> str:
    return str(source_labels.get(name) or "other")


def _tool_display_schema(tool_def: dict[str, Any]) -> dict[str, Any]:
    parameters = _def_parameters(tool_def)
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return {}
    compact: dict[str, dict[str, Any]] = {}
    for key, value in properties.items():
        if not isinstance(value, dict):
            continue
        compact[key] = {
            "type": value.get("type"),
            "description": value.get("description", ""),
            "required": key in (parameters.get("required") or []),
        }
    return compact


@dataclass
class CatalogEntry:
    name: str
    description: str
    source: str
    source_name: str
    required: list[str]
    schema: dict[str, Any]
    tool_def: dict[str, Any] = field(repr=False)
    _words: dict[str, int] = field(default_factory=dict, repr=False)


def build_catalog(
    tool_defs: list[dict[str, Any]],
    source_labels: dict[str, str] | None = None,
) -> list[CatalogEntry]:
    source_labels = source_labels or {}
    entries: list[CatalogEntry] = []
    for tool_def in tool_defs:
        name = _def_name(tool_def)
        if not name:
            continue
        parameters = _def_parameters(tool_def)
        words = _tokenize(_entry_search_text(tool_def))
        word_counts: dict[str, int] = {}
        for word in words:
            word_counts[word] = word_counts.get(word, 0) + 1
        entries.append(
            CatalogEntry(
                name=name,
                description=_def_description(tool_def)[:300],
                source=_classify_source(name, source_labels),
                source_name=str(source_labels.get(name) or name),
                required=list(parameters.get("required") or []),
                schema=_tool_display_schema(tool_def),
                tool_def=tool_def,
                _words=word_counts,
            )
        )
    return entries


def build_deferred_catalog(
    tool_defs: list[dict[str, Any]],
    deferred_names: set[str],
    source_labels: dict[str, str] | None = None,
) -> list[CatalogEntry]:
    _, deferred = classify_tools(tool_defs, deferred_names)
    return build_catalog(deferred, source_labels)


def catalog_sources(catalog: list[CatalogEntry]) -> list[str]:
    seen: set[str] = set()
    sources: list[str] = []
    for entry in catalog:
        if entry.source not in seen:
            seen.add(entry.source)
            sources.append(entry.source)
    return sources


def search_catalog(
    catalog: list[CatalogEntry],
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[CatalogEntry]:
    query_words = _tokenize(query)
    if not query_words or not catalog:
        return []
    limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))
    avg_len = max(1.0, sum(len(entry._words) for entry in catalog) / len(catalog))
    doc_freqs: dict[str, int] = {}
    for entry in catalog:
        for word in entry._words:
            doc_freqs[word] = doc_freqs.get(word, 0) + 1
    n = len(catalog)
    scored: list[tuple[float, CatalogEntry]] = []
    for entry in catalog:
        score = 0.0
        dl = len(entry._words)
        for word in query_words:
            tf = entry._words.get(word, 0)
            if not tf:
                continue
            df = doc_freqs.get(word, 0)
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            denom = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avg_len)
            score += idf * (tf * (_BM25_K1 + 1)) / denom
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[:limit]]


def should_activate(config: ToolSearchConfig, deferred_tokens: int, threshold_tokens: int) -> bool:
    if config.enabled == "off":
        return False
    if config.enabled == "on":
        return deferred_tokens > 0
    return deferred_tokens > threshold_tokens


@dataclass
class AssemblyResult:
    tool_defs: list[dict[str, Any]]
    activated: bool
    tier: int
    deferred_count: int
    deferred_tokens: int
    threshold_tokens: int
    listing_form: str
    deferred_names: list[str]
    core_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "activated": self.activated,
            "tier": self.tier,
            "deferred_count": self.deferred_count,
            "deferred_tokens": self.deferred_tokens,
            "threshold_tokens": self.threshold_tokens,
            "listing_form": self.listing_form,
            "deferred_names": self.deferred_names,
            "core_names": self.core_names,
            "visible_count": len(self.tool_defs),
        }


def _listing_text(
    catalog: list[CatalogEntry],
    form: str,
) -> tuple[str, str]:
    if form == "full":
        payload = [
            {
                "name": entry.name,
                "description": entry.description,
                "source": entry.source,
                "required": entry.required,
            }
            for entry in catalog
        ]
        return json.dumps(payload, separators=(",", ":")), "full"
    if form == "names":
        payload = [{"name": entry.name, "source": entry.source} for entry in catalog]
        return json.dumps(payload, separators=(",", ":")), "names"
    return "", "none"


def _bridge_defs(
    listing_form: str,
    listing_text: str,
    sources: list[str],
) -> list[dict[str, Any]]:
    search_description = (
        "Search the catalog of deferred tools (MCP/plugin connectors that were "
        "hidden from the visible tools list). Returns ranked matches with name, "
        "source, and required parameters. Use this before tool_call."
    )
    if listing_form == "full":
        search_description += (
            "\n\nCatalog (searchable now):\n" + listing_text
        )
    elif listing_form == "names":
        search_description += "\n\nAvailable tools (names only):\n" + listing_text
    if sources and listing_form == "none":
        search_description += "\n\nAvailable sources: " + ", ".join(sources)

    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query for deferred tools."},
            "limit": {"type": "integer", "description": "Max results (1-20).", "default": DEFAULT_SEARCH_LIMIT},
        },
        "required": ["query"],
    }
    return [
        {
            "type": "function",
            "function": {
                "name": TOOL_SEARCH_NAME,
                "description": search_description,
                "parameters": parameters,
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_DESCRIBE_NAME,
                "description": (
                    "Return the full schema for one deferred tool by name. Use after "
                    "tool_search to learn exact parameter names before calling tool_call."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Exact deferred tool name."}
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_CALL_NAME,
                "description": (
                    "Execute a deferred tool by name with its full arguments object. "
                    "Search and describe first; mutating tools still require confirmation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Exact deferred tool name."},
                        "arguments": {
                            "type": "object",
                            "description": "Arguments for the tool, matching its schema.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
    ]


def assemble_tool_defs(
    tool_defs: list[dict[str, Any]],
    *,
    deferred_names: set[str],
    source_labels: dict[str, str] | None = None,
    config: ToolSearchConfig | None = None,
) -> AssemblyResult:
    config = config or load_tool_search_config()
    source_labels = source_labels or {}
    core, deferred = classify_tools(tool_defs, deferred_names)
    threshold_tokens = int(config.context_length * max(0.0, config.threshold_ratio))
    deferred_tokens = estimate_tokens_from_schemas(deferred)
    core_names = [_def_name(tool_def) for tool_def in core]
    deferred_names_list = [_def_name(tool_def) for tool_def in deferred]

    if not should_activate(config, deferred_tokens, threshold_tokens):
        return AssemblyResult(
            tool_defs=list(tool_defs),
            activated=False,
            tier=0,
            deferred_count=len(deferred),
            deferred_tokens=deferred_tokens,
            threshold_tokens=threshold_tokens,
            listing_form="none",
            deferred_names=deferred_names_list,
            core_names=core_names,
        )

    catalog = build_catalog(deferred, source_labels)
    budget = max(0, min(threshold_tokens, config.listing_max_tokens))
    listing_form = "none"
    listing_text = ""
    if budget > 0:
        full_text, form = _listing_text(catalog, "full")
        if estimate_tokens_from_schemas([_listing_as_def(full_text)]) <= budget:
            listing_form, listing_text = form, full_text
        else:
            names_text, form = _listing_text(catalog, "names")
            if estimate_tokens_from_schemas([_listing_as_def(names_text)]) <= budget:
                listing_form, listing_text = form, names_text

    sources = catalog_sources(catalog)
    tier = 2 if listing_form == "none" else 1
    visible = [*core, *_bridge_defs(listing_form, listing_text, sources)]
    return AssemblyResult(
        tool_defs=visible,
        activated=True,
        tier=tier,
        deferred_count=len(deferred),
        deferred_tokens=deferred_tokens,
        threshold_tokens=threshold_tokens,
        listing_form=listing_form,
        deferred_names=deferred_names_list,
        core_names=core_names,
    )


def _listing_as_def(listing_text: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": "__listing__", "description": listing_text}}


class ToolSearchArgs(BaseModel):
    query: str = PydanticField(description="Search query for deferred tools.")
    limit: int = PydanticField(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)


class ToolDescribeArgs(BaseModel):
    name: str = PydanticField(description="Exact deferred tool name.")


class ToolCallArgs(BaseModel):
    name: str = PydanticField(description="Exact deferred tool name.")
    arguments: dict[str, Any] = PydanticField(default_factory=dict)


def _bridge_result(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, default=str)


def build_tool_search_bridge(catalog: list[CatalogEntry]) -> StructuredTool:
    def run(query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> str:
        matches = search_catalog(catalog, query, limit=limit)
        if not matches:
            return _bridge_result(
                {
                    "query": query,
                    "matches": [],
                    "available_sources": catalog_sources(catalog),
                }
            )
        return _bridge_result(
            {
                "query": query,
                "matches": [
                    {
                        "name": entry.name,
                        "description": entry.description,
                        "source": entry.source,
                        "required": entry.required,
                    }
                    for entry in matches
                ],
            }
        )

    return StructuredTool.from_function(
        run,
        name=TOOL_SEARCH_NAME,
        description="Search the deferred MCP/plugin tool catalog.",
        args_schema=ToolSearchArgs,
    )


def build_tool_describe_bridge(catalog: list[CatalogEntry]) -> StructuredTool:
    by_name = {entry.name: entry for entry in catalog}

    def run(name: str) -> str:
        entry = by_name.get(name)
        if entry is None:
            return _bridge_result(
                {
                    "error": f"Unknown deferred tool '{name}'.",
                    "available_sources": catalog_sources(catalog),
                }
            )
        return _bridge_result(
            {
                "name": entry.name,
                "description": entry.description,
                "source": entry.source,
                "required": entry.required,
                "schema": entry.schema,
            }
        )

    return StructuredTool.from_function(
        run,
        name=TOOL_DESCRIBE_NAME,
        description="Describe one deferred MCP/plugin tool's schema.",
        args_schema=ToolDescribeArgs,
    )


def build_tool_call_bridge(tools_by_name: dict[str, StructuredTool]) -> StructuredTool:
    def run(name: str, arguments: dict[str, Any]) -> str:
        tool = tools_by_name.get(name)
        if tool is None:
            return _bridge_result({"error": f"Unknown tool '{name}'."})
        try:
            output = tool.invoke(arguments)
            return _bridge_result({"name": name, "output": output})
        except Exception as exc:
            return _bridge_result({"name": name, "error": f"{type(exc).__name__}: {exc}"})

    return StructuredTool.from_function(
        run,
        name=TOOL_CALL_NAME,
        description="Execute a deferred MCP/plugin tool by name.",
        args_schema=ToolCallArgs,
    )


def build_bridge_tools(
    tools: list[StructuredTool],
    catalog: list[CatalogEntry],
) -> list[StructuredTool]:
    tools_by_name = {tool.name: tool for tool in tools}
    return [
        build_tool_search_bridge(catalog),
        build_tool_describe_bridge(catalog),
        build_tool_call_bridge(tools_by_name),
    ]


def unwrap_bridge_call(name: str, tool_input: Any) -> tuple[str, Any]:
    if name == TOOL_CALL_NAME and isinstance(tool_input, dict):
        inner = str(tool_input.get("name") or "")
        if inner:
            return inner, tool_input.get("arguments") or {}
    return name, tool_input


def to_openai_defs(tools: list[StructuredTool]) -> list[dict[str, Any]]:
    return [convert_to_openai_tool(tool) for tool in tools]
