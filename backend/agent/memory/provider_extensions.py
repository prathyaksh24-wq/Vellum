"""Optional external memory provider extensions for Vellum.

These providers extend the local Memory Orchestrator. They never replace the
core SQLite/FTS5/Chroma/Honcho/Obsidian stack.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from agent.config import Settings


_HEALTH_TTL_SECONDS = 30.0


def _is_local_url(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    return host in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def _embedded_engine_url() -> str:
    """URL of Vellum's own Hindsight engine when it is running; never starts it."""
    try:
        from agent.memory.engines.runtime import get_engine_supervisor
    except Exception:  # noqa: BLE001
        return ""
    if not get_engine_supervisor.cache_info().currsize:
        return ""
    return get_engine_supervisor().url("hindsight")


def _delete_hindsight_document(client: Any, bank_id: str, doc_id: str) -> None:
    """Delete one document; works with hindsight-client 0.10 and 1.x.

    Neither version has a sync delete-document wrapper, so this drives the
    generated async Documents API with the client's own loop runner, which
    lives in ``hindsight_client.hindsight_client`` (not the package root).
    """
    from hindsight_client.hindsight_client import _run_async  # type: ignore[attr-defined]

    documents = getattr(client, "documents", None)  # 1.x exposes the API object
    if documents is None:
        from hindsight_client_api import DocumentsApi

        documents = DocumentsApi(client._api_client)
    _run_async(documents.delete_document(bank_id=bank_id, document_id=doc_id))


