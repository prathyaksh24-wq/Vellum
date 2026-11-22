"""Vellum learns from conversations, corrects itself, and heals its own failures.

The quick extractor in ``orchestrator._extract_candidates`` only catches
phrasings like "I prefer..." or "remember that...", so most conversations
taught Vellum nothing. The learner reads each conversation with a model (the
same one the memory engines use: the local model, or the cloud provider's
cheap model), alongside what Vellum already believes, and decides:

- **add**: durable things about the user (preferences, identity, projects,
  goals, how they like answers);
- **update**: an existing memory the conversation shows is wrong or outdated
  (self-correction, recorded as "corrected" with old and new text);
- **retire**: an existing memory the user contradicted (archived, so it can
  be restored).

Every change lands in the memory audit log as ``learned`` / ``corrected`` /
``retired`` with its source conversation, so growth and self-correction are
trackable from day one.

Self-healing: each conversation has a ledger row. Failures back off (2, 4,
8... minutes, capped at an hour), stop after five tries, and stopped
conversations get one more try a day. An unreachable model pauses the whole
run without spending anyone's attempts. A malformed model answer is retried
once with the error shown to the model before it counts as a failure. A
conversation is only learned once it has been quiet for a while, and again
whenever it grows.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 3600.0
DAILY_RETRY_SECONDS = 86400.0
QUIET_SECONDS = 600.0  # let a conversation settle before learning from it
CHUNK_CHARS = 3500
MAX_KNOWN = 40
KINDS = ("preference", "fact", "project", "correction")

SYSTEM = """You maintain a personal assistant's long-term memory about ONE user.
Read the conversation and the memories already saved. Return JSON only:
{"add": [{"kind": "preference|fact|project|correction", "text": "...", "confidence": 0.0-1.0}],
 "update": [{"id": 12, "text": "...", "reason": "..."}],
 "retire": [{"id": 34, "reason": "..."}]}
Rules:
- Only durable things about the user: who they are, preferences, how they want answers, projects, goals,
  tools they use, people and places that matter to them. Write each as one short third-person sentence
  ("Prefers concise answers with examples.").
- Skip one-off tasks, questions, pasted content, and anything the assistant said that the user didn't confirm.
- Never add something already saved. If the user changed their mind or a saved memory is wrong, use
  "update" (with the corrected sentence) or "retire" (if no longer true) with that memory's id.
- No secrets, passwords, financial or health details.
- At most 8 adds, 4 updates, 4 retires. Empty lists are fine. JSON only, no prose."""


_RUN_LOCK = threading.Lock()


class ModelUnavailable(RuntimeError):
    """The learning model can't be reached right now: pause, don't spend attempts."""


# -- the model ---------------------------------------------------------------------------


def ask_model(system: str, prompt: str, *, timeout: float = 300.0) -> str:
    """One chat completion from the memory engines' model (OpenAI-compatible endpoints)."""
    from agent.config import get_settings
    from agent.memory.engines.llm_routing import memory_engine_llm
    from agent.memory.local_llm import shared_context

    llm = memory_engine_llm()
    if not llm.ready:
        raise ModelUnavailable(llm.reason or "no model for learning")
    if llm.provider != "ollama" and get_settings().privacy_mode == "local_only":
        raise ModelUnavailable("privacy is set to local only; learning waits for a local model")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    headers = {"Content-Type": "application/json"}
    if llm.provider == "ollama":
        # Ollama's own API: thinking models (gemma4, qwen3) otherwise spend the
        # whole answer budget reasoning and return empty content.
        url = llm.base_url.rstrip("/").removesuffix("/v1") + "/api/chat"
        body: dict[str, Any] = {"model": llm.model, "messages": messages, "stream": False, "think": False,
                                "format": "json", "options": {"temperature": 0.1, "num_predict": 900,
                                                              **shared_context(llm.model)}}
    else:
        base = llm.base_url or {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "google": "https://generativelanguage.googleapis.com/v1beta/openai",
        }.get(llm.provider, "")
        url = f"{base.rstrip('/')}/chat/completions"
        body = {"model": llm.model, "messages": messages, "temperature": 0.1, "max_tokens": 2000, **llm.extra_body}
        if llm.provider in {"openai", "openrouter", "groq"}:
            body["response_format"] = {"type": "json_object"}
        if llm.api_key:
            headers["Authorization"] = f"Bearer {llm.api_key}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured provider
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 429} or exc.code >= 500:
            raise ModelUnavailable(f"{llm.provider} answered {exc.code}") from exc
        raise RuntimeError(f"{llm.provider} answered {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(exc):
            # Slow is not down: this conversation backs off and retries, the run goes on.
            raise RuntimeError(f"{llm.provider} took longer than {int(timeout)}s") from exc
        raise ModelUnavailable(f"{llm.provider} unreachable: {exc}") from exc
    if llm.provider == "ollama":
        return str((payload.get("message") or {}).get("content") or "")
    message = payload["choices"][0]["message"]
    # Reasoning models on some providers put the answer beside the reasoning.
    return str(message.get("content") or message.get("reasoning_content") or message.get("reasoning") or "")


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value] if value else []


