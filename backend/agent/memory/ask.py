"""Plan memory edits from a plain-language request ("Ask or update").

The local model turns a request into operations over the user's saved
memories. Adds, updates and suppressions apply immediately; deletions are
returned for the user to confirm, because they cannot be undone. When the
model is unavailable, simple rules cover remember / forget / delete.
"""
from __future__ import annotations

import re
from typing import Any

PLANNER_SYSTEM = """You edit a user's saved memories for a personal assistant.
Given the user's request and their memories (`id: text`), return JSON:
{"ops": [{"op": "add"|"update"|"suppress"|"delete", "memory_id": <id or null>, "text": "<new text or null>"}],
 "reply": "<one short sentence telling the user what you did>"}
- add: a new fact or preference the user stated. Write it as one plain sentence.
- update: change an existing memory's text (give memory_id and the corrected text).
- suppress: the user wants Vellum to stop using or mentioning a memory.
- delete: the user explicitly asked to delete or erase a memory.
Only use ids from the list. Return {"ops": [], "reply": "..."} when no change is needed,
for example when the user only asked a question about their memories."""


def plan_edits(request: str, memories: list[dict[str, Any]], *, planner: Any | None = None) -> dict[str, Any]:
    by_id = {int(item["id"]): item for item in memories}
    manifest = "\n".join(f"{item['id']}: {item['text']}" for item in memories[:150])
    prompt = f"Request: {request.strip()}\n\nMemories:\n{manifest or '(none yet)'}"
    try:
        if planner is not None:
            result = planner(PLANNER_SYSTEM, prompt)
        else:
            from agent.memory.local_llm import complete_json

            result = complete_json(PLANNER_SYSTEM, prompt, timeout=30.0, max_tokens=500)
        ops = _clean_ops(result.get("ops") if isinstance(result, dict) else None, by_id)
        reply = str(result.get("reply") or "").strip() if isinstance(result, dict) else ""
        if ops is not None:
            return {"ops": ops, "reply": reply, "planner": "model"}
    except Exception:  # noqa: BLE001 - fall back to rules
        pass
    return {**_rule_plan(request, memories), "planner": "rules"}


def _clean_ops(raw: Any, by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    ops: list[dict[str, Any]] = []
    for item in raw[:20]:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "").casefold()
        text = str(item.get("text") or "").strip()
        memory_id = item.get("memory_id")
        try:
            memory_id = int(memory_id) if memory_id is not None else None
        except (TypeError, ValueError):
            memory_id = None
        if op == "add" and text:
            ops.append({"op": "add", "text": text})
        elif op in {"update", "suppress", "delete"} and memory_id in by_id:
            if op == "update" and not text:
                continue
            ops.append({"op": op, "memory_id": memory_id, **({"text": text} if op == "update" else {})})
    return ops


def _rule_plan(request: str, memories: list[dict[str, Any]]) -> dict[str, Any]:
    from agent.memory.recall import keyword_rank

    clean = request.strip()
    forget = re.match(r"^(?:please\s+)?(forget|stop (?:using|mentioning)|don'?t mention)\s+(?:that\s+|about\s+)?(.+)$",
                      clean, re.I)
    delete = re.match(r"^(?:please\s+)?(?:delete|erase|remove)\s+(?:the\s+memory\s+(?:that|about)\s+)?(.+)$", clean, re.I)
    if delete:
        matches = keyword_rank(delete.group(1), memories, limit=3)
        return {"ops": [{"op": "delete", "memory_id": int(m["id"])} for m in matches],
                "reply": "Confirm to delete." if matches else "I couldn't find a memory matching that."}
    if forget:
        matches = keyword_rank(forget.group(2), memories, limit=3)
        return {"ops": [{"op": "suppress", "memory_id": int(m["id"])} for m in matches],
                "reply": "I'll stop using that." if matches else "I couldn't find a memory matching that."}
    remember = re.match(r"^(?:please\s+)?(?:remember|note|keep in mind)(?:\s+that)?\s+(.+)$", clean, re.I)
    if remember or re.match(r"^(?:i\s+(?:prefer|like|love|hate|don'?t like|am|work|live|use))\b", clean, re.I):
        text = (remember.group(1) if remember else clean).strip()
        text = text[:1].upper() + text[1:]
        return {"ops": [{"op": "add", "text": text if text.endswith((".", "!", "?")) else text + "."}],
                "reply": "Saved."}
    return {"ops": [], "reply": "Nothing to change. Try \"remember...\", \"forget...\" or \"delete...\"."}
