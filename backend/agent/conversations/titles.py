"""Short, content-based chat titles.

After a chat's first exchange the UI asks for a title that says what the chat is
about, judged from the user's message and Vellum's reply together (so "hi, can you
help with something" followed by a resume review is titled after the resume, not
the greeting). One small call to the memory engines' model (local or the cloud
provider's cheap model) writes it; inputs are scrubbed locally first, and content
with secrets or identifiers never leaves the machine. Without a reachable model
the title falls back to the key words of the message.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

MAX_TITLE_CHARS = 48
MAX_TITLE_WORDS = 6

SYSTEM_PROMPT = """Write a title for a chat between a user and their assistant.
The title says what the chat is actually about, using the subject from both the request and the reply.
2 to 5 words, Title Case, no quotes, no trailing punctuation, no emojis, no words like "Chat" or "Conversation".
If the request sets up a recurring or scheduled task, start with "Scheduled", e.g. "Scheduled Job Matches".
Never output placeholders like [PERSON]. Reply with JSON only: {"title": "..."}"""

_FILLER = re.compile(
    r"^(?:hey|hi|hello|ok(?:ay)?|so|please|pls|vellum)[,!. ]+|"
    r"^(?:can|could|would|will) you (?:please )?|^i (?:want|need|would like) (?:you )?to |^help me (?:to )?|^let'?s ",
    re.I,
)
_SMALL_WORDS = {"a", "an", "and", "as", "at", "for", "from", "in", "of", "on", "or", "the", "to", "with", "vs"}


def suggest_title(message: str, reply: str = "", *, ask: Callable[[str, str], str] | None = None) -> dict[str, str]:
    """A title for a chat from its first exchange: ``{"title", "source"}``."""
    fallback = fallback_title(message)
    clean_message, clean_reply = _scrub(message), _scrub(reply)
    if clean_message is None or clean_reply is None:
        return {"title": fallback, "source": "fallback"}
    prompt = f"Request:\n{clean_message[:1500]}\n\nReply:\n{clean_reply[:1500]}"
    try:
        raw = (ask or _ask_model)(SYSTEM_PROMPT, prompt)
    except Exception as exc:  # noqa: BLE001 — naming must never fail a chat
        logger.info("[TITLES] model unavailable, using fallback: %s", exc)
        return {"title": fallback, "source": "fallback"}
    title = clean_title(raw)
    return {"title": title, "source": "model"} if title else {"title": fallback, "source": "fallback"}


def clean_title(raw: str) -> str:
    """Normalize a model title; empty when it is unusable."""
    text = str(raw or "")
    # The memory engines' model may run in JSON mode and answer {"title": "..."}.
    quoted = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.I)
    if quoted:
        text = quoted.group(1).replace('\\"', '"')
    elif text.lstrip().startswith("{"):
        return ""
    line = next((part for part in text.splitlines() if part.strip()), "")
    line = re.sub(r"^(?:title)\s*:\s*", "", line.strip(), flags=re.I)
    line = line.strip(" \t\"'`*#.:;!?-")
    if not line or "[" in line or "]" in line:
        return ""
    words = line.split()
    if len(words) > MAX_TITLE_WORDS + 2:
        return ""
    return " ".join(words[:MAX_TITLE_WORDS])[:MAX_TITLE_CHARS].strip()


def fallback_title(message: str) -> str:
    text = " ".join(str(message or "").split())
    for _ in range(3):
        text = _FILLER.sub("", text).strip()
    sentence = re.split(r"(?<=[.?!])\s|\n", text, maxsplit=1)[0]
    words = re.findall(r"[\w'+#&-]+", sentence)[:MAX_TITLE_WORDS]
    if not words:
        return "New chat"
    titled = [word if (word.isupper() or index and word.lower() in _SMALL_WORDS) else word[:1].upper() + word[1:]
              for index, word in enumerate(words)]
    return " ".join(titled)[:MAX_TITLE_CHARS].strip()


def _scrub(text: str) -> str | None:
    """Locally scrubbed text, or None when it holds secrets or identifiers."""
    from agent.privacy.classifier import RED_LABELS, RED_PATTERNS
    from agent.privacy.scrubber import PrivacyScrubber

    value = " ".join(str(text or "").split())
    if any(pattern.search(value) for pattern, _ in RED_PATTERNS):
        return None
    clean, replacements = PrivacyScrubber().scrub(value)
    if any(item.label in RED_LABELS for item in replacements):
        return None
    return clean


def _ask_model(system: str, prompt: str) -> str:
    from agent.memory.learner import ask_model

    return ask_model(system, prompt, timeout=45.0)
