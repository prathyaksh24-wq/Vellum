"""Aphorism classifier: rules-based filter over Apify tweet items."""
from __future__ import annotations

import re
from typing import Any

_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]+")

MAX_CHARS = 280
MIN_WORDS = 3
MAX_WORDS = 60
MAX_NEWLINES = 1
MAX_SENTENCES = 3


def is_aphorism(item: dict[str, Any]) -> bool:
    """Return True iff `item` is a short, standalone, wisdom-style tweet."""
    if item.get("isRetweet") or item.get("isReply") or item.get("isQuote"):
        return False

    text = (item.get("text") or "").strip()
    if not text:
        return False

    if len(text) > MAX_CHARS:
        return False

    if _URL_RE.search(text):
        return False

    if text.lstrip().startswith("@"):
        return False

    media = item.get("media") or []
    if media:
        return False

    if text.count("\n") > MAX_NEWLINES:
        return False

    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]
    if len(sentences) > MAX_SENTENCES:
        return False

    words = text.split()
    if len(words) < MIN_WORDS or len(words) > MAX_WORDS:
        return False

    return True
