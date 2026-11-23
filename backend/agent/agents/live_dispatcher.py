from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
import re
from uuid import uuid4
from typing import Any

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
    """Handle the user's yes or no to a specialist's pending action. Every other
    message goes to the main model, which delegates through delegate_to_agent."""

    def __init__(
        self,
        agent_catalog: AgentCatalog | None = None,
        state_store: MasterThreadStateStore | None = None,
        skill_route_resolver: SkillRouteResolver | None = None,
        delegation_runtime: DelegationRuntime | None = None,
    ) -> None:
        runtime_catalog = getattr(delegation_runtime, "agent_catalog", None)
        if agent_catalog is not None and runtime_catalog is not None and agent_catalog is not runtime_catalog:
            raise ValueError("agent_catalog and delegation_runtime must use the same AgentCatalog")
        if delegation_runtime is None and agent_catalog is None:
            delegation_runtime = get_delegation_runtime()
            runtime_catalog = delegation_runtime.agent_catalog
        self.agent_catalog = agent_catalog or runtime_catalog or AgentCatalog.default()
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
        from agent.conversations.recall import is_conversation_recall
        if is_conversation_recall(message):
            # Main conversation recall owns this evidence, including when the
            # noun in the question names a previously selected specialist.
            return None
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
        # No pre-model routing, as in DeepSeek Harness: the main model decides
        # which specialist, if any, handles a request through delegate_to_agent.
        # The only route left is the explicit one above: the user's yes or no to a
        # specialist's pending action. A thread is never pinned to a specialist,
        # so an earlier specialist turn cannot capture unrelated later messages.
        if active_agent != "VellumAgent":
            self.state_store.set_active_agent(thread_id, "VellumAgent")
            self.state_store.clear_pending_reroute(thread_id)
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
        uses_kworb = any(event.get("name") == "music_kworb" for event in response.activity_events)
        if uses_kworb:
            tools.append("music_kworb")
        if any(source.kind == "web" and not source.path_or_url.startswith("https://kworb.net/spotify/") for source in response.sources) and not uses_agent_reach and not uses_kworb:
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

    def _source_record(self, source) -> dict[str, Any]:
        domain = self._domain(source.path_or_url) if source.kind == "web" else source.kind
        return {
            "url": source.path_or_url,
            "title": source.title,
            "snippet": str(getattr(source, "snippet", "") or ""),
            "domain": domain,
            "fetched_at": source.captured_at,
            "id": getattr(source, 'id', ''),
            "source_type": source.kind,
            "claims": [claim.model_dump(mode="json") for claim in getattr(source, 'claims', [])],
            **({"evidence":source.evidence.model_dump(mode="json")} if getattr(source, 'evidence', None) is not None else {}),
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
