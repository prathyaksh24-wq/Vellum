"""Public, bounded activity detail for the existing chat SSE channel."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

_SECRET = re.compile(r"password|passwd|secret|token|api.?key|authorization|cookie|credential", re.I)
_VALUE = re.compile(r"(?i)(bearer\s+)[\w.\-]+|\bsk-[\w-]+|((?:[?&]|\b)(?:token|password|authorization|cookie|api[_-]?key|secret)\s*[:=]\s*)[^&\s]+")


def activity_detail(value: Any, *, depth: int = 0) -> Any:
    """Keep inspectable inputs/results local without forwarding credentials."""
    if depth > 6:
        return "[nested content omitted]"
    if isinstance(value, dict):
        return {str(key): "[redacted]" if _SECRET.search(str(key)) else activity_detail(item, depth=depth + 1)
                for key, item in list(value.items())[:80]}
    if isinstance(value, (list, tuple)):
        return [activity_detail(item, depth=depth + 1) for item in value[:80]]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    # Parse JSON-shaped tool results before redacting their field values.
    if text.lstrip().startswith(('{', '[')):
        import json
        try:
            return activity_detail(json.loads(text), depth=depth + 1)
        except (ValueError, TypeError):
            pass
    text = _VALUE.sub(lambda match: (match[1] or match[2] or '') + '[redacted]', text)
    return text[:12000] + ('\n[preview truncated]' if len(text) > 12000 else '')


class AgentActivity(BaseModel):
    id: str
    type: str
    label: str
    detail: str = ""
    status: str = "in_progress"
    name: str = ""
    source: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    at: str
