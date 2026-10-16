"""Bounded normalization of command words; user-provided values stay verbatim."""
from __future__ import annotations

import re

_WORDS = frozenset({
    'change', 'switch', 'enable', 'disable', 'turn', 'show', 'hide', 'open', 'close',
    'background', 'theme', 'dark', 'light', 'provider', 'model', 'settings',
    'personalization', 'characteristics', 'warmth', 'enthusiasm', 'headers', 'emoji',
    'previous', 'restore', 'nickname', 'occupation', 'instructions', 'companion',
    'mode', 'name', 'with', 'from', 'this', 'that', 'more', 'less', 'your', 'please', 'read', 'date', 'time',
    'chat', 'agent', 'profile', 'default', 'memory', 'named', 'called', 'titled',
})
_ALIASES = {'u':'you', 'bg':'background', 'bgs':'backgrounds', 'charactrcitis':'characteristics', 'persoalization':'personalization'}


def _near_word(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        mismatches = [index for index, pair in enumerate(zip(left, right)) if pair[0] != pair[1]]
        return len(mismatches) == 1 or (
            len(mismatches) == 2 and mismatches[1] == mismatches[0] + 1
            and left[mismatches[0]] == right[mismatches[1]]
            and left[mismatches[1]] == right[mismatches[0]]
        )
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    return any(longer[:index] + longer[index + 1:] == shorter for index in range(len(longer)))


def normalize_command_words(message: str) -> str:
    text = ' '.join(str(message or '').split())
    command = re.sub(r'^(?:please\s+)?(?:(?:can|could|would|will)\s+(?:you|u)\s+)?(?:please\s+)?', '', text, flags=re.I)
    first = re.match(r'[a-zA-Z]+', command)
    verbs = {'change','switch','enable','disable','turn','show','hide','open','close','set','use','select','make','move','put','restore','install','remove','reset'}
    if first and first.group().casefold() not in verbs and not any(_near_word(first.group().casefold(), verb) for verb in verbs):
        if re.match(r"^(?:what|which)\b", text, re.I):
            return re.sub(r'\bbg\b','background',text,flags=re.I)
        return text
    # Only the command prefix is repaired. Quoted text and the value following
    # "to" are not spellchecked (names, instructions, secrets and model IDs).
    pieces = re.split(r'("[^"]*"|“[^”]*”|\s+to\s+)', text, flags=re.I)
    prefix = pieces[0]
    count = 0
    def repair(match):
        nonlocal count
        count += 1
        word = match.group().casefold()
        if word in _ALIASES:
            return _ALIASES[word]
        if word in _WORDS or (word.endswith('s') and word[:-1] in _WORDS) or len(word) < 4 or count > 8:
            return match.group()
        candidates = [candidate for candidate in _WORDS if _near_word(word, candidate)]
        return candidates[0] if len(candidates) == 1 else match.group()
    pieces[0] = re.sub(r'\b[a-zA-Z]+\b', repair, prefix)
    return ''.join(pieces)


def normalize_clock_question(message: str) -> str:
    text = re.sub(r'\b(?:tiime|tiem|tmie)\b', 'time', str(message), flags=re.I)
    return re.sub(r'^what\s+is\s+it\s+time\b', 'what is the time', text, flags=re.I)
