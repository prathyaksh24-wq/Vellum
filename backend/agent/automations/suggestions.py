"""Personal scheduled-task suggestions for the Scheduled page.

Suggestions come from what Vellum has learned about the user (saved memories),
what they have been chatting about recently (conversation titles), and the tasks
they already have, so the page proposes automations that fit this user instead of
a fixed list. One model call (the memory engines' model: local or the cloud
provider's cheap model, via ``learner.ask_model``) turns those signals into a few
task ideas. Signals are scrubbed locally first; items carrying secrets,
government or financial identifiers are dropped. Under local-only privacy with no
local model, the call is refused and the page shows starter ideas.

Results are cached in ``automation-suggestions.json`` beside the automation store
and refreshed in the background when the signals change or the cache ages out, so
opening the page never waits on a model.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

CACHE_FILE = "automation-suggestions.json"
FRESH_FOR = timedelta(hours=12)
RETRY_UNAVAILABLE_AFTER = timedelta(minutes=30)
MAX_SUGGESTIONS = 6
MAX_MEMORIES = 30
MAX_CHATS = 15
ICONS = ("research", "news", "music", "book", "shopping", "calendar", "code", "sports",
         "travel", "health", "money", "work", "learning", "home")

# Shown before anything is learned, or when no model can be reached.
STARTER_SUGGESTIONS: list[dict[str, str]] = [
    {"name": "Morning brief", "icon": "news",
     "request": "Every weekday at 8am, brief me on the news and topics I care about.", "reason": ""},
    {"name": "Weekend reads", "icon": "book",
     "request": "Every Saturday morning, send me one great long read that matches my interests.", "reason": ""},
    {"name": "Weekly review", "icon": "calendar",
     "request": "Every Sunday evening, summarize what I worked on and talked about this week and suggest priorities for next week.", "reason": ""},
    {"name": "Price watch", "icon": "shopping",
     "request": "Check daily whether an item I name drops in price and tell me when it does.", "reason": ""},
]

SYSTEM_PROMPT = """You suggest scheduled tasks for a personal assistant app called Vellum.
A scheduled task is a request Vellum runs on its own on a schedule (research, monitoring,
briefings, reminders, summaries) and delivers as a chat or notification.

You get what Vellum knows about the user, their recent chat titles, and tasks they already have.
Suggest tasks that would genuinely save this user time or keep them informed, grounded in
their actual interests and habits. Prefer recurring work they seem to do by hand.

Rules:
- Each suggestion names a concrete schedule inside "request" (for example "Every Friday at 6pm, ...").
- "request" is written as the user would ask it, one or two sentences, under 220 characters.
- "name" is 2 to 4 words. "reason" is one short line on why it fits this user, under 90 characters.
- "icon" is one of: {icons}.
- Do not repeat or closely duplicate an existing task, and do not suggest maintaining Vellum itself
  (memory, skills, indexing): Vellum already does that on its own. No tasks that send messages, post, buy or
  delete anything. Never include placeholders like [PERSON] in the output.
