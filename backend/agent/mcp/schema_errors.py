"""Argument errors a model can fix in one step.

"Arguments do not match the published schema" left a small local model
retrying the same empty call until the turn stopped. The error now names what
was wrong, which fields are required and which are accepted.
"""
from __future__ import annotations

import json
from typing import Any


def schema_mismatch(provider: str, schema: dict[str, Any] | None, error: Any) -> str:
    schema = schema or {}
    reason = " ".join(str(getattr(error, "message", "") or error or "").split())[:200]
    required = list(schema.get("required") or [])
    accepted = sorted((schema.get("properties") or {}))[:30]
    return (f"Arguments do not match {provider}'s published schema" + (f": {reason}" if reason else "") +
            f". Required fields: {json.dumps(required)}; accepted fields: {json.dumps(accepted)}. "
            "Put them inside arguments and retry.")
