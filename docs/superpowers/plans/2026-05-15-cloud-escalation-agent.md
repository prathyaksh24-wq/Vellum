# Cloud Escalation Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a privacy-gated `escalate_to_cloud` tool that lets Gemma ask a stronger cloud model for help and save reusable lessons to Obsidian.

**Architecture:** Implement escalation as a normal LangGraph tool, not a router. A focused helper module classifies privacy, calls a configured cloud model, parses the response, and saves a lesson note through the existing Obsidian REST wrapper.

**Tech Stack:** Python, LangChain tools, LangChain OpenAI/OpenRouter client, existing Vellum config, existing Obsidian REST wrapper, pytest.

---

## File Structure

- Create `backend/agent/tools/cloud_escalation.py`: privacy classification, cloud call, response parsing, lesson markdown generation, Obsidian save, and LangChain `escalate_to_cloud` tool.
- Modify `backend/agent/config.py`: add `CLOUD_ESCALATION_MODEL` and `CLOUD_ESCALATION_ENABLED`.
- Modify `backend/agent/graph/agent.py`: import/register the tool and update the system prompt with escalation rules.
- Create `backend/tests/test_cloud_escalation.py`: unit tests for privacy gates, parsing, lesson markdown, blocked/private/public behavior, and mocked cloud call.
- Modify `backend/tests/test_config.py`: assert cloud escalation settings load.

---

### Task 1: Config Fields

**Files:**
- Modify: `backend/agent/config.py`
- Modify: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing config test**

Add assertions to `backend/tests/test_config.py`:

```python
assert settings.cloud_escalation_model == "google/gemini-2.5-pro"
assert settings.cloud_escalation_enabled is True
```

- [ ] **Step 2: Run the config test**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_config.py -q`

Expected: FAIL with `Settings` missing `cloud_escalation_model`.

- [ ] **Step 3: Add settings fields**

Add to `Settings` in `backend/agent/config.py` near the agent fields:

```python
cloud_escalation_model: str = Field(default="google/gemini-2.5-pro", alias="CLOUD_ESCALATION_MODEL")
cloud_escalation_enabled: bool = Field(default=True, alias="CLOUD_ESCALATION_ENABLED")
```

- [ ] **Step 4: Run the config test**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_config.py -q`

Expected: PASS.

---

### Task 2: Cloud Escalation Tool Core

**Files:**
- Create: `backend/agent/tools/cloud_escalation.py`
- Create: `backend/tests/test_cloud_escalation.py`

- [ ] **Step 1: Write privacy and parsing tests**

Create `backend/tests/test_cloud_escalation.py` with tests that call:

```python
from agent.tools import cloud_escalation


def test_public_code_task_auto_allowed():
    decision = cloud_escalation.classify_escalation_request(
        "Debug this FastAPI route",
        "Public repo code, no private notes.",
        approval=False,
    )
    assert decision.privacy_class == "public"
    assert decision.allowed is True


def test_private_vault_task_requires_approval():
    decision = cloud_escalation.classify_escalation_request(
        "Summarize my notes",
        "Agent/Memories/vellum-computer-use-gemma-orchestration.md",
        approval=False,
    )
    assert decision.privacy_class == "private"
    assert decision.allowed is False
    assert "requires approval" in decision.reason


def test_private_vault_task_allowed_with_approval():
    decision = cloud_escalation.classify_escalation_request(
        "Summarize my notes",
        "Agent/Memories/vellum-computer-use-gemma-orchestration.md",
        approval=True,
    )
    assert decision.privacy_class == "private"
    assert decision.allowed is True


def test_secret_content_is_blocked_even_with_approval():
    decision = cloud_escalation.classify_escalation_request(
        "Use this key",
        "OPENROUTER_API_KEY=sk-secret",
        approval=True,
    )
    assert decision.privacy_class == "secret"
    assert decision.allowed is False


def test_parse_structured_cloud_json():
    parsed = cloud_escalation.parse_cloud_response(
        '{"answer":"done","what_gemma_missed":"x","workflow_used":"y","lesson_for_vellum":"z","suggested_skill":"s"}'
    )
    assert parsed["answer"] == "done"
    assert parsed["lesson_for_vellum"] == "z"


def test_parse_non_json_cloud_text_as_best_effort():
    parsed = cloud_escalation.parse_cloud_response("Use pytest and inspect the traceback.")
    assert parsed["answer"] == "Use pytest and inspect the traceback."
    assert parsed["lesson_for_vellum"]
```

