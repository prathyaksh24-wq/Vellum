from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from agent.agents.base import SpecialistResponse
from agent.llm.routing.runtime import get_routed_chat_model
from agent.master.state import MasterThreadStateStore
from agent.memory.orchestrator import MemoryOrchestrator
from agent.memory.specialist_cache import CacheDecision
from agent.profiles import AgentCatalog, AgentProfile, profile_policy


logger = logging.getLogger(__name__)
_AUDIT_LOCK = threading.Lock()


@dataclass(frozen=True)
class DelegationRequest:
    agent_id: str
    task: str
    parent_thread_id: str
    user_id: str = "default"
    context: str = ""
    task_id: str | None = None
    depth: int = 0
    confirm_pending_action: bool = False

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("agent_id is required")
        if not self.task.strip():
            raise ValueError("task is required")
        if not self.parent_thread_id.strip():
            raise ValueError("parent_thread_id is required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if self.depth < 0:
            raise ValueError("depth must be non-negative")


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
        agent_catalog: AgentCatalog,
        memory_orchestrator: MemoryOrchestrator | None,
        llm_factory: Callable[[str | None], Any] = get_routed_chat_model,
        now: Callable[[], datetime] | None = None,
        audit_path: str | Path = Path("data/memory/delegation-runs.jsonl"),
        reasoning_mode: Any = None,
        pending_action_store: MasterThreadStateStore | None = None,
    ) -> None:
        self.agent_catalog = agent_catalog
        self.memory_orchestrator = memory_orchestrator
        self.llm_factory = llm_factory
        self.reasoning_mode = reasoning_mode
        self.pending_action_store = pending_action_store
        self._now = now or (lambda: datetime.now(UTC))
        self.audit_path = Path(audit_path)

    def delegate(
        self,
        request: DelegationRequest,
    ) -> DelegationRunResult:
        started = self._utc_now()
        binding = self.agent_catalog.resolve(request.agent_id)
        profile = binding.profile
        executor = binding.executor
        goal = request.task
        parent_thread_id = request.parent_thread_id
        context = request.context
        task_id = request.task_id
        action_request = None
        if request.confirm_pending_action:
            action_request = self._resolve_pending_action(
                agent_id=profile.id,
                parent_thread_id=parent_thread_id,
            )
            if action_request is None:
                response = _runtime_response(
                    profile=profile,
                    status="blocked",
                    summary="No matching pending action is available for confirmation.",
                    analysis="confirmation_authority",
                )
                return self._complete(
                    profile=profile,
                    response=response,
                    parent_thread_id=parent_thread_id,
                    task_id=task_id,
                    started=started,
                    cache_status="bypass",
                    cache_reason="confirmation_authority",
                    goal=goal,
                    context=context,
                )
        if not profile.delegation.can_receive or request.depth > profile.delegation.max_depth:
            response = _runtime_response(
                profile=profile,
                status="blocked",
                summary=f"{profile.id} cannot receive this delegated task.",
                analysis="delegation_policy",
            )
            return self._complete(
                profile=profile,
                response=response,
                parent_thread_id=parent_thread_id,
                task_id=task_id,
                started=started,
                cache_status="bypass",
                cache_reason="delegation_policy",
                goal=goal,
                context=context,
            )
        decision = (
            CacheDecision(status="bypass", reason="confirmed_action")
            if action_request is not None
            else CacheDecision(status="bypass", reason="explicit_context")
            if context.strip()
            else self._lookup(profile, goal)
        )
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
            response = self._execute(
                profile=profile,
                executor=executor,
                goal=goal,
                context=context,
                parent_thread_id=parent_thread_id,
                user_id=request.user_id,
                action_request=action_request,
            )
            _validate_response_schema(profile, response)
            if response.agent != profile.id:
                raise ValueError("delegated response agent does not match the selected profile")
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
            response = _runtime_response(
                profile=profile,
                status="error",
                summary=f"{profile.id} could not complete this delegated task.",
                analysis=exc.__class__.__name__,
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
                if self.memory_orchestrator is not None and action_request is None and not context.strip():
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

    def _resolve_pending_action(self, *, agent_id: str, parent_thread_id: str) -> dict[str, Any] | None:
        if self.pending_action_store is None:
            return None
        pending = self.pending_action_store.claim_pending_action(
            parent_thread_id,
            agent_id=agent_id,
        )
        if pending is None or str(pending.get("agent") or "") != agent_id:
            return None
        return pending

    def _lookup(self, profile: AgentProfile, goal: str) -> CacheDecision:
        if self.memory_orchestrator is None:
            return CacheDecision(status="bypass", reason="memory_orchestrator_unavailable")
        if not profile.memory.cache_first:
            return CacheDecision(status="bypass", reason="profile_cache_disabled")
        try:
            decision = self.memory_orchestrator.lookup_specialist_response(profile=profile, query=goal)
            if decision.response is not None and decision.response.agent != profile.id:
                logger.warning(
                    "Ignored cached response for %s with agent identity %s.",
                    profile.id,
                    decision.response.agent,
                )
                return CacheDecision(status="miss", reason="cached_agent_mismatch")
            return decision
        except Exception as exc:
            logger.exception("Specialist cache lookup failed for %s.", profile.id)
            return CacheDecision(status="miss", reason=f"cache_error:{exc.__class__.__name__}")

    def _execute(
        self,
        *,
        profile: AgentProfile,
        executor: Any | None,
        goal: str,
        context: str,
        parent_thread_id: str,
        user_id: str,
        action_request: dict[str, Any] | None,
    ) -> SpecialistResponse:
        with profile_policy(
            profile_id=profile.id,
            user_id=user_id,
            source_egress=profile.source_egress,
            allowed_tools=frozenset(profile.tools.allow),
            allowed_skills=frozenset(profile.skills.allow),
            require_confirmation=frozenset(profile.tools.require_confirmation),
        ):
            if profile.executor == "deterministic":
                if executor is None:
                    raise ValueError(f"{profile.id} requires a deterministic executor")
                if action_request is not None:
                    execute = getattr(executor, "execute_action_request")
                    return execute(action_request)
                return executor.answer(goal)
            if action_request is not None:
                raise ValueError("LLM profiles cannot execute confirmed actions")
            return self._execute_llm(
                profile=profile,
                goal=goal,
                context=context,
                parent_thread_id=parent_thread_id,
            )

    def _llm_for(self, model_id: str | None) -> Any:
        if self.reasoning_mode is not None and self.llm_factory is get_routed_chat_model:
            return get_routed_chat_model(model_id, reasoning_mode=self.reasoning_mode)
        return self.llm_factory(model_id)

    def _execute_llm(
        self,
        *,
        profile: AgentProfile,
        goal: str,
        context: str,
        parent_thread_id: str,
    ) -> SpecialistResponse:
        if self.memory_orchestrator is None:
            raise RuntimeError("LLM profiles require a memory orchestrator")
        packet = self.memory_orchestrator.build_memory_packet(
            thread_id=parent_thread_id,
            query=goal,
            agent_name=profile.id,
            read_scopes=profile.memory.read_scopes,
        )
        instructions = self.agent_catalog.instructions_for(profile)
        messages = [
            SystemMessage(content=instructions or f"You are {profile.id}. Return a focused specialist result."),
            HumanMessage(content=_llm_task_packet(goal=goal, context=context, memory_packet=packet)),
        ]
        model = self._llm_for(profile.model)
        output = model.invoke(
            messages,
            config={"configurable": {"thread_id": parent_thread_id}},
        )
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


def _runtime_response(
    *,
    profile: AgentProfile,
    status: str,
    summary: str,
    analysis: str,
) -> SpecialistResponse:
    structured_payload: dict[str, Any] = {}
    if profile.response_schema == "books-agent-response-v1":
        from agent.contracts.books import books_envelope_payload

        structured_payload = books_envelope_payload(
            answer=summary,
            status="failed",
            uncertainty=["The BooksAgent runtime did not return a valid answer."],
        )
    return SpecialistResponse(
        agent=profile.id,
        status=status,
        summary=summary,
        analysis=analysis,
        confidence=0.0,
        structured_payload=structured_payload,
    )


def _validate_response_schema(profile: AgentProfile, response: SpecialistResponse) -> None:
    if profile.response_schema != "books-agent-response-v1":
        return
    from agent.contracts.books import BooksAgentEnvelope

    payload = response.structured_payload.get("books_agent")
    envelope = BooksAgentEnvelope.model_validate(payload)
    if envelope.answer != response.summary:
        raise ValueError("BooksAgent envelope answer must match the specialist summary")


def _text_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