def _hindsight_items(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        raw_items = result.get("results") or result.get("memories") or result.get("observations") or []
    else:
        raw_items = getattr(result, "results", None) or getattr(result, "memories", None) or []
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            get = item.get
        else:
            def get(key: str, _item: Any = item) -> Any:
                return getattr(_item, key, None)
        text = get("text") or get("content") or get("memory") or get("observation")
        if not text:
            continue
        items.append({
            "text": str(text).strip(),
            "type": str(get("type") or get("fact_type") or ""),
            "document_id": str(get("document_id") or ""),
        })
    return items


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
    def __init__(self, client: Any | None = None, *, settings: Settings | None = None) -> None:
        super().__init__(
            id="hindsight",
            name="Hindsight",
            provider_type="knowledge_graph",
            env_key="HINDSIGHT_API_KEY",
            capabilities=["memory.prefetch", "memory.sync_turn", "memory.reflect", "memory.recall"],
            notes="Set HINDSIGHT_API_KEY and add hindsight to MEMORY_EXTENSION_PROVIDERS.",
        )
        self.client = client
        self._injected_client = client is not None
        self._client_url = ""
        self._local = threading.local()
        self.settings = settings
        self._healthy = False
        self._health_checked_at = -_HEALTH_TTL_SECONDS
        self.bank_id = settings.hindsight_bank_id if settings else os.environ.get("HINDSIGHT_BANK_ID", "vellum")
        self.budget = settings.hindsight_budget if settings else os.environ.get("HINDSIGHT_BUDGET", "mid")

    def is_enabled(self) -> bool:
        if _embedded_engine_url():
            return True
        if self.settings is None:
            return super().is_enabled()
        return self.settings.hindsight_memory_enabled or "hindsight" in {
            name.strip().casefold() for name in self.settings.memory_extension_providers.split(",")
        }

    def is_configured(self) -> bool:
        if _is_local_url(self.base_url):
            return True
        if self.settings is None:
            return super().is_configured()
        return bool(self.settings.hindsight_api_key.get_secret_value().strip())

    @property
    def base_url(self) -> str:
        """The embedded engine when Vellum runs one; otherwise the configured URL."""
        embedded = _embedded_engine_url()
        if embedded:
            return embedded
        return (self.settings.hindsight_api_url if self.settings else
                os.environ.get("HINDSIGHT_API_URL", "https://api.hindsight.vectorize.io")).rstrip("/")

    def health(self) -> bool:
        """True only when the server answered recently, not merely when configured."""
        if self._injected_client:
            return True
        if self._client_url and self._client_url != self.base_url:
            self._health_checked_at = -_HEALTH_TTL_SECONDS  # engine moved: re-check now
        now = time.monotonic()
        if now - self._health_checked_at < _HEALTH_TTL_SECONDS:
            return self._healthy
        self._health_checked_at = now
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=1.5) as response:  # noqa: S310
                self._healthy = 200 <= int(response.status) < 300
        except Exception:
            self._healthy = False
        return self._healthy

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        items = self.recall_items(query)
        if not items:
            return ""
        return "## Hindsight Memory\n" + "\n".join(f"- {item['text']}" for item in items[:8])

    def recall_items(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        client = self._client()
        if client is None or not query.strip() or not self.health():
            return []
        result = client.recall(self.bank_id, query, budget=self.budget)
        return _hindsight_items(result)[:limit]

    def reflect(self, query: str, *, context: str | None = None) -> str:
        client = self._client()
        if client is None or not query.strip() or not self.health() or not hasattr(client, "reflect"):
            return ""
        result = client.reflect(self.bank_id, query, budget="low", context=context)
        text = result.get("text") if isinstance(result, dict) else getattr(result, "text", "")
        return str(text or "").strip()

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Retain a conversation turn. Returns the provider document id."""
        client = self._client()
        if client is None or not self.health():
            return None
        content = f"User: {user_content.strip()}\nAssistant: {assistant_content.strip()}".strip()
        if not content:
            return None
        next_metadata = {
            key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for key, value in {"session_id": session_id, **(metadata or {})}.items()
        }
        doc_id = f"vellum-turn-{uuid.uuid4().hex}"
        if hasattr(client, "retain"):
            client.retain(self.bank_id, content, metadata=next_metadata, document_id=doc_id,
                          tags=["vellum:turn"], retain_async=True)
        elif hasattr(client, "add"):
            client.add(self.bank_id, content, metadata=next_metadata)
        return doc_id

    def retain_memory(self, memory: dict[str, Any]) -> str:
        """Upsert one durable Vellum memory as its own Hindsight document."""
        client = self._client()
        if client is None or not self.health():
            raise RuntimeError("Hindsight is unreachable")
        doc_id = f"vellum-memory-{int(memory['id'])}"
        client.retain(
            self.bank_id,
            str(memory.get("text") or ""),
            context=f"{memory.get('origin') or 'inferred'} {memory.get('kind') or 'fact'} about the user",
            document_id=doc_id,
            metadata={"memory_id": str(memory["id"]), "kind": str(memory.get("kind") or ""),
                      "origin": str(memory.get("origin") or "")},
            tags=["vellum:memory", f"kind:{memory.get('kind') or 'fact'}"],
        )
        return doc_id

    def forget_document(self, doc_id: str) -> None:
        client = self._client()
        if client is None or not self.health():
            raise RuntimeError("Hindsight is unreachable")
        if hasattr(client, "forget_document"):  # test doubles
            client.forget_document(self.bank_id, doc_id)
            return
        _delete_hindsight_document(client, self.bank_id, doc_id)

    def shutdown(self) -> None:
        # Close this thread's client; other threads' clients belong to their own
        # event loops and are released with them.
        client = self.client if self._injected_client else getattr(self._local, "client", None)
        self.client = None
        self._local = threading.local()
        try:
            _close_client(client)
        except Exception:  # noqa: BLE001 - shutting down
            pass

    def _client(self) -> Any | None:
        """One Hindsight client per thread.

        The client's HTTP session belongs to the event loop of the thread that
        first used it. Memory sync runs on whichever pool thread is free, and
        reusing another thread's client failed every call with "Timeout context
        manager should be used inside a task".
        """
        if self._injected_client:
            return self.client
        local = self._local
        base_url = self.base_url
        if getattr(local, "client", None) is not None and getattr(local, "url", "") == base_url:
            return local.client
        if getattr(local, "client", None) is not None:  # the embedded engine restarted on a new port
            _close_client(local.client)
            local.client = None
        try:
            from hindsight_client import Hindsight
        except Exception:
            return None
        kwargs: dict[str, Any] = {"base_url": base_url, "timeout": 30.0}
        api_key = (self.settings.hindsight_api_key.get_secret_value() if self.settings else os.environ.get("HINDSIGHT_API_KEY", "")).strip()
        if api_key:
            kwargs["api_key"] = api_key
        try:
            local.client, local.url = Hindsight(**kwargs), base_url
        except Exception:
            local.client = None
        self.client, self._client_url = local.client, base_url
        return local.client

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

    def get(self, provider_id: str) -> MemoryProviderExtension | None:
        for provider in self.providers:
            if provider.id == provider_id and provider.is_enabled() and provider.is_configured():
                return provider
        return None

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
                doc_id = provider.sync_turn(user_content, assistant_content, session_id=session_id, metadata=metadata)
                results.append({"provider": provider.id, "status": "synced", "doc_id": str(doc_id or "")})
            except Exception as exc:
                results.append({"provider": provider.id, "status": "error", "error": str(exc)[:240]})
        return results

    def shutdown(self) -> None:
        for provider in self.providers:
            try:
                provider.shutdown()
            except Exception:
                continue


def build_default_memory_provider_extensions(*, settings: Settings | None = None) -> MemoryProviderExtensionManager:
    return MemoryProviderExtensionManager(
        [
            HindsightProviderExtension(settings=settings),
            SupermemoryProviderExtension(),
            HolographicProviderExtension(),
        ]
    )


def _status_for(provider: MemoryProviderExtension) -> dict[str, Any]:
    enabled = provider.is_enabled()
    configured = provider.is_configured()
    status = "ready" if enabled and configured else "not_configured" if enabled else "disabled"
    health = getattr(provider, "health", None)
    if status == "ready" and callable(health) and not health():
        status = "unreachable"
    return {
        "id": provider.id,
        "name": provider.name,
        "type": provider.provider_type,
        "optional": provider.optional,
        "enabled": enabled,
        "configured": configured,
        "status": status,
        "capabilities": list(provider.capabilities),
        "notes": "" if status == "ready" else (
            "Configured but not answering. Start it with: docker compose up -d hindsight"
            if status == "unreachable" else provider.setup_notes()
        ),
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
