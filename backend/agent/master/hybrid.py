from __future__ import annotations

import json
import logging
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from agent.agents.base import SpecialistResponse
from agent.agents.context import AgentExecutionContext


logger = logging.getLogger(__name__)


class HybridExecutor:
    def __init__(self, llm_factory: Callable[[str | None], Any]) -> None:
        self.llm_factory = llm_factory

    def refine(self, context: AgentExecutionContext, acquisition: SpecialistResponse) -> SpecialistResponse:
        if acquisition.action_request or acquisition.status in {"blocked", "error"}:
            return acquisition
        try:
            model = self.llm_factory(context.profile.model)
            prompt = context.prompt_stack.render() or f"You are {context.profile.id}, an independent Vellum specialist."
            skills = "\n\n".join(skill.instructions for skill in context.skills)
            payload = json.dumps(acquisition.model_dump(mode="json"), ensure_ascii=False)
            output = model.invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(
                        content=f"Goal:\n{context.goal}\n\nActivated skills:\n{skills or 'None'}\n\nAcquisition result:\n{payload}\n\nReturn the specialist assessment only."
                    ),
                ]
            )
            summary = str(getattr(output, "content", output) or "").strip()
            if not summary:
                raise RuntimeError("empty hybrid response")
            return acquisition.model_copy(update={"summary": summary})
        except Exception as exc:
            logger.warning("Hybrid refinement failed for %s: %s", context.profile.id, exc.__class__.__name__)
            note = f"hybrid fallback: {exc.__class__.__name__}."
            return acquisition.model_copy(update={"analysis": f"{acquisition.analysis}\n{note}".strip()})
