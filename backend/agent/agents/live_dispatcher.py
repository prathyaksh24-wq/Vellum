from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace
import threading
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
import re

from agent.agents.base import SpecialistResponse, user_query_text
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
    """Route selected and natural-language turns to deterministic specialists."""

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

    def maybe_handle(self, message: str, thread_id: str, *, on_result=None) -> LiveAgentResult | None:
        message = self._clean_surface_prefix(message)
        state = self.state_store.get(thread_id)
        active_agent = state.active_agent
        pending_action = self.state_store.get_pending_action(thread_id)
        if pending_action is not None:
            retry = pending_action.get("agent")=="CalendarAgent" and self._confirmed_retry(message,pending_action)
            if pending_action.get("agent")=="CalendarAgent" and self._retry_message(message) and not retry:
                return LiveAgentResult(handled=True,agent_name="CalendarAgent",status="blocked",
                    answer="Confirm this same Calendar change before I retry it: " + str(pending_action.get("preview") or pending_action.get("payload",{}).get("summary") or "the pending action"),
                    tools=["calendar_agent"],route_source="pending_action")
            if self._is_confirmation(message, pending_action) or retry:
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
                    if not state.agent_selected:
                        self.state_store.set_active_agent(thread_id, agent_name)
                    if run.response.action_request:
                        self.state_store.set_pending_action(thread_id, {"agent": agent_name, **run.response.action_request,
                            "batch_id":pending_action.get("batch_id"), "queued_actions":pending_action.get("queued_actions", [])})
                    elif agent_name=="CalendarAgent" and run.response.status=="error":
                        # Retain the exact authorized target for an explicit retry;
                        # never authorize another event or a background retry.
                        self.state_store.set_pending_action(thread_id,{**pending_action,"confirmed_until":(datetime.now(UTC)+timedelta(minutes=5)).isoformat()})
                    elif pending_action.get("queued_actions"):
                        queued = pending_action["queued_actions"]
                        self.state_store.set_pending_action(thread_id, {**queued[0], "batch_id":pending_action.get("batch_id"), "queued_actions":queued[1:]})
                        run = replace(run, response=run.response.model_copy(update={
                            "summary":run.response.summary + "\n\nNext change awaiting confirmation: " + str(queued[0].get("preview") or "the next proposed action")}))
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
                    answer=f"Canceled the pending {str(pending_action.get('agent') or 'specialist')} action.",
                    tools=[self._tool_name(str(pending_action.get("agent") or "XAgent"))],
                )
        batch = self._independent_tasks(message, thread_id)
        if batch:
            completed = []
            lock = threading.Lock()
            def emit(run):
                part = self._result_from_response(run.response, run=run, route_source="parallel")
                with lock:
                    completed.append(part)
                    if on_result is not None:
                        on_result(part)
            runs = self.delegation_runtime.delegate_many(batch, on_complete=emit if on_result else None)
            parts = completed if on_result else [self._result_from_response(run.response, run=run, route_source="parallel") for run in runs]
            if not state.agent_selected:
                self.state_store.set_active_agent(thread_id, "VellumAgent")
                self.state_store.clear_pending_reroute(thread_id)
            return LiveAgentResult(handled=True, agent_name="VellumAgent",
                answer="\n\n".join(part.answer for part in parts),
                status="answered" if all(part.status == "answered" for part in parts) else "partial",
                tools=list(dict.fromkeys(tool for part in parts for tool in part.tools)),
                sources=[source for part in parts for source in part.sources],
                activity_events=[event for part in parts for event in part.activity_events], route_source="parallel")
        matched_binding = None
        profile_only_id = ""
        route_source = "deterministic"
        # Clear music intent delegates to its permitted owner even if the user
        # previously selected a specialist for an unrelated task. Selection itself
        # remains intact; this is a bounded delegation rather than a UI switch.
        music_binding = self.agent_catalog.try_resolve("MusicAgent")
        music_context = self.state_store.get_specialist_context(thread_id, "MusicAgent")
        contextual_music = (music_binding is not None and music_binding.executor is not None
                            and callable(getattr(music_binding.executor, "can_handle_with_context", None))
                            and music_binding.executor.can_handle_with_context(message, music_context))
        if music_binding is not None and music_binding.executor is not None and (music_binding.executor.can_handle(message) or contextual_music):
            matched_binding = music_binding
            route_source = "music_intent"
        if matched_binding is None and state.agent_selected:
            natural_binding = self.agent_catalog.match(message)
            if natural_binding is not None and natural_binding.profile.id != active_agent:
                matched_binding = natural_binding
                route_source = "natural_intent"
        if matched_binding is None and state.agent_selected and active_agent != "VellumAgent":
            selected = self.agent_catalog.try_resolve(active_agent)
            if selected is not None and selected.executor is not None:
                matched_binding = selected
                route_source = "selected"
            elif selected is not None and selected.profile.executor == "llm":
                profile_only_id = selected.profile.id
                route_source = "selected"
            else:
                self.state_store.set_active_agent(thread_id, "VellumAgent")
                self.state_store.clear_pending_reroute(thread_id)
                active_agent = "VellumAgent"
        if matched_binding is None and not profile_only_id:
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
                profile = binding.profile if binding is not None else None
                if profile is not None and profile.executor == "llm" and self.delegation_runtime is not None:
                    profile_only_id = profile.id
                    route_source = "skill"
                    break
                logger.warning("Ignoring skill route %s to unknown agent %s.", skill_route.skill_id, skill_route.agent_name)
        if matched_binding is None and not profile_only_id:
            matched_binding = self.agent_catalog.match(message)
        if (
            matched_binding is None
            and not profile_only_id
            and active_agent != "VellumAgent"
            and self._is_contextual_followup(message, active_agent)
        ):
            previous = self.agent_catalog.try_resolve(active_agent)
            if previous is not None and previous.executor is not None:
                matched_binding = previous
                route_source = "contextual"
            elif previous is not None and previous.profile.executor == "llm":
                profile_only_id = previous.profile.id
                route_source = "contextual"
        if matched_binding is not None or profile_only_id:
            agent_name = matched_binding.profile.id if matched_binding is not None else profile_only_id
            if active_agent != agent_name and not (route_source in {"music_intent", "natural_intent"} and state.agent_selected):
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
                response_action = response.action_request
                if response_action:
                    self.state_store.set_pending_action(thread_id, {"agent": agent_name, **response_action})
                return result
            except Exception:
                logger.exception("Agent %s failed while answering.", agent_name)
                return LiveAgentResult(
                    handled=True,
                    agent_name=agent_name,
                    status="error",
                    answer=(
                        f"{agent_name} could not complete this request."
                    ),
                    tools=[self._tool_name(agent_name)],
                    route_source=route_source,
                )

        if active_agent != "VellumAgent":
            self.state_store.set_active_agent(thread_id, "VellumAgent")
            self.state_store.clear_pending_reroute(thread_id)
            return None

        return None

    def _independent_tasks(self, message: str, thread_id: str) -> list[DelegationRequest]:
        from agent.app_actions.runtime import AppActionRuntime
        # Dependencies and references require main-agent planning with prior results.
        if re.search(r"\b(?:then|after|based on|using that|use (?:that|those|the result))\b", message, re.I):
            return []
        clauses = AppActionRuntime._split_mixed_clauses(message)
        if not 2 <= len(clauses) <= 8:
            return []
        requests = []
        for clause in clauses:
            clause = re.sub(r"^(?:also\s+)", "", clause, flags=re.I)
            if not re.match(r"(?:please\s+)?(?:what|which|when|who|how|can|could|show|tell|summari[sz]e|find|search|read|play|skip|pause|post|tweet|create|make|list|get)\b", clause, re.I):
                return []
            if re.search(r"\b(?:it|that|those|them|he|she|him|her)\b", clause, re.I):
                return []
            binding = self.agent_catalog.match(clause)
            if binding is None:
                return []
            requests.append(DelegationRequest(agent_id=binding.profile.id, task=clause, parent_thread_id=thread_id))
        return requests if len({request.agent_id for request in requests}) > 1 else []

    def _is_contextual_followup(self, message: str, agent_name: str) -> bool:
        """Keep a natural specialist active for a clearly dependent follow-up."""
        lowered = " ".join(str(message or "").casefold().split())
        if not lowered:
            return False
        common = (
            r"^(?:please\s+)?(?:try|check|search|look)\s+again\??$",
            r"^(?:and\s+)?what\s+about\b",
            r"^(?:can\s+you\s+)?(?:summari[sz]e|explain)\s+(?:that|those|them|it)\??$",
            r"^(?:do|send|post|book|schedule|cancel)\s+(?:it|that|them)\b",
            r"^(?:yes|no|why|how|when|where|which|who|\?+)$",
        )
        if any(re.search(pattern, lowered) for pattern in common):
            return True
        patterns = {
            "DiscordAgent": (
                r"\b(?:recent|latest|new)\s+messages?\b",
                r"\b(?:summari[sz]e|read|show|send|reply|react)\b.*\bmessages?\b",
                r"\bcatch\s+me\s+up\b",
                r"\b(?:channel|server|guild)\b",
            ),
            "CalendarAgent": (
                r"\b(?:delete|remove)\s+(?:it|that|this|the\s+(?:event|appointment|meeting))\b",
                r"\b(?:today|tomorrow|next\s+week|this\s+week)\b",
                r"\b(?:book|create|add|move|reschedule|cancel)\b",
                r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
            ),
            "SportsAgent": (
                r"\b(?:score|scores|game|match|fixture|standings?|injur(?:y|ies)|lineup|result)\b",
                r"\b(?:live|latest|next|last)\b",
            ),
            "XAgent": (
                r"\b(?:delete|remove)\s+(?:it|that|this|the\s+(?:post|tweet))\b",
                r"\b(?:post|posts|tweet|tweets|timeline|feed|bookmark|like|repost|retweet|unrepost|unretweet|reply|replies)\b",
                r"\bwhat\s+did\s+(?:he|she|they)\s+(?:say|post)\b",
            ),
            "YoutubeAgent": (r"\b(?:video|videos|channel|upload|watch)\b",),
            "BooksAgent": (r"\b(?:book|chapter|author|passage|quote)\b",),
        }
        return any(re.search(pattern, lowered) for pattern in patterns.get(agent_name, ()))

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
            r"^\s*(?:x|youtube|discord|calendar|sports|memory|mcp|research|music)\s+agent\s*:\s*",
            "",
            user_query_text(message),
            count=1,
            flags=re.I,
        ).strip()

    @staticmethod
    def _retry_message(message: str) -> bool:
        return bool(re.fullmatch(r"(?:please\s+)?(?:try|retry)(?:\s+(?:it|that))?(?:\s+again)?[.!]*",message.strip(),re.I))

    @staticmethod
    def _confirmed_retry(message: str, pending: dict) -> bool:
        try:
            valid = datetime.fromisoformat(str(pending.get("confirmed_until") or "")) > datetime.now(UTC)
        except (ValueError, TypeError):
            return False
        return valid and LiveAgentDispatcher._retry_message(message)

    @staticmethod
    def _is_confirmation(message: str, pending_action: dict | None = None) -> bool:
        action = str((pending_action or {}).get("action") or "")
        verbs = {"x.publish_post": r"(?:publish|post)\s+it", "x.reply": r"(?:send\s+the\s+reply|reply)",
                 "x.repost": r"repost\s+it", "x.unrepost": r"remove\s+the\s+repost", "x.delete": r"delete\s+it"}
        if action in verbs and re.fullmatch(r"yes[,\s]+(?:please\s+)?" + verbs[action] + r"[.!]*", message.strip(), re.I):
            return True
        if pending_action and pending_action.get("action") == "calendar.delete_event":
            if re.fullmatch(r"(?:(?:yes|confirmed?)[,\s]+)?(?:please\s+)?(?:go\s+ahead\s+and\s+)?(?:delete|remove)\s+(?:it|that|this|the\s+(?:event|appointment|meeting))(?:\s+please)?[.!]*", message.strip(), re.I):
                return True
        return bool(re.fullmatch(
            r"(?:yes|(?:yes[,\s]+)?(?:please\s+)?(?:confirm(?:ed)?|do\s+it|post\s+it|go\s+ahead(?:\s+and\s+(?:post|send|do)\s+(?:it|that))?))(?:\s+please)?[.!]*",
            message.strip(), re.I,
        ))

    @staticmethod
    def _is_rejection(message: str) -> bool:
        return bool(re.fullmatch(
            r"(?:please\s+)?(?:no|cancel(?:\s+(?:it|that|the\s+(?:post|tweet|action)))?|stop|don['’]t(?:\s+(?:post|send)(?:\s+(?:it|that))?)?|do\s+not(?:\s+(?:post|send)(?:\s+(?:it|that))?)?)(?:\s+please)?[.!]*",
            message.strip(), re.I,
        ))