- [ ] **Step 2: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_cloud_escalation.py -q`

Expected: FAIL because `cloud_escalation.py` does not exist.

- [ ] **Step 3: Implement core module**

Create `backend/agent/tools/cloud_escalation.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any

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
        return EscalationDecision(PRIVACY_SECRET, False, "Escalation blocked because the request appears to contain secrets.")
    if any(pattern.casefold() in text for pattern in DESTRUCTIVE_PATTERNS):
        return EscalationDecision(PRIVACY_DESTRUCTIVE, approval, "Destructive or account-impacting escalation requires approval.")
    if any(pattern.casefold() in text for pattern in PRIVATE_PATTERNS):
        if approval:
            return EscalationDecision(PRIVACY_PRIVATE, True, "Private escalation approved by user.")
        return EscalationDecision(PRIVACY_PRIVATE, False, "Private vault or personal context requires approval before cloud escalation.")
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
```

- [ ] **Step 4: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_cloud_escalation.py -q`

Expected: PASS for privacy and parsing tests.

---

### Task 3: Cloud Call, Lesson Saving, And Tool Wrapper

**Files:**
- Modify: `backend/agent/tools/cloud_escalation.py`
- Modify: `backend/tests/test_cloud_escalation.py`

- [ ] **Step 1: Add tests for mocked escalation and lesson saving**

Append tests that monkeypatch `_call_cloud_model` and `obsidian_run`:

```python
def test_escalate_to_cloud_blocks_private_without_approval():
    result = cloud_escalation.escalate_to_cloud.invoke(
        {"task": "Use my memory", "context": "Agent/Memories/private.md", "approval": False}
    )
    assert "requires approval" in result


def test_escalate_to_cloud_blocks_secret(monkeypatch):
    result = cloud_escalation.escalate_to_cloud.invoke(
        {"task": "Use key", "context": "OPENROUTER_API_KEY=sk-secret", "approval": True}
    )
    assert "blocked" in result


def test_escalate_to_cloud_saves_lesson(monkeypatch):
    saved = {}

    def fake_cloud(task, context, privacy_class):
        return {
            "answer": "Use the traceback.",
            "what_gemma_missed": "It did not inspect the failing line.",
            "workflow_used": "Ran focused test, inspected traceback.",
            "lesson_for_vellum": "Always inspect the first concrete traceback line.",
            "suggested_skill": "Debug pytest failures from traceback first.",
        }

    def fake_obsidian(params):
        saved.update(params)
        return "saved"

    monkeypatch.setattr(cloud_escalation, "_call_cloud_model", fake_cloud)
    monkeypatch.setattr(cloud_escalation, "obsidian_run", fake_obsidian)

    result = cloud_escalation.escalate_to_cloud.invoke(
        {"task": "Debug public pytest failure", "context": "public repo traceback", "reason": "tool failed"}
    )

    assert "Cloud escalation used" in result
    assert "Use the traceback" in result
    assert saved["action"] == "write"
    assert saved["path"].startswith("Agent/Memories/Lessons/")
    assert "Always inspect" in saved["content"]
```

- [ ] **Step 2: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_cloud_escalation.py -q`

Expected: FAIL because the tool and `_call_cloud_model` are incomplete.

- [ ] **Step 3: Implement cloud call and tool**

Add to `backend/agent/tools/cloud_escalation.py`:

```python
def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return slug[:60] or "lesson"


