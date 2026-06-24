"""Optional external memory provider extensions for Vellum.

These providers extend the local Memory Orchestrator. They never replace the
core SQLite/FTS5/Chroma/Honcho/Obsidian stack.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class MemoryProviderExtension(Protocol):
    id: str
    name: str
    provider_type: str
    optional: bool
    capabilities: list[str]

    def is_enabled(self) -> bool: ...

    def is_configured(self) -> bool: ...

    def setup_notes(self) -> str: ...

    def prefetch(self, query: str, *, session_id: str = "") -> str: ...

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def shutdown(self) -> None: ...


@dataclass(slots=True)
class ConfiguredMemoryProviderExtension:
    id: str
    name: str
    provider_type: str
    env_key: str
    enable_key: str = "MEMORY_EXTENSION_PROVIDERS"
    optional: bool = True
    capabilities: list[str] = field(default_factory=list)
    notes: str = ""

    def is_enabled(self) -> bool:
        enabled = _enabled_provider_ids()
        if self.id in enabled:
            return True
        explicit_flag = os.environ.get(f"{self.id.upper()}_MEMORY_ENABLED", "")
        return explicit_flag.strip().lower() in {"1", "true", "yes", "on"}

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.env_key, "").strip())

    def setup_notes(self) -> str:
        return self.notes or f"Set {self.env_key} and add {self.id} to MEMORY_EXTENSION_PROVIDERS."

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        return ""

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    def shutdown(self) -> None:
        return None


class HindsightProviderExtension(ConfiguredMemoryProviderExtension):
    def __init__(self, client: Any | None = None) -> None:
        super().__init__(
            id="hindsight",
            name="Hindsight",
            provider_type="knowledge_graph",
            env_key="HINDSIGHT_API_KEY",
            capabilities=["memory.prefetch", "memory.sync_turn", "memory.reflect", "memory.recall"],
            notes="Set HINDSIGHT_API_KEY and add hindsight to MEMORY_EXTENSION_PROVIDERS.",
        )
        self.client = client
        self.bank_id = os.environ.get("HINDSIGHT_BANK_ID", "vellum")
        self.budget = os.environ.get("HINDSIGHT_BUDGET", "mid")

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        client = self._client()
        if client is None or not query.strip():
            return ""
        result = client.recall(self.bank_id, query, budget=self.budget)
        return _format_hindsight_recall(result)

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        client = self._client()
        if client is None:
            return
        content = f"User: {user_content.strip()}\nAssistant: {assistant_content.strip()}".strip()
        if not content:
            return
        next_metadata = {"session_id": session_id, **(metadata or {})}
        if hasattr(client, "retain"):
            client.retain(self.bank_id, content, metadata=next_metadata)
        elif hasattr(client, "add"):
            client.add(self.bank_id, content, metadata=next_metadata)

    def _client(self) -> Any | None:
        if self.client is not None:
            return self.client
        try:
            from hindsight_client import Hindsight
        except Exception:
            return None
        kwargs: dict[str, Any] = {"base_url": os.environ.get("HINDSIGHT_API_URL", "https://api.hindsight.vectorize.io")}
        api_key = os.environ.get("HINDSIGHT_API_KEY", "").strip()
        if api_key:
            kwargs["api_key"] = api_key
        try:
            self.client = Hindsight(**kwargs)
        except Exception:
            self.client = None
        return self.client

    def shutdown(self) -> None:
        _close_client(self.client)
        self.client = None


class SupermemoryProviderExtension(ConfiguredMemoryProviderExtension):
    def __init__(self, client: Any | None = None) -> None:
        super().__init__(
            id="supermemory",
            name="Supermemory",
            provider_type="managed_semantic_profile",
            env_key="SUPERMEMORY_API_KEY",
            capabilities=["memory.prefetch", "memory.sync_turn", "memory.profile", "memory.search"],
            notes="Set SUPERMEMORY_API_KEY and add supermemory to MEMORY_EXTENSION_PROVIDERS.",
        )
        self.client = client

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        client = self._client()
        if client is None or not query.strip():
            return ""
        return _format_supermemory_profile(client.profile(query))

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        client = self._client()
        if client is None or not hasattr(client, "ingest_turn"):
            return
        client.ingest_turn(session_id, user_content, assistant_content, metadata or {})

    def _client(self) -> Any | None:
        if self.client is not None:
            return self.client
        try:
            from supermemory import Supermemory
        except Exception:
            return None
        api_key = os.environ.get("SUPERMEMORY_API_KEY", "").strip()
        if not api_key:
            return None
        try:
            self.client = _SupermemorySdkAdapter(Supermemory(api_key=api_key))
        except Exception:
            self.client = None
        return self.client

    def shutdown(self) -> None:
        target = getattr(self.client, "client", self.client)
        _close_client(target)
        self.client = None


class _SupermemorySdkAdapter:
    def __init__(self, client: Any) -> None:
        self.client = client

    def profile(self, query: str) -> dict[str, Any]:
        response = self.client.profile(q=query)
        profile = getattr(response, "profile", None)
        search = getattr(response, "search_results", None) or getattr(response, "searchResults", None)
        return {
            "static": list(getattr(profile, "static", []) or []) if profile is not None else [],
            "dynamic": list(getattr(profile, "dynamic", []) or []) if profile is not None else [],
            "search_results": list(getattr(search, "results", []) or []) if search is not None else [],
        }

    def ingest_turn(self, session_id: str, user_content: str, assistant_content: str, metadata: dict[str, Any]) -> None:
        content = f"[role:user]{user_content}[/role]\n[role:assistant]{assistant_content}[/role]"
        self.client.documents.add(content=content, metadata={"session_id": session_id, **metadata})


class HolographicProviderExtension(ConfiguredMemoryProviderExtension):
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("HOLOGRAPHIC_MEMORY_DB", "data/memory/holographic.db"))
        super().__init__(
            id="holographic",
            name="Holographic Memory",
            provider_type="local_structured_facts",
            env_key="HOLOGRAPHIC_MEMORY_ENABLED",
            capabilities=["memory.prefetch", "memory.mirror_write", "fact.search", "fact.feedback"],
            notes="Set HOLOGRAPHIC_MEMORY_ENABLED=true and add holographic to MEMORY_EXTENSION_PROVIDERS.",
        )

    def is_configured(self) -> bool:
        return os.environ.get("HOLOGRAPHIC_MEMORY_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        terms = _terms(query)
        if not terms:
            return ""
        self._init_db()
        with self._connect() as conn:
            rows = conn.execute("SELECT content, trust FROM facts ORDER BY updated_at DESC LIMIT 200").fetchall()
        matches: list[str] = []
        for row in rows:
            content = str(row["content"])
            if terms.intersection(_terms(content)):
                matches.append(f"- [{float(row['trust']):.1f}] {content}")
            if len(matches) >= 5:
                break
        return "## Holographic Memory\n" + "\n".join(matches) if matches else ""

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not _looks_durable_fact(user_content):
            return
        self._init_db()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO facts (content, session_id, trust, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (user_content.strip(), session_id, 0.6, _safe_json(metadata or {})),
            )

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    session_id TEXT,
                    trust REAL NOT NULL DEFAULT 0.5,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )


class MemoryProviderExtensionManager:
    def __init__(self, providers: list[MemoryProviderExtension] | None = None) -> None:
        self.providers = providers or []

    def statuses(self) -> list[dict[str, Any]]:
        return [_status_for(provider) for provider in self.providers]

    def active_provider_ids(self) -> list[str]:
        return [provider.id for provider in self.providers if provider.is_enabled() and provider.is_configured()]

    def prefetch(self, query: str, *, session_id: str = "") -> list[dict[str, str]]:
        contexts: list[dict[str, str]] = []
        for provider in self.providers:
            if not provider.is_enabled() or not provider.is_configured():
                continue
            try:
                context = provider.prefetch(query, session_id=session_id)
            except Exception as exc:
                context = ""
                contexts.append({"provider": provider.id, "context": "", "error": str(exc)[:240]})
            if context:
                contexts.append({"provider": provider.id, "context": str(context)})
        return contexts

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for provider in self.providers:
            if not provider.is_enabled() or not provider.is_configured():
                continue
            try:
                provider.sync_turn(user_content, assistant_content, session_id=session_id, metadata=metadata)
                results.append({"provider": provider.id, "status": "synced"})
            except Exception as exc:
                results.append({"provider": provider.id, "status": "error", "error": str(exc)[:240]})
        return results

    def shutdown(self) -> None:
        for provider in self.providers:
            try:
                provider.shutdown()
            except Exception:
                continue


def build_default_memory_provider_extensions() -> MemoryProviderExtensionManager:
    return MemoryProviderExtensionManager(
        [
            HindsightProviderExtension(),
            SupermemoryProviderExtension(),
            HolographicProviderExtension(),
        ]
    )


def _status_for(provider: MemoryProviderExtension) -> dict[str, Any]:
    enabled = provider.is_enabled()
    configured = provider.is_configured()
    status = "ready" if enabled and configured else "not_configured" if enabled else "disabled"
    return {
        "id": provider.id,
        "name": provider.name,
        "type": provider.provider_type,
        "optional": provider.optional,
        "enabled": enabled,
        "configured": configured,
        "status": status,
        "capabilities": list(provider.capabilities),
        "notes": "" if status == "ready" else provider.setup_notes(),
    }


def _enabled_provider_ids() -> set[str]:
    raw = os.environ.get("MEMORY_EXTENSION_PROVIDERS", "")
    return {part.strip().casefold() for part in raw.split(",") if part.strip()}


def _format_hindsight_recall(result: Any) -> str:
    items = []
    if isinstance(result, dict):
        raw_items = result.get("memories") or result.get("results") or result.get("observations") or []
    else:
        raw_items = getattr(result, "memories", None) or getattr(result, "results", None) or []
    for item in raw_items:
        if isinstance(item, dict):
            content = item.get("content") or item.get("text") or item.get("memory") or item.get("observation")
            score = item.get("score") or item.get("similarity")
        else:
            content = getattr(item, "content", "") or getattr(item, "text", "") or getattr(item, "memory", "")
            score = getattr(item, "score", None) or getattr(item, "similarity", None)
        if not content:
            continue
        prefix = ""
        if score is not None:
            try:
                prefix = f"[{round(float(score) * 100)}%] "
            except Exception:
                prefix = ""
        items.append(f"- {prefix}{str(content).strip()}")
    return "## Hindsight Memory\n" + "\n".join(items[:8]) if items else ""


def _format_supermemory_profile(profile: Any) -> str:
    if not isinstance(profile, dict):
        return ""
    sections: list[str] = []
    static = [str(item).strip() for item in profile.get("static", []) if str(item).strip()]
    dynamic = [str(item).strip() for item in profile.get("dynamic", []) if str(item).strip()]
    search_results = profile.get("search_results", []) or []
    if static:
        sections.append("## Supermemory Profile\n" + "\n".join(f"- {item}" for item in static[:6]))
    if dynamic:
        sections.append("## Supermemory Recent Context\n" + "\n".join(f"- {item}" for item in dynamic[:6]))
    memories = []
    for item in search_results:
        if isinstance(item, dict):
            memory = str(item.get("memory") or item.get("content") or "").strip()
        else:
            memory = str(getattr(item, "memory", "") or getattr(item, "content", "")).strip()
        if memory:
            memories.append(f"- {memory}")
    if memories:
        sections.append("## Supermemory Related Memories\n" + "\n".join(memories[:6]))
    return "\n\n".join(sections)


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[A-Za-z0-9]+", text.casefold()) if len(term) > 2}


def _looks_durable_fact(text: str) -> bool:
    return bool(re.search(r"\b(?:remember|prefer|use|uses|decided|project|vellum|agent|memory)\b", text, re.I))


def _safe_json(value: dict[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return "{}"


def _close_client(client: Any | None) -> None:
    if client is None:
        return
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
            return
        except Exception:
            pass
    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        try:
            import asyncio

            asyncio.run(aclose())
        except Exception:
            pass
