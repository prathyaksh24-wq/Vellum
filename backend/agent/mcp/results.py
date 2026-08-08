"""Normalize MCP results before they enter the agent context."""

from __future__ import annotations

from collections import Counter
import json
import re

UNREACHABLE = "Unreachable."
MAX_MCP_RESULT_CHARS = 12_000
_FAILURE_PREFIXES = (
    "apify search failed:",
    "apify search timed out after ",
    "context7 mcp failed:",
    "context7 mcp timed out after ",
    "context mode failed:",
    "context mode timed out after ",
    "filesystem mcp failed:",
    "filesystem mcp timed out after ",
    "firecrawl mcp failed:",
    "firecrawl mcp timed out after ",
    "github mcp failed:",
    "github mcp timed out after ",
    "gitmcp failed:",
    "gitmcp timed out after ",
    "obsidian mcp failed:",
    "obsidian mcp timed out after ",
    "playwright mcp failed:",
    "playwright mcp timed out after ",
    "tavily mcp failed:",
    "tavily mcp timed out after ",
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WORDS = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_UNSAFE_INSTRUCTION = re.compile(
    r"(?:\b(ignore|disregard|forget|override|reveal|execute|delete|exfiltrate)\b.{0,160}"
    r"\b(instruction|prompt|message|record|file|command|secret|policy)s?\b)"
    r"|(?:\b(send|upload|post|share|expose|return|provide|disclose)\b.{0,160}"
    r"\b(conversation|history|messages?|prompt|secrets?|credentials?|private data)\b)"
    r"|(?:\b(you|assistant|model)\s+(must|should|need to|are instructed to)\b)"
    r"|(?:\b(system|developer|assistant)\s+(prompt|message|instruction)\b)"
    r"|(?:<(system|developer|assistant|tool)>|\[(system|developer|assistant|inst)\])",
    re.IGNORECASE,
)
_SAFE_PATH_PART = re.compile(r"[^A-Za-z0-9_.\[\]-]+")
_SAFE_STRING_FIELDS = frozenset(
    {
        "author", "city", "country", "currency", "date", "href", "id",
        "label", "location", "model", "name", "observed_on", "price",
        "provider", "status", "time", "title", "type", "uri", "url", "version",
    }
)
_URL = re.compile(r"https?://[^\s<>\]\)]+", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-Z]+)?\b")
_NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?![A-Za-z])")
_SUMMARY_STOPWORDS = frozenset(
    {
        "and", "are", "but", "for", "from", "has", "have", "into", "not",
        "the", "their", "this", "that", "was", "were", "with", "your",
        "person", "email", "phone", "location", "address", "organization",
        "redacted", "secret", "government_id", "credit_card", "financial_id",
    }
)


def looks_unreachable(value: object) -> bool:
    """Recognize legacy adapter failures without exposing their details."""

    text = str(value or "").strip()
    lowered = text.casefold()
    return text == UNREACHABLE or any(lowered.startswith(prefix) for prefix in _FAILURE_PREFIXES)


def normalize_mcp_text(value: object, *, max_chars: int = MAX_MCP_RESULT_CHARS) -> str:
    """Return a bounded, display-safe projection of an MCP result.

    The projection preserves source text for accurate retrieval while removing
    control characters and preventing one tool call from consuming unbounded
    model context.
    """

    if looks_unreachable(value):
        return UNREACHABLE

    text = _CONTROL_CHARS.sub("", str(value or "")).replace("\r\n", "\n").strip()
    if len(text) <= max_chars:
        return text

    boundary = text.rfind("\n", 0, max_chars)
    if boundary < max_chars // 2:
        boundary = max_chars
    return text[:boundary].rstrip() + "\n\n[MCP result truncated locally]"


