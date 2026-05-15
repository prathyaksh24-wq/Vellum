"""Privacy-gated cloud escalation tool for difficult Vellum tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from agent.config import get_settings
from agent.mcp.obsidian_tools import run_tool as obsidian_run

PRIVACY_PUBLIC = "public"
PRIVACY_PRIVATE = "private"
PRIVACY_SECRET = "secret"
PRIVACY_DESTRUCTIVE = "destructive"

PRIVATE_PATTERNS = (
    "Agent/Memories",
    "Agent/Queries",
    "Agent/Responses",
    "X/",
    "Youtube/",
    "Sports/",
    "Vault/",
    "Obsidian",
    "personal",
    "private",
)

SECRET_PATTERNS = (
    ".env",
    "api_key",
    "api key",
    "password",
    "passwd",
    "secret",
    "credential",
    "bearer ",
    "sk-",
    "ghp_",
    "token=",
)

DESTRUCTIVE_PATTERNS = (
    "delete repo",
    "delete repository",
    "permanently delete",
    "purchase",
    "buy now",
    "send message",
    "bank",
    "password manager",
)


@dataclass(frozen=True)
class EscalationDecision:
    privacy_class: str
    allowed: bool
    reason: str


def classify_escalation_request(task: str, context: str = "", approval: bool = False) -> EscalationDecision:
    text = f"{task}\n{context}".casefold()
    if any(pattern.casefold() in text for pattern in SECRET_PATTERNS):
        return EscalationDecision(
            PRIVACY_SECRET,
            False,
            "Escalation blocked because the request appears to contain secrets.",
        )
    if any(pattern.casefold() in text for pattern in DESTRUCTIVE_PATTERNS):
        return EscalationDecision(
            PRIVACY_DESTRUCTIVE,
            approval,
            "Destructive or account-impacting escalation requires approval.",
        )
    if any(pattern.casefold() in text for pattern in PRIVATE_PATTERNS):
        if approval:
            return EscalationDecision(PRIVACY_PRIVATE, True, "Private escalation approved by user.")
        return EscalationDecision(
            PRIVACY_PRIVATE,
            False,
            "Private vault or personal context requires approval before cloud escalation.",
        )
    return EscalationDecision(PRIVACY_PUBLIC, True, "Public/code/docs escalation is allowed.")


def parse_cloud_response(text: str) -> dict[str, str]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {
                "answer": str(parsed.get("answer") or text),
                "what_gemma_missed": str(parsed.get("what_gemma_missed") or ""),
                "workflow_used": str(parsed.get("workflow_used") or ""),
                "lesson_for_vellum": str(parsed.get("lesson_for_vellum") or parsed.get("answer") or text),
                "suggested_skill": str(parsed.get("suggested_skill") or ""),
            }
    except json.JSONDecodeError:
        pass
    return {
        "answer": text,
        "what_gemma_missed": "Cloud model returned unstructured guidance.",
        "workflow_used": "Best-effort fallback parsing was used.",
        "lesson_for_vellum": text[:1200],
        "suggested_skill": "",
    }


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return slug[:60] or "lesson"


def _lesson_path(task: str) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return f"Agent/Memories/Lessons/{today}-cloud-escalation-{_slugify(task)}.md"


def build_lesson_markdown(task: str, reason: str, privacy_class: str, model: str, parsed: dict[str, str]) -> str:
    captured_at = datetime.now(timezone.utc).isoformat()
    return f"""---
type: cloud_escalation_lesson
captured_at: "{captured_at}"
privacy_class: {privacy_class}
model: "{model}"
tags:
  - vellum
  - cloud-escalation
  - lesson
---

# Cloud Escalation Lesson

## Task Summary

{task}

## Escalation Reason

{reason or "Gemma requested cloud assistance."}

## What Gemma Missed

{parsed["what_gemma_missed"]}

## Workflow Used

{parsed["workflow_used"]}

## Lesson For Vellum

{parsed["lesson_for_vellum"]}

## Suggested Skill

{parsed["suggested_skill"] or "No candidate skill suggested."}
"""


def _build_cloud_llm():
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        model=settings.cloud_escalation_model,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        temperature=0.2,
        max_tokens=2048,
        default_headers={"HTTP-Referer": "http://localhost", "X-Title": "Vellum"},
        extra_body={"provider": {"data_collection": "deny", "zdr": settings.zdr_only}},
    )


def _call_cloud_model(task: str, context: str, privacy_class: str) -> dict[str, str]:
    llm = _build_cloud_llm()
    result = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are Vellum's cloud escalation helper. Return only valid JSON with keys "
                    "answer, what_gemma_missed, workflow_used, lesson_for_vellum, suggested_skill."
                )
            ),
            HumanMessage(content=f"Privacy class: {privacy_class}\n\nTask:\n{task}\n\nContext:\n{context}"),
        ]
    )
    return parse_cloud_response(str(result.content))


@tool
def escalate_to_cloud(task: str, context: str = "", reason: str = "", approval: bool = False) -> str:
    """Escalate difficult public/code/docs tasks to a stronger cloud model and save a reusable lesson.

    Public/code/docs tasks may escalate automatically. Private vault, memory,
    or personal context requires approval=True. Secrets/API keys/passwords are
    blocked. Cloud advice for destructive actions must not be executed without
    confirmation.
    """

    settings = get_settings()
    if not settings.cloud_escalation_enabled:
        return "Cloud escalation is disabled by CLOUD_ESCALATION_ENABLED=false."

    decision = classify_escalation_request(task, context, approval)
    if not decision.allowed:
        return decision.reason

    parsed = _call_cloud_model(task, context, decision.privacy_class)
    lesson = build_lesson_markdown(task, reason, decision.privacy_class, settings.cloud_escalation_model, parsed)
    save_result = obsidian_run({"action": "write", "path": _lesson_path(task), "content": lesson})
    return (
        f"Cloud escalation used ({settings.cloud_escalation_model}, {decision.privacy_class}).\n\n"
        f"{parsed['answer']}\n\n"
        f"Lesson save: {save_result}"
    )
