from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re

from agent.agents.base import SpecialistResponse
from agent.agents.skill_router import SkillRouteResolver
from agent.master.live_runtime import get_delegation_runtime
from agent.master.runtime import DelegationRequest, DelegationRunResult, DelegationRuntime
from agent.master.state import MasterThreadStateStore
from agent.profiles import AgentCatalog


logger = logging.getLogger(__name__)


@dataclass
class LiveAgentResult:
    handled: bool
    agent_name: str
    answer: str
    status: str = "answered"
    tools: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    activity_events: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    run_id: str = ""
    cache_status: str = ""
    cache_reason: str = ""
    route_source: str = "deterministic"


class LiveAgentDispatcher:
    """Compatibility adapter for deterministic routing into DelegationRuntime."""

    def __init__(
        self,
        vault_root: Path,
        agent_catalog: AgentCatalog | None = None,
        state_store: MasterThreadStateStore | None = None,
        skill_route_resolver: SkillRouteResolver | None = None,
        delegation_runtime: DelegationRuntime | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        runtime_catalog = getattr(delegation_runtime, "agent_catalog", None)
        if agent_catalog is not None and runtime_catalog is not None and agent_catalog is not runtime_catalog:
            raise ValueError("agent_catalog and delegation_runtime must use the same AgentCatalog")
        if delegation_runtime is None and agent_catalog is None:
            delegation_runtime = get_delegation_runtime()
            runtime_catalog = delegation_runtime.agent_catalog
        self.agent_catalog = agent_catalog or runtime_catalog or AgentCatalog.default(vault_root=self.vault_root)
        self.state_store = state_store or MasterThreadStateStore()
        if hasattr(delegation_runtime, "pending_action_store"):
            runtime_state_store = delegation_runtime.pending_action_store
            if runtime_state_store is None:
                delegation_runtime.pending_action_store = self.state_store
            elif runtime_state_store.sessions_db.resolve() != self.state_store.sessions_db.resolve():
                raise ValueError(
                    "delegation_runtime and dispatcher must use the same pending-action store"
                )
        self.skill_route_resolver = skill_route_resolver or SkillRouteResolver()
        self.delegation_runtime = delegation_runtime or DelegationRuntime(
            agent_catalog=self.agent_catalog,
            memory_orchestrator=None,
            audit_path=self.state_store.sessions_db.parent / "delegation-runs.jsonl",
            pending_action_store=self.state_store,
        )

    def maybe_handle(self, message: str, thread_id: str) -> LiveAgentResult | None:
        message = self._clean_surface_prefix(message)
        state = self.state_store.get(thread_id)
        active_agent = state.active_agent
        pending_action = self.state_store.get_pending_action(thread_id)
        if pending_action is not None:
            if self._is_confirmation(message):
                agent_name = str(pending_action.get("agent") or "XAgent")
                try:
                    run = self.delegation_runtime.delegate(
                        DelegationRequest(
                            agent_id=agent_name,
                            task="Execute the confirmed pending action.",
                            parent_thread_id=thread_id,
                            confirm_pending_action=True,
                        )
                    )
                    return self._result_from_response(
                        run.response,
                        run=run,
                        route_source="pending_action",
                    )
                except Exception:
                    logger.exception("Pending action for %s failed.", agent_name)
                    return LiveAgentResult(
                        handled=True,
                        agent_name=agent_name,
                        status="error",
                        answer=f"{agent_name} could not complete the confirmed action.",
                        tools=[self._tool_name(agent_name)],
                    )
            if self._is_rejection(message):
                self.state_store.clear_pending_action(thread_id)
                return LiveAgentResult(
                    handled=True,
                    agent_name=str(pending_action.get("agent") or "XAgent"),
                    status="blocked",
                    answer="Canceled the pending X action.",
                    tools=["x_agent"],
                )
        matched_binding = None
        profile_only_id = ""
        route_source = "deterministic"
        try:
            resolve_all = getattr(self.skill_route_resolver, "resolve_all", None)
            if callable(resolve_all):
                skill_routes = resolve_all(message)
            else:
                skill_route = self.skill_route_resolver.resolve(message)
                skill_routes = [skill_route] if skill_route is not None else []
        except Exception:
            logger.exception("Skill route resolution failed.")
            skill_routes = []
        for skill_route in skill_routes:
            binding = self.agent_catalog.try_resolve(skill_route.agent_name)
            if binding is not None and skill_route.skill_id not in binding.profile.skills.allow:
                logger.warning(
                    "Ignoring skill route %s because it is not allowed by %s.",
                    skill_route.skill_id,
                    binding.profile.id,
                )
                continue
            if binding is not None and binding.executor is not None:
                matched_binding = binding
                route_source = "skill"
                break
            else:
                profile = binding.profile if binding is not None else None
                if profile is not None and profile.executor == "llm" and self.delegation_runtime is not None:
                    profile_only_id = profile.id
                    route_source = "skill"
                    break
                else:
                    logger.warning("Ignoring skill route %s to unknown agent %s.", skill_route.skill_id, skill_route.agent_name)
        if matched_binding is None and not profile_only_id:
            matched_binding = self.agent_catalog.match(message)

        if matched_binding is not None or profile_only_id:
            agent_name = matched_binding.profile.id if matched_binding is not None else profile_only_id
            if active_agent != agent_name:
                self.state_store.set_active_agent(thread_id, agent_name)
                self.state_store.clear_pending_reroute(thread_id)
            try:
                run = self.delegation_runtime.delegate(
                    DelegationRequest(
                        agent_id=agent_name,
                        task=message,
                        parent_thread_id=thread_id,
                    )
                )
                response = run.response
                result = self._result_from_response(response, run=run, route_source=route_source)
                if response.status == "error":
                    self.state_store.set_active_agent(thread_id, "VellumAgent")
                    self.state_store.clear_pending_reroute(thread_id)
                response_action = response.action_request
                if response_action:
                    self.state_store.set_pending_action(thread_id, {"agent": agent_name, **response_action})
                return result
            except Exception:
                logger.exception("Agent %s failed while answering.", agent_name)
                self.state_store.set_active_agent(thread_id, "VellumAgent")
                self.state_store.clear_pending_reroute(thread_id)
                return LiveAgentResult(
                    handled=True,
                    agent_name=agent_name,
                    status="error",
                    answer=(
                        f"{agent_name} could not complete this request. "
                        "I routed control back to Vellum so the main agent can continue."
                    ),
                    tools=[self._tool_name(agent_name)],
                    route_source=route_source,
                )

        if active_agent != "VellumAgent":
            self.state_store.set_active_agent(thread_id, "VellumAgent")
            self.state_store.clear_pending_reroute(thread_id)
            return None

        return None

    def _result_from_response(
        self,
        response: SpecialistResponse,
        *,
        run: DelegationRunResult | None = None,
        route_source: str = "deterministic",
    ) -> LiveAgentResult:
        tools = [self._tool_name(response.agent)]
        uses_agent_reach = "agent-reach" in response.analysis.casefold() or any(
            str(event.get("name") or "").startswith("agent_reach_x_") for event in response.activity_events
        )
        if any(source.kind == "web" for source in response.sources) and not uses_agent_reach:
            tools.append("web_search")
        if "serpapi" in response.analysis.casefold():
            tools.append("serpapi")
        return LiveAgentResult(
            handled=True,
            agent_name=response.agent,
            answer=response.summary,
            status=response.status,
            tools=tools,
            sources=[
                self._source_record(source)
                for source in response.sources
                if source.path_or_url
            ],
            activity_events=list(response.activity_events),
            confidence=float(response.confidence),
            run_id=run.run_id if run is not None else "",
            cache_status=run.cache_status if run is not None else "",
            cache_reason=run.cache_reason if run is not None else "",
            route_source=route_source,
        )

    def _domain(self, url: str) -> str:
        match = re.match(r"https?://(?:www\.)?([^/]+)", url)
        return match.group(1) if match else ""

    def _source_record(self, source) -> dict[str, str]:
        domain = self._domain(source.path_or_url) if source.kind == "web" else source.kind
        return {
            "url": source.path_or_url,
            "title": source.title,
            "snippet": str(getattr(source, "snippet", "") or ""),
            "domain": domain,
            "fetched_at": source.captured_at,
        }

    def _tool_name(self, agent_name: str) -> str:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", agent_name).lower()
        return name[:-6] + "_agent" if name.endswith("_agent") else name

    def _clean_surface_prefix(self, message: str) -> str:
        return re.sub(
            r"^\s*(?:x|youtube|sports|memory|mcp|research)\s+agent\s*:\s*",
            "",
            message,
            count=1,
            flags=re.I,
        ).strip()

    def _is_confirmation(self, message: str) -> bool:
        lowered = message.strip().lower()
        return lowered in {"yes", "confirm", "confirmed", "do it", "post it", "yes post it", "yes, post it"} or (
            "confirm" in lowered or "post it" in lowered or "go ahead" in lowered
        )

    def _is_rejection(self, message: str) -> bool:
        lowered = message.strip().lower()
        return lowered in {"no", "cancel", "stop", "don't", "do not"}