def _lesson_path(task: str) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return f"Agent/Memories/Lessons/{today}-cloud-escalation-{_slugify(task)}.md"


def build_lesson_markdown(task: str, reason: str, privacy_class: str, model: str, parsed: dict[str, str]) -> str:
    captured_at = datetime.now(timezone.utc).isoformat()
    return f'''---
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
'''


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
            SystemMessage(content="You are Vellum's cloud escalation helper. Return only valid JSON with keys answer, what_gemma_missed, workflow_used, lesson_for_vellum, suggested_skill."),
            HumanMessage(content=f"Privacy class: {privacy_class}\n\nTask:\n{task}\n\nContext:\n{context}"),
        ]
    )
    return parse_cloud_response(str(result.content))


@tool
def escalate_to_cloud(task: str, context: str = "", reason: str = "", approval: bool = False) -> str:
    """Escalate difficult public/code/docs tasks to a stronger cloud model and save a reusable lesson.

    Public/code/docs tasks may escalate automatically. Private vault, memory, or personal context requires approval=True.
    Secrets/API keys/passwords are blocked. Cloud advice for destructive actions must not be executed without confirmation.
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
```

- [ ] **Step 4: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_cloud_escalation.py -q`

Expected: PASS.

---

### Task 4: Register Tool In Agent Prompt

**Files:**
- Modify: `backend/agent/graph/agent.py`
- Create/Modify: `backend/tests/test_cloud_escalation.py`

- [ ] **Step 1: Add prompt registration test**

Append:

```python
from agent.graph.agent import VELLUM_SYSTEM_PROMPT


def test_agent_prompt_mentions_cloud_escalation():
    assert "escalate_to_cloud" in VELLUM_SYSTEM_PROMPT
    assert "Private vault" in VELLUM_SYSTEM_PROMPT or "private vault" in VELLUM_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the test**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_cloud_escalation.py::test_agent_prompt_mentions_cloud_escalation -q`

Expected: FAIL.

- [ ] **Step 3: Register the tool**

In `backend/agent/graph/agent.py`, import:

```python
from agent.tools.cloud_escalation import escalate_to_cloud
```

Add a tool line:

```text
16. escalate_to_cloud - Escalate difficult public/code/docs tasks to a stronger cloud model; private vault or memory context requires approval.
```

Add prompt rules that public/code/docs can auto-escalate, private vault/memory requires approval, secrets are blocked, and saved lessons do not mean model weights changed.

Add `escalate_to_cloud` to both `build_agent` and `build_async_agent` tool lists.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_cloud_escalation.py backend\tests\test_config.py -q`

Expected: PASS.

---

### Task 5: Final Verification

**Files:**
- All changed implementation files.

- [ ] **Step 1: Compile changed Python files**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile backend\agent\tools\cloud_escalation.py backend\agent\graph\agent.py backend\agent\config.py
```

Expected: exit code 0.

- [ ] **Step 2: Run MCP/config/agent-related tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_cloud_escalation.py backend\tests\test_config.py backend\tests\test_mcp_tools.py backend\tests\test_access_control.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Inspect git diff**

Run:

```powershell
git diff -- backend\agent\tools\cloud_escalation.py backend\agent\graph\agent.py backend\agent\config.py backend\tests\test_cloud_escalation.py backend\tests\test_config.py
```

Expected: diff only contains cloud escalation implementation and tests.

- [ ] **Step 4: Commit implementation files only**

Run:

```powershell
git add backend\agent\tools\cloud_escalation.py backend\agent\graph\agent.py backend\agent\config.py backend\tests\test_cloud_escalation.py backend\tests\test_config.py docs\superpowers\plans\2026-05-15-cloud-escalation-agent.md
git commit -m "feat: add cloud escalation tool"
```

Expected: commit succeeds without staging unrelated files.