- Return JSON only: {{"suggestions": [{{"name": "...", "icon": "...", "request": "...", "reason": "..."}}]}}
  with {count} suggestions."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AutomationSuggestions:
    """Cached, background-refreshed suggestions. Safe to call from request handlers."""

    def __init__(
        self,
        root: str | Path,
        *,
        signals: Callable[[], dict[str, Any]] | None = None,
        ask: Callable[[str, str], str] | None = None,
        background: bool = True,
    ) -> None:
        self.path = Path(root) / CACHE_FILE
        self._signals = signals or collect_signals
        self._ask = ask or _ask_model
        self._background = background
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def snapshot(self, *, refresh: bool = False) -> dict[str, Any]:
        """Current suggestions; starts a refresh when they are stale, missing or asked for."""
        cache = self._read()
        try:
            signals = self._signals()
        except Exception as exc:  # noqa: BLE001 — suggestions must never break the page
            logger.warning("[AUTOMATIONS] suggestion signals unavailable: %s", exc)
            signals = {}
        fingerprint = _fingerprint(signals)
        if refresh or self._stale(cache, fingerprint):
            self._start_refresh(signals, fingerprint)
            cache = self._read()  # a synchronous refresh has already written its result
        refreshing = self._refreshing()
        suggestions = cache.get("suggestions") if cache.get("source") == "learned" else None
        return {
            "suggestions": suggestions or [dict(item) for item in STARTER_SUGGESTIONS],
            "source": "learned" if suggestions else "starter",
            "status": "refreshing" if refreshing else cache.get("status", "ready"),
            "reason": cache.get("reason", ""),
            "generated_at": cache.get("generated_at"),
        }

    def refresh_now(self, signals: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate synchronously (tests and the background worker)."""
        signals = signals if signals is not None else self._signals()
        fingerprint = _fingerprint(signals)
        record: dict[str, Any] = {"fingerprint": fingerprint, "generated_at": _now().isoformat()}
        if not signals.get("memories") and not signals.get("chats"):
            record.update(source="starter", status="ready", reason="Vellum has not learned enough about you yet.")
            self._write(record)
            return record
        try:
            raw = self._ask(SYSTEM_PROMPT.format(icons=", ".join(ICONS), count=MAX_SUGGESTIONS),
                            _user_prompt(scrub_signals(signals)))
            suggestions = parse_suggestions(raw, existing=signals.get("tasks", []))
        except Exception as exc:  # noqa: BLE001 — model failures fall back to starter ideas
            logger.info("[AUTOMATIONS] suggestions unavailable: %s", exc)
            previous = self._read()
            record.update(source=previous.get("source", "starter"), suggestions=previous.get("suggestions"),
                          status="unavailable", reason=str(exc)[:200])
            record["fingerprint"] = previous.get("fingerprint", "")
            record["failed_at"] = _now().isoformat()
            self._write(record)
            return record
        if not suggestions:
            record.update(source="starter", status="ready", reason="No suggestions fit yet.")
        else:
            record.update(source="learned", status="ready", suggestions=suggestions, reason="")
        self._write(record)
        return record

    # -- internals ------------------------------------------------------------------

    def _stale(self, cache: dict[str, Any], fingerprint: str) -> bool:
        if cache.get("status") == "unavailable":
            failed = _date(cache.get("failed_at"))
            return failed is None or _now() - failed > RETRY_UNAVAILABLE_AFTER
        generated = _date(cache.get("generated_at"))
        if generated is None:
            return True
        if cache.get("fingerprint") != fingerprint:
            # New memories or chats arrive often; regenerate at most hourly for them.
            return _now() - generated > timedelta(hours=1)
        return _now() - generated > FRESH_FOR

    def _refreshing(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def _start_refresh(self, signals: dict[str, Any], fingerprint: str) -> None:
        with self._lock:
            if self._refreshing():
                return
            if not self._background:
                self.refresh_now(signals)
                return
            self._worker = threading.Thread(target=self.refresh_now, args=(signals,),
                                            name="automation-suggestions", daemon=True)
            self._worker.start()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, record: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            logger.warning("[AUTOMATIONS] could not save suggestions: %s", exc)


def parse_suggestions(raw: str, *, existing: list[str] | None = None) -> list[dict[str, str]]:
    """Validate the model's JSON into clean suggestions, dropping duplicates and junk."""
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise ValueError("the model returned no JSON")
    items = json.loads(match.group(0)).get("suggestions")
    if not isinstance(items, list):
        raise ValueError("the model returned no suggestions list")
    taken = {_key(name) for name in existing or []}
    result: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("name"), 48)
        request = _clean(item.get("request"), 280)
        if not name or not request or "[" in request or _key(name) in taken:
            continue
        icon = str(item.get("icon") or "").strip().lower()
        result.append({
            "name": name,
            "icon": icon if icon in ICONS else "research",
            "request": request,
            "reason": _clean(item.get("reason"), 120),
        })
        taken.add(_key(name))
        if len(result) == MAX_SUGGESTIONS:
            break
    return result


