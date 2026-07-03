from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from agent.agents.base import SpecialistAgent, SpecialistResponse
from agent.llm.routing.runtime import get_routed_chat_model
from agent.memory.orchestrator import MemoryOrchestrator
from agent.memory.specialist_cache import CacheDecision
from agent.profiles import AgentProfile, ProfileRegistry, profile_policy


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DelegationRunResult:
    run_id: str
    task_id: str
    parent_thread_id: str
    profile_id: str
    profile_version: int
    executor: str
    cache_status: str
    cache_reason: str
    started_at: str
    finished_at: str
    response: SpecialistResponse


class DelegationRuntime:
    def __init__(
        self,
        *,
        profile_registry: ProfileRegistry,
        memory_orchestrator: MemoryOrchestrator,
        llm_factory: Callable[[str | None], Any] = get_routed_chat_model,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.profile_registry = profile_registry
        self.memory_orchestrator = memory_orchestrator
        self.llm_factory = llm_factory
        self._now = now or (lambda: datetime.now(UTC))

    def delegate(
        self,
        *,
        profile_id: str,
        pupil: SpecialistAgent | None,
        goal: str,
        parent_thread_id: str,
        context: str = "",
        task_id: str | None = None,
    ) -> DelegationRunResult:
        started = self._utc_now()
        profile = self.profile_registry.get(profile_id)
        decision = self._lookup(profile, goal)
        if decision.status == "hit" and decision.response is not None:
            return self._result(
                profile=profile,
                response=decision.response,
                parent_thread_id=parent_thread_id,
                task_id=task_id,
                started=started,
                cache_status="hit",
                cache_reason=decision.reason,
            )

        try:
            response = self._execute(profile=profile, pupil=pupil, goal=goal, context=context, parent_thread_id=parent_thread_id)
        except Exception as exc:
            logger.exception("Delegated profile %s failed.", profile.id)
            if decision.status == "stale" and decision.response is not None:
                stale = decision.response.model_copy(
                    update={
                        "status": "stale",
                        "confidence": min(float(decision.response.confidence), 0.6),
                        "analysis": _append_analysis(decision.response.analysis, "Live refresh failed; reused stale cached result."),
                    }
                )
                return self._result(
                    profile=profile,
                    response=stale,
                    parent_thread_id=parent_thread_id,
                    task_id=task_id,
                    started=started,
                    cache_status="stale_fallback",
                    cache_reason=exc.__class__.__name__,
                )
            response = SpecialistResponse(
                agent=profile.id,
                status="error",
                summary=f"{profile.id} could not complete this delegated task.",
                analysis=exc.__class__.__name__,
                confidence=0.0,
            )

        if response.status == "error" and decision.status == "stale" and decision.response is not None:
            response = decision.response.model_copy(
                update={
                    "status": "stale",
                    "confidence": min(float(decision.response.confidence), 0.6),
                    "analysis": _append_analysis(decision.response.analysis, "Live refresh returned an error; reused stale cached result."),
                }
            )
            cache_status = "stale_fallback"
        else:
            cache_status = decision.status
            try:
                self.memory_orchestrator.store_specialist_response(profile=profile, query=goal, response=response)
            except Exception:
                logger.exception("Could not store specialist response for %s.", profile.id)

        return self._result(
            profile=profile,
            response=response,
            parent_thread_id=parent_thread_id,
            task_id=task_id,
            started=started,
            cache_status=cache_status,
            cache_reason=decision.reason,
        )

    def _lookup(self, profile: AgentProfile, goal: str) -> CacheDecision:
        if not profile.memory.cache_first:
            return CacheDecision(status="bypass", reason="profile_cache_disabled")
        try:
            return self.memory_orchestrator.lookup_specialist_response(profile=profile, query=goal)
        except Exception as exc:
            logger.exception("Specialist cache lookup failed for %s.", profile.id)
            return CacheDecision(status="miss", reason=f"cache_error:{exc.__class__.__name__}")

    def _execute(
        self,
        *,
        profile: AgentProfile,
        pupil: SpecialistAgent | None,
        goal: str,
        context: str,
        parent_thread_id: str,
    ) -> SpecialistResponse:
        with profile_policy(profile_id=profile.id, allowed_tools=frozenset(profile.tools.allow)):
            if profile.executor == "deterministic":
                if pupil is None:
                    raise ValueError(f"{profile.id} requires a deterministic pupil")
                return pupil.answer(goal)
            return self._execute_llm(
                profile=profile,
                goal=goal,
                context=context,
                parent_thread_id=parent_thread_id,
            )

    def _execute_llm(
        self,
        *,
        profile: AgentProfile,
        goal: str,
        context: str,
        parent_thread_id: str,
    ) -> SpecialistResponse:
        packet = self.memory_orchestrator.build_memory_packet(
            thread_id=parent_thread_id,
            query=goal,
            agent_name=profile.id,
            read_scopes=profile.memory.read_scopes,
        )
        instructions = self.profile_registry.instructions_for(profile)
        messages = [
            SystemMessage(content=instructions or f"You are {profile.id}. Return a focused specialist result."),
            HumanMessage(content=_llm_task_packet(goal=goal, context=context, memory_packet=packet)),
        ]
        model = self.llm_factory(profile.model)
        output = model.invoke(messages)
        content = getattr(output, "content", output)
        if isinstance(content, list):
            content = "\n".join(str(item.get("text") or "") if isinstance(item, dict) else str(item) for item in content)
        summary = str(content or "").strip()
        if not summary:
            raise RuntimeError("LLM profile returned an empty response")
        return SpecialistResponse(agent=profile.id, status="answered", summary=summary, confidence=0.65)

    def _result(
        self,
        *,
        profile: AgentProfile,
        response: SpecialistResponse,
        parent_thread_id: str,
        task_id: str | None,
        started: datetime,
        cache_status: str,
        cache_reason: str,
    ) -> DelegationRunResult:
        return DelegationRunResult(
            run_id=str(uuid4()),
            task_id=task_id or str(uuid4()),
            parent_thread_id=parent_thread_id,
            profile_id=profile.id,
            profile_version=profile.version,
            executor=profile.executor,
            cache_status=cache_status,
            cache_reason=cache_reason,
            started_at=started.isoformat(),
            finished_at=self._utc_now().isoformat(),
            response=response,
        )

    def _utc_now(self) -> datetime:
        value = self._now()
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _llm_task_packet(*, goal: str, context: str, memory_packet: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            f"Goal:\n{goal.strip()}",
            f"Explicit context:\n{context.strip() or 'None supplied.'}",
            "Approved profile memory:\n" + json.dumps(memory_packet, ensure_ascii=False, default=str),
            "Return only the specialist result for this task.",
        ]
    )


def _append_analysis(existing: str, note: str) -> str:
    return f"{existing}\n{note}".strip()
