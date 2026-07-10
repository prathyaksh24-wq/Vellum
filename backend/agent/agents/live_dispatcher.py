from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import re

from agent.agents.base import SpecialistAgent, SpecialistResponse
from agent.agents.skill_router import SkillRouteResolver
from agent.agents.sports import SportsAgent
from agent.master.registry import PupilRegistry
from agent.master.runtime import DelegationRunResult, DelegationRuntime
from agent.master.state import MasterThreadStateStore
from agent.profiles import ProfileRegistry


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
    """Parent-owned live delegation layer.

    This is the first concrete Master/Pupil runtime slice: Vellum owns routing
    and final response shape; SportsAgent is a specialist that returns a
    structured response.
    """

    def __init__(
        self,
        vault_root: Path,
        sports_agent: SportsAgent | None = None,
        registry: PupilRegistry | None = None,
        state_store: MasterThreadStateStore | None = None,
        skill_route_resolver: SkillRouteResolver | None = None,
        delegation_runtime: DelegationRuntime | None = None,
        profile_registry: ProfileRegistry | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        if registry is not None:
            self.registry = registry
        elif sports_agent is not None:
            default_registry = PupilRegistry.default(vault_root=self.vault_root)
            self.registry = PupilRegistry(
                {
                    "XAgent": default_registry.get("XAgent"),
                    "YoutubeAgent": default_registry.get("YoutubeAgent"),
                    "MemoryAgent": default_registry.get("MemoryAgent"),
                    sports_agent.name: sports_agent,
                }
            )
        else:
            self.registry = PupilRegistry.default(vault_root=self.vault_root)
        self.state_store = state_store or MasterThreadStateStore()
        self.skill_route_resolver = skill_route_resolver or SkillRouteResolver()
        self.delegation_runtime = delegation_runtime
        self.profile_registry = profile_registry or getattr(delegation_runtime, "profile_registry", ProfileRegistry())

    def maybe_handle(self, message: str, thread_id: str) -> LiveAgentResult | None:
        message = self._clean_surface_prefix(message)
        state = self.state_store.get(thread_id)
        active_agent = state.active_agent
        pending_action = self.state_store.get_pending_action(thread_id)
        if pending_action is not None:
            if self._is_confirmation(message):
                agent_name = str(pending_action.get("agent") or "XAgent")
                try:
                    agent = self.registry.get(agent_name)
                    execute = getattr(agent, "execute_action_request")
                    response = execute(pending_action)
                    self.state_store.clear_pending_action(thread_id)
                    return self._result_from_response(response, route_source="pending_action")
                except Exception:
                    logger.exception("Pending action for %s failed.", agent_name)
                    self.state_store.clear_pending_action(thread_id)
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
        matched_pupil = None
        profile_only_id = ""
        route_source = "deterministic"
        try:
            skill_route = self.skill_route_resolver.resolve(message)
        except Exception:
            logger.exception("Skill route resolution failed.")
            skill_route = None
        if skill_route is not None:
            matched_pupil = self.registry.try_get(skill_route.agent_name)
            if matched_pupil is not None:
                route_source = "skill"
            else:
                profile = self.profile_registry.try_get(skill_route.agent_name)
                if profile is not None and profile.executor == "llm" and self.delegation_runtime is not None:
                    profile_only_id = profile.id
                    route_source = "skill"
                else:
                    logger.warning("Ignoring skill route %s to unknown pupil %s.", skill_route.skill_id, skill_route.agent_name)
        if matched_pupil is None and not profile_only_id:
            matched_pupil = self.registry.match(message)

        if matched_pupil is not None or profile_only_id:
            agent_name = matched_pupil.name if matched_pupil is not None else profile_only_id
            if active_agent != agent_name:
                self.state_store.set_active_agent(thread_id, agent_name)
                self.state_store.clear_pending_reroute(thread_id)
                self._record_handoff(
                    message=message,
                    thread_id=thread_id,
                    agent_name=agent_name,
                    reason=(
                        f"routing skill selected {agent_name}"
                        if route_source == "skill"
                        else f"{agent_name} intent detected"
                    ),
                )
            try:
                run = None
                if self.delegation_runtime is None:
                    if matched_pupil is None:
                        raise RuntimeError(f"{agent_name} requires the delegation runtime")
                    response = matched_pupil.answer(message)
                else:
                    run = self.delegation_runtime.delegate(
                        profile_id=agent_name,
                        pupil=matched_pupil,
                        goal=message,
                        parent_thread_id=thread_id,
                    )
                    response = run.response
                result = self._result_from_response(response, run=run, route_source=route_source)
                response_action = response.action_request
                if response_action:
                    self.state_store.set_pending_action(thread_id, {"agent": agent_name, **response_action})
                return result
            except Exception:
                logger.exception("Pupil %s failed while answering.", agent_name)
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

    def _record_handoff(self, *, message: str, thread_id: str, agent_name: str, reason: str) -> None:
        folder = self.vault_root / "Agent" / "Queries"
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        slug = re.sub(r"[^A-Za-z0-9]+", "-", message).strip("-").lower()[:60] or "pupil-query"
        path = folder / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slug}.md"
        content = (
            "---\n"
            f"created: \"{now}\"\n"
            f"thread_id: \"{thread_id}\"\n"
            f"routed_to: {agent_name}\n"
            f"reason: \"{reason}\"\n"
            "---\n\n"
            "## Query\n"
            f"{message}\n"
        )
        path.write_text(content, encoding="utf-8", newline="\n")

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
