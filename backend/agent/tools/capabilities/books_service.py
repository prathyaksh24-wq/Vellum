from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from agent.knowledge.models import ContextPackRequest
from agent.profiles import get_active_profile_policy
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


class BooksCapabilityService:
    def __init__(
        self,
        *,
        knowledge_core_provider: Callable[[], Any] | None = None,
        skill_registry_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._knowledge_core_provider = knowledge_core_provider or _knowledge_core
        self._skill_registry_provider = skill_registry_provider or _skill_registry

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        allowed_agents = frozenset({"BooksAgent"})
        registry.register(
            CapabilityRecord(
                name="books.knowledge_query",
                namespace="books",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Searched installed Book evidence",
                adapter=self.query_knowledge,
            )
        )
        registry.register(
            CapabilityRecord(
                name="books.skill_lookup",
                namespace="books",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Matched Hermes Book skills",
                adapter=self.lookup_skills,
            )
        )
        return registry

    def query_knowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        if not query:
            return {"action": "books.knowledge_query", "evidence": [], "policy": {}}
        token_budget = max(256, min(int(payload.get("token_budget") or 2400), 8000))
        pack = self._knowledge_core_provider().create_context_pack(
            ContextPackRequest(
                query=query,
                purpose="specialist",
                destination="external",
                token_budget=token_budget,
                source_kinds=["book", "book_document", "book_page", "book_skill"],
                include_raw_content=False,
                citations_required=True,
            )
        )
        return {
            "action": "books.knowledge_query",
            "context_pack_id": str(pack.get("id") or ""),
            "evidence": list(pack.get("evidence") or []),
            "policy": dict(pack.get("policy") or {}),
        }

    def lookup_skills(self, payload: dict[str, Any]) -> dict[str, Any]:
        query_terms = _terms(str(payload.get("query") or ""))
        policy = get_active_profile_policy()
        allowed_skills = policy.allowed_skills if policy is not None else frozenset()
        matches: list[dict[str, Any]] = []
        for package in self._skill_registry_provider().list_packages():
            metadata = package.metadata
            extensions = metadata.metadata
            if extensions.vellum.route_to_agent != "BooksAgent":
                continue
            if extensions.hermes.category != "books" or metadata.name not in allowed_skills:
                continue
            searchable = " ".join(
                [metadata.name, metadata.description, *extensions.hermes.tags]
            )
            if query_terms and not query_terms.intersection(_terms(searchable)):
                continue
            matches.append(
                {
                    "name": metadata.name,
                    "description": metadata.description,
                    "version": metadata.version or "",
                    "category": extensions.hermes.category,
                    "tags": list(extensions.hermes.tags),
                }
            )
        return {"action": "books.skill_lookup", "skills": matches[:8]}


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", value.casefold()) if len(term) > 2}


def _knowledge_core():
    from agent.knowledge.runtime import get_knowledge_core

    return get_knowledge_core()


def _skill_registry():
    from agent.skills.runtime import get_skill_registry

    return get_skill_registry()
