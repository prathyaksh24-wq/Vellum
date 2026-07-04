from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import logging
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from agent.agents.base import SpecialistAgent, SpecialistResponse
from agent.agents.context import AgentExecutionContext, CancellationView, invoke_specialist
from agent.llm.routing.runtime import get_routed_chat_model
from agent.memory.orchestrator import MemoryOrchestrator
from agent.memory.specialist_cache import CacheDecision
from agent.profiles import AgentHomeManager, AgentProfile, AgentSkillLoader, IdentityLoader, ProfileRegistry, profile_policy
from agent.master.hybrid import HybridExecutor


logger = logging.getLogger(__name__)
_AUDIT_LOCK = threading.Lock()


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
        audit_path: str | Path = Path("data/memory/delegation-runs.jsonl"),
    ) -> None:
        self.profile_registry = profile_registry
        self.memory_orchestrator = memory_orchestrator
        self.llm_factory = llm_factory
        self._now = now or (lambda: datetime.now(UTC))
        self.audit_path = Path(audit_path)
        self.agent_home_manager = AgentHomeManager(self.profile_registry.profile_dir.parent / "agents")

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
            return self._complete(
                profile=profile,
                response=decision.response,
                parent_thread_id=parent_thread_id,
                task_id=task_id,
                started=started,
                cache_status="hit",
                cache_reason=decision.reason,
                goal=goal,
                context=context,
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
                return self._complete(
                    profile=profile,
                    response=stale,
                    parent_thread_id=parent_thread_id,
                    task_id=task_id,
                    started=started,
                    cache_status="stale_fallback",
                    cache_reason=exc.__class__.__name__,
                    goal=goal,
                    context=context,
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

        return self._complete(
            profile=profile,
            response=response,
            parent_thread_id=parent_thread_id,
            task_id=task_id,
            started=started,
            cache_status=cache_status,
            cache_reason=decision.reason,
            goal=goal,
            context=context,
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
                return invoke_specialist(pupil, self._execution_context(profile, goal, context))
            if profile.executor == "hybrid":
                if pupil is None:
                    raise ValueError(f"{profile.id} requires a deterministic acquisition pupil")
                execution_context = self._execution_context(profile, goal, context)
                acquisition = invoke_specialist(pupil, execution_context)
                return HybridExecutor(self.llm_factory).refine(execution_context, acquisition)
            return self._execute_llm(
                profile=profile,
                goal=goal,
                context=context,
                parent_thread_id=parent_thread_id,
            )

    def _execution_context(self, profile: AgentProfile, goal: str, explicit_context: str) -> AgentExecutionContext:
        home = self.agent_home_manager.ensure(profile.id)
        identity = IdentityLoader(home).load(profile)
        skills = AgentSkillLoader(home).activate(goal).skills
        deadline = (
            self._utc_now() + timedelta(seconds=profile.delegation.timeout_seconds)
            if profile.delegation.timeout_seconds > 0
            else None
        )
        return AgentExecutionContext(
            run_id=str(uuid4()),
            task_id=str(uuid4()),
            parent_task_id=None,
            goal=goal,
            explicit_context=explicit_context,
            profile=profile,
            prompt_stack=identity,
            skills=skills,
            memory_refs=(),
            task_room_id=None,
            deadline=deadline,
            max_iterations=profile.delegation.max_iterations,
            cancellation=CancellationView(lambda: False),
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

    def _complete(
        self,
        *,
        profile: AgentProfile,
        response: SpecialistResponse,
        parent_thread_id: str,
        task_id: str | None,
        started: datetime,
        cache_status: str,
        cache_reason: str,
        goal: str,
        context: str,
    ) -> DelegationRunResult:
        result = DelegationRunResult(
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
        self._write_audit(result=result, goal=goal, context=context)
        return result

    def _write_audit(self, *, result: DelegationRunResult, goal: str, context: str) -> None:
        record = {
            "run_id": result.run_id,
            "task_id": result.task_id,
            "parent_thread_id": result.parent_thread_id,
            "profile_id": result.profile_id,
            "profile_version": result.profile_version,
            "executor": result.executor,
            "cache_status": result.cache_status,
            "cache_reason": result.cache_reason,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "status": result.response.status,
            "confidence": result.response.confidence,
            "goal_hash": _text_hash(goal),
            "context_hash": _text_hash(context),
            "source_count": len(result.response.sources),
            "tool_event_count": len(result.response.activity_events),
        }
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            with _AUDIT_LOCK:
                with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
        except OSError:
            logger.exception("Could not persist delegation audit record for %s.", result.run_id)

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


def _text_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
