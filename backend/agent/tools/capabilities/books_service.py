from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from agent.contracts.books import BooksDiscoveryTask
from agent.knowledge.models import BookRetrievalRequest
from agent.profiles import get_active_profile_policy
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


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
        for name, adapter in (("books.discover", self.discover), ("books.verify_candidate", self.verify_candidate)):
            registry.register(CapabilityRecord(
                name=name, namespace="books", access=CapabilityAccess.READ,
                allowed_agents=allowed_agents, stream_label="Evaluated shadow Book Discovery",
                adapter=adapter, requires_confirmation=True,
            ))
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

    def discover(self, payload: dict[str, Any]) -> dict[str, Any]:
        from agent.knowledge.models import BookDiscoveryPolicy, BookDiscoveryRequest

        task, active = self._discovery_authority(payload, operation="discover")
        return self._knowledge_core_provider().discover_books(
            BookDiscoveryRequest(
                user_id=active.user_id, query=task.query, objective=task.objective,
                max_candidates=task.max_candidates, request_key=active.book_discovery_request_key,
            ),
            policy=BookDiscoveryPolicy(network_allowed=True, public_query_approved=True),
        )

    def verify_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        from agent.knowledge.models import BookDiscoveryPolicy, BookDiscoveryVerificationRequest

        task, active = self._discovery_authority(payload, operation="verify")
        return self._knowledge_core_provider().verify_book_discovery_candidate(
            BookDiscoveryVerificationRequest(
                user_id=active.user_id, candidate_id=task.candidate_id,
                request_key=active.book_discovery_request_key,
            ),
            policy=BookDiscoveryPolicy(network_allowed=True, public_query_approved=True, deadline_seconds=30.0),
        )

    @staticmethod
    def _discovery_authority(payload: dict[str, Any], *, operation: str):
        task = BooksDiscoveryTask.model_validate({key: value for key, value in payload.items() if key != "confirm"})
        active = get_active_profile_policy()
        if (
            active is None or active.profile_id != "BooksAgent"
            or not active.book_discovery_network or active.source_egress != "external"
            or task.operation != operation or task.capability not in active.allowed_tools
            or not active.book_discovery_request_key
            or active.book_discovery_approval != task.fingerprint()
        ):
            raise ToolPermissionError("Book Discovery requires profile-bound confirmation")
        return task, active

    def query_knowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        if not query:
            return {"action": "books.knowledge_query", "evidence": [], "policy": {}}
        policy = get_active_profile_policy()
        user_id = policy.user_id if policy is not None else "default"
        max_chunks = max(1, min(int(payload.get("max_chunks") or 6), 12))
        token_budget = max(256, min(int(payload.get("token_budget") or 2400), 8000))
        result = self._knowledge_core_provider().search_active_book_materializations(
            BookRetrievalRequest(
                user_id=user_id,
                query=query,
                destination=policy.source_egress if policy is not None else "local",
                max_chunks=max_chunks,
                token_budget=token_budget,
            )
        )
        return {
            "action": "books.knowledge_query",
            "evidence": list(result.get("evidence") or []),
            "policy": dict(result.get("policy") or {}),
        }

    def lookup_skills(self, payload: dict[str, Any]) -> dict[str, Any]:
        query_terms = _terms(str(payload.get("query") or ""))
        policy = get_active_profile_policy()
        allowed_skills = policy.allowed_skills if policy is not None else frozenset()
        matches: list[dict[str, Any]] = []
        core = self._knowledge_core_provider()
        list_active = getattr(core, "list_active_book_skills", None)
        if "book-to-skill" in allowed_skills and callable(list_active):
            matches.extend(
                list_active(
                    user_id=policy.user_id if policy is not None else "default",
                    limit=8,
                )
            )
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
        deduplicated = {str(item.get("name") or ""): item for item in matches}
        return {
            "action": "books.skill_lookup",
            "skills": list(deduplicated.values())[:8],
        }


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", value.casefold()) if len(term) > 2}


def _knowledge_core():
    from agent.knowledge.runtime import get_knowledge_core

    return get_knowledge_core()


def _skill_registry():
    from agent.skills.runtime import get_skill_registry

    return get_skill_registry()