def collect_signals() -> dict[str, Any]:
    """What the suggestions are grounded in (raw; ``scrub_signals`` runs before any model call)."""
    from agent import api  # lazy: the main api module mounts the automations router
    from agent.automations.api import get_store
    from agent.conversations.lifecycle import ConversationLifecycle

    memories: list[str] = []
    store = getattr(api._memory_orchestrator, "store", None)
    if store is not None:
        rows = [row for row in store.list_saved() if not row.get("suppressed")]
        rows.sort(key=lambda row: (bool(row.get("pinned")), int(row.get("use_count") or 0), str(row.get("updated_at") or "")),
                  reverse=True)
        for row in rows:
            if row.get("topic") == "How to talk to me":
                continue  # tone preferences say nothing about useful tasks
            text = " ".join(str(row.get("text") or "").split())
            if text:
                memories.append(text[:160])
            if len(memories) >= MAX_MEMORIES:
                break
    chats: list[str] = []
    conversations = ConversationLifecycle(path=api._UI_CONVERSATIONS_PATH).list_view()
    conversations = sorted(conversations, key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    for row in conversations:
        if row.get("archived") or str(row.get("id") or "").startswith(("automation-", "scheduled-task-")):
            continue
        title = " ".join(str(row.get("title") or "").split())
        if title and title.lower() not in {"new chat", "new conversation"}:
            chats.append(title[:100])
        if len(chats) >= MAX_CHATS:
            break
    # Built-in maintenance jobs count as existing tasks so they are not suggested again.
    tasks = [str(task.get("name") or "") for task in get_store().list()]
    return {"memories": memories, "chats": chats, "tasks": tasks}


def _user_prompt(signals: dict[str, Any]) -> str:
    lines = ["What Vellum knows about the user:"]
    lines += [f"- {text}" for text in signals.get("memories", [])] or ["- (nothing yet)"]
    lines += ["", "Recent chat titles:"]
    lines += [f"- {text}" for text in signals.get("chats", [])] or ["- (none)"]
    lines += ["", "Tasks they already have:"]
    lines += [f"- {text}" for text in signals.get("tasks", [])] or ["- (none)"]
    return "\n".join(lines)


def scrub_signals(signals: dict[str, Any]) -> dict[str, Any]:
    """Scrub signals locally (Presidio + patterns); drop items carrying secrets or identifiers."""
    from agent.privacy.classifier import RED_LABELS, RED_PATTERNS
    from agent.privacy.scrubber import PrivacyScrubber

    scrubber = PrivacyScrubber()

    def safe(value: Any) -> str:
        text = " ".join(str(value or "").split())
        if not text or any(pattern.search(text) for pattern, _ in RED_PATTERNS):
            return ""
        clean, replacements = scrubber.scrub(text)
        return "" if any(item.label in RED_LABELS for item in replacements) else clean

    return {
        "memories": [text for text in map(safe, signals.get("memories", [])) if text],
        "chats": [text for text in map(safe, signals.get("chats", [])) if text],
        "tasks": [text for text in map(safe, signals.get("tasks", [])) if text],
    }


def _ask_model(system: str, prompt: str) -> str:
    from agent.memory.learner import ask_model

    return ask_model(system, prompt, timeout=240.0)


def _fingerprint(signals: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(signals, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _date(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_SERVICE: AutomationSuggestions | None = None


def get_suggestions_service() -> AutomationSuggestions:
    global _SERVICE
    from agent.automations.api import get_store

    root = get_store().root
    if _SERVICE is None or _SERVICE.path.parent != Path(root):
        _SERVICE = AutomationSuggestions(root)
    return _SERVICE
