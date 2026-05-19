"""Filter profiles for X tweet ingestion.

Each profile is a pure boolean function over an Apify item dict.
Register a profile in `PROFILES` and dispatch via `accepts(profile_name, item)`.
"""
from __future__ import annotations

import re
from typing import Any, Callable

_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]+")


def _text(item: dict[str, Any]) -> str:
    return (item.get("text") or item.get("full_text") or "").strip()


def _is_retweet(item: dict[str, Any]) -> bool:
    """Detect retweet across multiple actor shapes.

    - apidojo/tweet-scraper: `isRetweet` boolean
    - patient_discovery/twitter-user-tweets: `retweeted_tweet` object, or text starts with `RT @`
    """
    if item.get("isRetweet"):
        return True
    if item.get("retweeted_tweet") or item.get("retweetedTweet"):
        return True
    text = _text(item)
    if text.startswith("RT @"):
        return True
    return False


def _is_reply(item: dict[str, Any]) -> bool:
    if item.get("isReply"):
        return True
    if item.get("in_reply_to_status_id") or item.get("in_reply_to_user_id"):
        return True
    if item.get("inReplyToStatusId") or item.get("inReplyToUserId"):
        return True
    return False


def _is_quote(item: dict[str, Any]) -> bool:
    if item.get("isQuote") or item.get("isQuoteStatus"):
        return True
    if item.get("quoted_tweet") or item.get("quotedTweet"):
        return True
    return False


def _is_original(item: dict[str, Any]) -> bool:
    """Common rejection rules: must be an original tweet, no media."""
    if _is_retweet(item) or _is_reply(item) or _is_quote(item):
        return False
    if item.get("media"):
        return False
    return True


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