def summarize_mcp_text(
    value: object,
    *,
    max_terms: int = 12,
    max_facts: int = 24,
) -> str:
    """Return a bounded fact projection without forwarding connector output wholesale."""

    text = normalize_mcp_text(value)
    if text == UNREACHABLE:
        return text
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, list):
        kind = "json_list"
        item_count = len(parsed)
        field_names = _json_field_names(parsed)
    elif isinstance(parsed, dict):
        kind = "json_object"
        item_count = len(parsed)
        field_names = _json_field_names(parsed)
    else:
        kind = "text"
        item_count = len([line for line in text.splitlines() if line.strip()])
        field_names = []
    facts = _project_facts(parsed, text, max_facts=max_facts)
    accepted_text = "\n".join(facts)
    terms = Counter(
        token
        for token in (match.group(0).casefold() for match in _WORDS.finditer(accepted_text))
        if token not in _SUMMARY_STOPWORDS and not token.startswith("masked")
    )
    term_text = ", ".join(
        f"{term} ({count})" for term, count in terms.most_common(max_terms)
    ) or "none"
    lines = [
        "<MCP_RESULT_SUMMARY>",
        f"kind: {kind}",
        f"characters: {len(text)}",
        f"items_or_lines: {item_count}",
    ]
    if field_names:
        lines.append("fields: " + ", ".join(field_names))
    if facts:
        lines.append("facts:")
        lines.extend(f"- {fact}" for fact in facts)
    lines.extend((f"top_terms: {term_text}", "</MCP_RESULT_SUMMARY>"))
    return "\n".join(lines)


def _json_field_names(value: object) -> list[str]:
    records = value if isinstance(value, list) else [value]
    names: set[str] = set()
    for record in records[:50]:
        if not isinstance(record, dict):
            continue
        for key in record:
            clean = str(key)
            if _WORDS.fullmatch(clean) and not _unsafe_field_name(clean):
                names.add(clean)
    return sorted(names)[:30]


def _project_facts(parsed: object, text: str, *, max_facts: int) -> list[str]:
    facts: list[str] = []

    def visit(value: object, path: str) -> None:
        if len(facts) >= max_facts:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if _unsafe_field_name(str(key)):
                    continue
                clean_key = _SAFE_PATH_PART.sub("_", str(key)).strip("_") or "field"
                visit(child, f"{path}.{clean_key}" if path else clean_key)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]" if path else f"item[{index}]")
            return
        field_name = path.rsplit(".", 1)[-1].split("[", 1)[0].casefold()
        projected = _safe_scalar(value, allow_text=_safe_string_field(field_name))
        if projected is not None:
            facts.append(f"{path or 'value'} = {projected}")

    if isinstance(parsed, (dict, list)):
        visit(parsed, "")
        return facts

    for index, raw_line in enumerate(line for line in text.splitlines() if line.strip()):
        if len(facts) >= max_facts:
            break
        line = " ".join(raw_line.split())
        if _UNSAFE_INSTRUCTION.search(line):
            facts.append(f"line[{index}] = [unsafe-text-omitted]")
            continue
        key, separator, value = line.partition(":")
        if not separator:
            key, separator, value = line.partition("=")
        if separator and key.strip() and value.strip():
            label = _SAFE_PATH_PART.sub("_", key.strip()).strip("_") or f"line[{index}]"
            projected = _safe_scalar(
                value.strip(),
                allow_text=_safe_string_field(label.casefold()),
            )
            if projected is not None:
                facts.append(f"{label} = {projected}")
            continue
        for url in _URL.findall(line):
            facts.append(f"line[{index}].url = {json.dumps(url, ensure_ascii=False)}")
        for date in _ISO_DATE.findall(line):
            facts.append(f"line[{index}].date = {json.dumps(date, ensure_ascii=False)}")
        for number in _NUMBER.findall(line):
            facts.append(f"line[{index}].number = {number}")
    return facts


def _safe_string_field(field_name: str) -> bool:
    return (
        field_name in _SAFE_STRING_FIELDS
        or field_name.endswith("_id")
        or field_name.endswith("_at")
        or field_name.endswith("_date")
        or field_name.endswith("_url")
    )


def _unsafe_field_name(field_name: str) -> bool:
    normalized = re.sub(r"[_-]+", " ", field_name)
    return len(field_name) > 80 or _UNSAFE_INSTRUCTION.search(normalized) is not None


def _safe_scalar(value: object, *, allow_text: bool) -> str | None:
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    text = " ".join(str(value).split())
    if not allow_text:
        return None
    if _UNSAFE_INSTRUCTION.search(text):
        return "[unsafe-text-omitted]"
    if len(text) > 240:
        terms = [match.group(0).casefold() for match in _WORDS.finditer(text)]
        summary = ", ".join(dict.fromkeys(terms))[:200]
        return json.dumps(f"topics: {summary}", ensure_ascii=False)
    return json.dumps(text, ensure_ascii=False)