def parse_ops(text: str, known_ids: set[int]) -> dict[str, list[dict[str, Any]]]:
    """Validate the model's answer; raise ValueError with a reason it can fix."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the answer")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("the answer must be a JSON object")
    ops: dict[str, list[dict[str, Any]]] = {"add": [], "update": [], "retire": []}
    for item in _as_list(data.get("add")):
        if isinstance(item, str):  # models sometimes list plain sentences
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text_ = str(item.get("text") or "").strip()
        kind = str(item.get("kind") or "fact").strip().lower()
        if 6 <= len(text_) <= 300:
            try:
                confidence = float(item.get("confidence") or 0.7)
            except (TypeError, ValueError):
                confidence = 0.7
            ops["add"].append({"kind": kind if kind in KINDS else "fact", "text": text_,
                               "confidence": max(0.0, min(1.0, confidence))})
    for key in ("update", "retire"):
        for item in _as_list(data.get(key)):
            if not isinstance(item, dict):
                continue
            try:
                memory_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if memory_id not in known_ids:
                continue  # never touch a memory the model wasn't shown
            entry = {"id": memory_id, "reason": str(item.get("reason") or "")[:200]}
            if key == "update":
                entry["text"] = str(item.get("text") or "").strip()
                if not 6 <= len(entry["text"]) <= 300:
                    continue
            ops[key].append(entry)
    ops["add"], ops["update"], ops["retire"] = ops["add"][:8], ops["update"][:4], ops["retire"][:4]
    return ops


# -- the learner -------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(text or "").lower()).strip()


def _words(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) > 3}


class ConversationLearner:
    def __init__(self, store: Any, conversations: Callable[[], list[dict[str, Any]]], *,
                 model: Callable[[str, str], str] = ask_model, clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.conversations = conversations
        self.model = model
        self.clock = clock or (lambda: datetime.now(UTC))
        self._ensure_tables()

    # ledger ---------------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        with self.store._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_learning (
                    thread_id TEXT PRIMARY KEY,
                    messages_seen INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    learned INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _ledger(self) -> dict[str, dict[str, Any]]:
        with self.store._connect() as conn:
            rows = conn.execute("SELECT * FROM memory_learning").fetchall()
        return {str(row["thread_id"]): dict(row) for row in rows}

    def _mark(self, thread_id: str, *, state: str, messages_seen: int | None = None, error: str = "",
              learned: int = 0) -> None:
        now = self.clock().isoformat()
        with self.store._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_learning (thread_id, messages_seen, state, attempts, learned, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    messages_seen = CASE WHEN ? IS NULL THEN memory_learning.messages_seen ELSE excluded.messages_seen END,
                    state = excluded.state,
                    attempts = CASE WHEN excluded.last_error != '' THEN memory_learning.attempts + 1 ELSE 0 END,
                    learned = memory_learning.learned + excluded.learned,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (thread_id, messages_seen or 0, state, 1 if error else 0, learned, error[:300], now, messages_seen),
            )

    def _age(self, iso: str) -> float:
        try:
            return (self.clock() - datetime.fromisoformat(str(iso).replace("Z", "+00:00"))).total_seconds()
        except (TypeError, ValueError):
            return float("inf")

    def due(self, limit: int = 20) -> list[dict[str, Any]]:
        """Conversations with new user messages that have gone quiet, plus failures whose wait is over."""
        ledger = self._ledger()
        picked: list[dict[str, Any]] = []
        for conversation in self.conversations():
            if conversation.get("temporary"):
                continue
            thread_id = str(conversation.get("thread_id") or conversation.get("id") or "")
            users = [m for m in conversation.get("messages") or [] if m.get("role") == "user" and m.get("text")]
            if not thread_id or not users:
                continue
            row = ledger.get(thread_id)
            if row and row["messages_seen"] >= len(users) and row["state"] == "learned":
                continue
            if self._age(conversation.get("updated_at") or "") < QUIET_SECONDS:
                continue  # still being talked in
            if row and row["state"] == "failed":
                attempts = int(row["attempts"])
                wait = DAILY_RETRY_SECONDS if attempts >= MAX_ATTEMPTS else min(60.0 * 2 ** attempts, MAX_BACKOFF_SECONDS)
                if self._age(row["updated_at"]) < wait:
                    continue
            picked.append({"thread_id": thread_id, "messages": users,
                           "seen": int(row["messages_seen"]) if row else 0, "title": conversation.get("title") or ""})
            if len(picked) >= limit:
                break
        return picked

    # one conversation -------------------------------------------------------------------

    def _known(self, text: str) -> list[dict[str, Any]]:
        saved = self.store.list_saved()
        words = _words(text)
        ranked = sorted(saved, key=lambda m: len(words & _words(m.get("text") or "")), reverse=True)
        return ranked[:MAX_KNOWN]

    def _ask(self, prompt: str, known_ids: set[int]) -> dict[str, list[dict[str, Any]]]:
        answer = self.model(SYSTEM, prompt)
        try:
            return parse_ops(answer, known_ids)
        except (ValueError, json.JSONDecodeError) as first:
            # Self-correct once: show the model what was wrong with its answer.
            retry = self.model(SYSTEM, f"{prompt}\n\nYour previous answer was rejected ({first}). "
                                       "Answer again with the JSON object only.")
            return parse_ops(retry, known_ids)

    def learn(self, item: dict[str, Any]) -> dict[str, int]:
        from agent.memory.quality import is_scaffold, user_words

        new_messages = item["messages"][item["seen"]:] or item["messages"]
        said = [user_words(str(m.get("text") or "")).strip() for m in new_messages]
        said = [s for s in said if s and not is_scaffold(s)]
        totals = {"added": 0, "corrected": 0, "retired": 0}
        text = "\n".join(f"- {s[:1500]}" for s in said)
        for start in range(0, max(len(text), 1), CHUNK_CHARS):
            chunk = text[start:start + CHUNK_CHARS].strip()
            if not chunk:
                continue
            known = self._known(chunk)
            known_ids = {int(m["id"]) for m in known}
            listing = "\n".join(f"[{m['id']}] ({m.get('kind')}) {m.get('text')}" for m in known) or "(nothing yet)"
            prompt = (f"Saved memories:\n{listing}\n\nConversation \"{item['title']}\" "
                      f"(the user's messages):\n{chunk}")
            ops = self._ask(prompt, known_ids)
            for key, value in self.apply(ops, item["thread_id"]).items():
                totals[key] += value
        return totals

    def apply(self, ops: dict[str, list[dict[str, Any]]], thread_id: str) -> dict[str, int]:
        counts = {"added": 0, "corrected": 0, "retired": 0}
        existing = {_norm(m.get("text") or "") for m in self.store.list_saved()}
        for add in ops["add"]:
            key = _norm(add["text"])
            if not key or key in existing:
                continue
            memory_id = self.store.add_pending(
                kind=add["kind"], text=add["text"], source_thread_id=thread_id,
                confidence=add["confidence"], scope="user_profile" if add["kind"] in {"preference", "correction"} else "global",
                origin="inferred",
            )
            if add["confidence"] >= 0.6:
                self.store.promote(memory_id)
            self.store.audit("learned", memory_id, f"From conversation {thread_id}: {add['text']}")
            existing.add(key)
            counts["added"] += 1
        for update in ops["update"]:
            try:
                before = self.store.get_memory(update["id"])["text"]
                self.store.update(update["id"], text=update["text"])
            except (KeyError, ValueError):
                continue  # gone, or pinned by the user: leave it
            self.store.audit("corrected", update["id"],
                             f"From conversation {thread_id}: \"{before}\" -> \"{update['text']}\" ({update['reason']})")
            counts["corrected"] += 1
        for retire in ops["retire"]:
            try:
                memory = self.store.get_memory(retire["id"])
                if memory.get("pinned"):
                    continue
                self.store.archive(retire["id"])
            except (KeyError, ValueError):
                continue
            self.store.audit("retired", retire["id"],
                             f"From conversation {thread_id}: \"{memory['text']}\" ({retire['reason']})")
            counts["retired"] += 1
        return counts

    # a run ------------------------------------------------------------------------------

    def run(self, *, budget_seconds: float = 240.0, limit: int = 20) -> dict[str, Any]:
        """Learn from due conversations within a time budget. Safe to call repeatedly."""
        result: dict[str, Any] = {"learned_from": 0, "added": 0, "corrected": 0, "retired": 0, "failed": 0,
                                  "paused": ""}
        # One run at a time (the schedule and "learn now" could overlap and learn twice).
        if not _RUN_LOCK.acquire(blocking=False):
            result["paused"] = "already learning"
            return result
        try:
            return self._run(result, budget_seconds=budget_seconds, limit=limit)
        finally:
            _RUN_LOCK.release()

    def _run(self, result: dict[str, Any], *, budget_seconds: float, limit: int) -> dict[str, Any]:
        from agent.foreground import user_is_active

        started = time.monotonic()
        for item in self.due(limit=limit):
            if time.monotonic() - started > budget_seconds:
                break
            if user_is_active():
                result["paused"] = "you're chatting; learning resumes when you pause"
                break
            try:
                counts = self.learn(item)
            except ModelUnavailable as exc:
                result["paused"] = str(exc)  # nobody's fault: try the whole run again later
                break
            except Exception as exc:  # noqa: BLE001 - recorded; backs off and retries
                logger.warning("[LEARN] %s failed: %s", item["thread_id"], exc)
                self._mark(item["thread_id"], state="failed", error=str(exc) or type(exc).__name__)
                result["failed"] += 1
                continue
            learned = counts["added"] + counts["corrected"] + counts["retired"]
            self._mark(item["thread_id"], state="learned", messages_seen=len(item["messages"]), learned=learned)
            result["learned_from"] += 1
            for key, value in counts.items():
                result[key] += value
        return result

    def status(self) -> dict[str, Any]:
        """Progress for status screens: how much of the user's history Vellum has learned from."""
        ledger = self._ledger()
        total = sum(1 for c in self.conversations()
                    if not c.get("temporary") and any(m.get("role") == "user" for m in c.get("messages") or []))
        states = {"learned": 0, "failed": 0, "stopped": 0}
        for row in ledger.values():
            if row["state"] == "failed":
                states["stopped" if int(row["attempts"]) >= MAX_ATTEMPTS else "failed"] += 1
            else:
                states["learned"] += 1
        with self.store._connect() as conn:
            events = dict(conn.execute(
                "SELECT event, COUNT(*) FROM memory_audit_log WHERE event IN ('learned', 'corrected', 'retired') "
                "GROUP BY event").fetchall())
        return {"conversations": total, **states, "waiting": max(total - sum(states.values()), 0),
                "events": {k: int(events.get(k, 0)) for k in ("learned", "corrected", "retired")}}


def default_learner() -> ConversationLearner:
    from agent.config import REPO_ROOT
    from agent.conversations.lifecycle import ConversationLifecycle
    from agent.memory.memory_context import _default_orchestrator

    lifecycle = ConversationLifecycle(path=Path(REPO_ROOT) / "data" / "ui" / "conversations.json")
    return ConversationLearner(_default_orchestrator().store, lifecycle.list)
