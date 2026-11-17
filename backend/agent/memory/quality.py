"""Decide which text is the user's own words and which of it is worth remembering.

The UI and the agent graph append context blocks to the user's message
(``[Attachment context]``, ``[Conversation follow-up context]``, ...) and can
prefix it with ``[Vellum UI mode: ...]``. Those blocks are prompt scaffolding,
not things the user said, so memory must never learn from them.

Memory should hold durable facts, preferences, projects and corrections. A
one-off request ("get me my repo on github", "@Linear what is my latest
issue") is a task, not something to remember about the user.
"""

from __future__ import annotations

import re
from typing import Any

# Blocks appended after the user's words. Everything from the first marker on
# is scaffolding, so user_words() cuts the text at the first match. The pattern
# has no leading or trailing wildcard: with ``\s*...\].*`` a long run of spaces
# made each scan position retry, which is quadratic on user-controlled text.
_SCAFFOLD_BLOCK_RE = re.compile(
    r"\[(?:Attachment context|Conversation follow-up context|Current conversation follow-up|"
    r"Conversation source context|Recent Vellum conversation context|Conversation knowledge context|"
    r"Specialist result)\]",
    re.IGNORECASE,
)
# Annotations the UI puts in front of (or inside) the user's words. The body
# stops at the next "[" as well as "]", so an unclosed annotation repeated many
# times cannot make every match attempt run to the end of the text.
_UI_ANNOTATION_RE = re.compile(r"\[Vellum UI (?:context|mode):[^\[\]]*\]", re.IGNORECASE)
# Whole prompts the UI writes on the user's behalf (buttons, templates).
_UI_TEMPLATE_RE = re.compile(
    r"^I'd like to create a new automation\b|\bverification (?:only|preview)\b|\bwithout submitting\b",
    re.IGNORECASE,
)

SCAFFOLD_MARKERS: tuple[str, ...] = (
    "[Attachment context]",
    "[Conversation follow-up context]",
    "[Current conversation follow-up]",
    "[Conversation source context]",
    "[Recent Vellum conversation context]",
    "[Conversation knowledge context]",
    "[Specialist result]",
    "[Vellum UI mode:",
    "[Vellum UI context:",
)


def user_words(text: str) -> str:
    """Return only what the user typed: no appended context blocks, no UI annotations."""
    clean = str(text or "")
    block = _SCAFFOLD_BLOCK_RE.search(clean)
    if block:
        clean = clean[:block.start()]
    clean = _UI_ANNOTATION_RE.sub(" ", clean)
    return " ".join(clean.split()).strip()


def is_scaffold(text: str) -> bool:
    """True when the text carries injected context or is a UI-written template prompt."""
    raw = str(text or "")
    folded = raw.casefold()
    if any(marker.casefold() in folded for marker in SCAFFOLD_MARKERS):
        return True
    return bool(_UI_TEMPLATE_RE.search(raw.strip()))


# Fillers that can precede a request ("ok so can you ...").
_LEAD_RE = re.compile(
    r"^(?:(?:please|pls|plz|ok(?:ay)?|so|now|also|and|then|hey|hi|yo|vellum|no|nah|"
    r"never ?mind|actually)[,.!\s]+)*"
    r"(?:(?:can|could|would|will) (?:you|u)(?: please)? |i (?:need|want) (?:you|u) to |"
    r"i'?d like (?:you|u) to |help me(?: to)? |let'?s |go ahead and |try to |please )*",
    re.IGNORECASE,
)
_REQUEST_VERB_RE = re.compile(
    r"(?:add|accumulate|collect|gather|track|monitor|scrape|sync|get|find|search|look (?:up|for|at|into)|show|list|open|create|make|generate|draw|write|draft|post|"
    r"send|reply|schedule|move|delete|remove|cancel|summari[sz]e|sumamrize|order|book|play|pause|skip|prepare|"
    r"set up|setup|change|switch|update|rename|run|check|tell|give|fetch|pull|download|upload|translate|"
    r"explain|compare|research|browse|click|navigate|go to|turn (?:on|off)|enable|disable|start|verify|test|"
    r"connect|install|uninstall|read|watch|buy|call|email|message|text|remind|save|export|import|fix|debug|"
    r"deploy|push|commit|merge|review|analy[sz]e|continue|retry|try again|redo|undo|use)\b",
    re.IGNORECASE,
)
_MENTION_RE = re.compile(r"(?:^|\s)@[A-Za-z][\w.-]*")
# Phrasing that makes an instruction a standing rule rather than a one-off.
_STANDING_RE = re.compile(
    r"\b(?:from now on|going forward|always|never(?! ?mind)|every time|each time|whenever|in (?:the )?future|"
    r"by default|next time|in general)\b",
    re.IGNORECASE,
)
# Reactions tied to the current turn: "for now we'll go with option a", "I like this sentence".
_TURN_BOUND_RE = re.compile(
    r"\b(?:for now|this time|right now|for this chat|option [a-d]\b|"
    r"(?:this|that) (?:sentence|one|answer|response|reply|version|approach|option|image|draft|idea)|"
    r"just (?:say|post|send|reply|write|tell|do))\b",
    re.IGNORECASE,
)


def is_one_off_request(text: str) -> bool:
    """True for a task or @-mention command that says nothing lasting about the user."""
    clean = user_words(text)
    if not clean:
        return False
    if _MENTION_RE.search(clean):
        return True
    if _STANDING_RE.search(clean):
        return False
    if _TURN_BOUND_RE.search(clean):
        return True
    rest = _LEAD_RE.sub("", clean, count=1)
    return bool(_REQUEST_VERB_RE.match(rest))


def junk_reason(item: dict[str, Any]) -> str:
    """Why a stored memory is not a real memory: "scaffold", "request", or "" when it is fine.

    Corrections keep their imperative lesson ("Check the tool result first.").
    Pinned, imported and hand-written memories are the user's call, so they are
    only flagged when they carry scaffolding.
    """
    text = str(item.get("text") or "")
    if item.get("pinned"):
        return ""
    if is_scaffold(text):
        return "scaffold"
    written_by_user = (str(item.get("origin") or "") == "imported"
                       or str(item.get("source_thread_id") or "") == "manual")
    if str(item.get("kind") or "") in {"correction", "manual"} or written_by_user:
        return ""
    if is_one_off_request(text):
        return "request"
    return ""
