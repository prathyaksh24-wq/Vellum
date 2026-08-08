"""Metadata-only audit records for MCP calls."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import threading
from typing import Any

from agent.config import REPO_ROOT


_AUDIT_LOCK = threading.Lock()


class McpAuditLog:
    """Append one content-free record for each remote MCP operation."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or (REPO_ROOT / "data" / "memory" / "mcp_audit_log.jsonl"))

    def record(
        self,
        *,
        plugin_id: str,
        connector: str,
        operation: str,
        tool_name: str,
        latency_ms: int,
        outcome: str,
    ) -> None:
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "plugin_id": plugin_id,
            "connector": connector,
            "operation": operation,
            "tool_name": tool_name,
            "call_count": 1,
            "latency_ms": max(0, int(latency_ms)),
            "outcome": outcome,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, sort_keys=True, separators=(",", ":"))
        with _AUDIT_LOCK, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
