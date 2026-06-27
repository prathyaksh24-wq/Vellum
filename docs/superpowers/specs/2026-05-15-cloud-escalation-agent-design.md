# Cloud Escalation Agent Design

## Summary

Vellum should keep Gemma 4 31B as the default brain while adding a cloud escalation path for tasks Gemma cannot handle reliably. The escalation path is exposed as a normal LangGraph tool so Gemma can call it like a skill, but the tool enforces privacy and safety rules before sending any context to a cloud model.

## Goals

- Let Gemma attempt tasks first by default.
- Escalate public/code/docs tasks automatically when the task is complex, Gemma is stuck, or tools fail repeatedly.
- Require user approval before sending private vault, memory, or personal data to a cloud model.
- Never send secrets, API keys, passwords, tokens, or sensitive credentials.
- Save cloud-model teaching artifacts back into Obsidian so Vellum improves through memory, skills, and orchestration.
- Stay honest: Vellum may behave as if it learned through saved lessons, but it must not claim Gemma's model weights changed unless real fine-tuning happened.

## Non-Goals

- No full parallel multi-agent architecture in this first version.
- No automatic fine-tuning.
- No automatic execution of destructive actions recommended by the cloud model.
- No cloud escalation for sensitive private content without explicit approval.

## Architecture

Add a new tool named `escalate_to_cloud`.

Gemma can call this tool when:

- The task involves public code, documentation, web research, or repository context and is too complex for the current attempt.
- A tool fails repeatedly or returns confusing results.
- Gemma cannot form a reliable plan.
- The user explicitly asks to escalate, use a stronger model, or use a cloud model.

The tool will route to a configured flagship model, initially the active registry flagship or `google/gemini-2.5-pro` when available. The exact model should be configurable later through env.

## Privacy Policy

Each escalation request is classified before calling the cloud model.

- `public`: code, docs, public web, public GitHub, public APIs. Auto-escalation allowed.
- `private`: vault notes, memories, personal preferences, user history, personal files. Approval required before cloud call.
- `secret`: API keys, tokens, passwords, credentials, private auth material. Escalation blocked.
- `destructive`: deletes, pushes, purchases, account changes, message sending. Cloud may advise only; Vellum must ask before execution.

The first implementation can use conservative heuristics:

- If content mentions vault paths, `Agent/Memories`, `X/`, `Youtube/`, `Sports/`, `.env`, keys, tokens, passwords, or personal records, treat it as private or secret.
- If uncertain, treat it as private and ask for approval.

## Cloud Response Contract

The escalation tool should ask the cloud model for structured output:

```json
{
  "answer": "The direct result or recommended solution.",
  "what_gemma_missed": "The key reasoning/tool-use gap.",
  "workflow_used": "The steps the cloud model used.",
  "lesson_for_vellum": "Reusable lesson for future similar tasks.",
  "suggested_skill": "Optional candidate skill/playbook text."
}
```

If the cloud model does not return valid JSON, Vellum should still return the answer and save a best-effort lesson summary.

## Memory And Skill Capture

For successful escalations, save a lesson note to:

`Agent/Memories/Lessons/YYYY-MM-DD-cloud-escalation-<slug>.md`

Each lesson note should include:

- original task summary,
- privacy class,
- model used,
- why escalation happened,
- what Gemma missed,
- workflow used,
- reusable lesson,
- suggested future skill if present.

Repeated lessons can later be promoted into active skills. Promotion is not part of this first version.

## User Experience

For public/code tasks, escalation can happen automatically and the final response should say when a cloud fallback was used.

For private tasks, Vellum should ask before escalation with a concise message:

> This may require sending private vault or memory context to a cloud model. I can summarize/redact it first, or keep this local. Proceed?

For secret content, Vellum should refuse escalation and continue locally or ask the user to remove secrets.

## Error Handling

- If cloud escalation fails, return the local best-effort result plus the error.
- If approval is required and not provided, do not call the cloud model.
- If lesson saving fails, return the cloud result and mention that the lesson was not saved.
- If the cloud model suggests destructive action, mark it as advice only and require confirmation before any tool executes it.

## Testing

Unit tests should cover:

- public task auto-escalates,
- private vault task requires approval,
- secret-like content is blocked,
- structured cloud response parsing,
- fallback parsing for non-JSON output,
- lesson note generation,
- cloud failure returns a useful error,
- agent prompt includes the escalation tool and privacy rules.

Integration smoke tests should use a mocked cloud model by default. A live test can be optional and env-gated.

## Open Implementation Notes

- The first version should be a tool, not a pre-agent router.
- Store lessons through the existing Obsidian API path.
- Keep parallel orchestration as a later phase after enough escalation traces exist.
- The tool description should be explicit so Gemma knows when to use it and when not to.
