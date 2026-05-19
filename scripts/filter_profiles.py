"""Filter profiles for X tweet ingestion.

Each profile is a pure boolean function over an Apify item dict.
Register a profile in `PROFILES` and dispatch via `accepts(profile_name, item)`.
"""
from __future__ import annotations

import re
from typing import Any, Callable

_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]+")


def _is_original(item: dict[str, Any]) -> bool:
    """Common rejection rules: must be an original tweet, no media."""
    if item.get("isRetweet") or item.get("isReply") or item.get("isQuote"):
        return False
    if item.get("media") or []:
        return False
    return True


def _text(item: dict[str, Any]) -> str:
    return (item.get("text") or "").strip()


def _aphorism(item: dict[str, Any]) -> bool:
    if not _is_original(item):
        return False
    text = _text(item)
    if not text:
        return False
    if len(text) > 280:
        return False
    if _URL_RE.search(text):
        return False
    if text.lstrip().startswith("@"):
        return False
    if text.count("\n") > 1:
        return False
    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]
    if len(sentences) > 3:
        return False
    words = text.split()
    if len(words) < 3 or len(words) > 60:
        return False
    return True


def _multiline_quote(item: dict[str, Any]) -> bool:
    if not _is_original(item):
        return False
    text = _text(item)
    if not text:
        return False
    if len(text) > 500:
        return False
    if _URL_RE.search(text):
        return False
    if text.lstrip().startswith("@"):
        return False
    if text.count("\n") > 10:
        return False
    words = text.split()
    if len(words) < 3:
        return False
    return True


def _original_tweet(item: dict[str, Any]) -> bool:
    if not _is_original(item):
        return False
    text = _text(item)
    if not text:
        return False
    if _URL_RE.search(text):
        return False
    words = text.split()
    if len(words) < 10:
        return False
    return True


PROFILES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "aphorism": _aphorism,
    "multiline_quote": _multiline_quote,
    "original_tweet": _original_tweet,
}


def accepts(profile_name: str, item: dict[str, Any]) -> bool:
    """Return True iff `item` passes the named filter profile."""
    if profile_name not in PROFILES:
        raise KeyError(f"Unknown filter profile: {profile_name}")
    return PROFILES[profile_name](item)
