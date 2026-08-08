"""Local, operation-bound approvals for mutating plugin MCP calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from agent.config import REPO_ROOT


class PluginMcpApprovalError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _arguments_hash(arguments: dict[str, Any]) -> str:
    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PluginMcpOperation:
    plugin_id: str
    connector: str
    tool_name: str
    arguments_hash: str

    @classmethod
    def from_arguments(
        cls,
        *,
        plugin_id: str,
        connector: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> "PluginMcpOperation":
        return cls(
            plugin_id=plugin_id,
            connector=connector,
            tool_name=tool_name,
            arguments_hash=_arguments_hash(arguments),
        )


class PluginMcpApprovalStore:
    """Persist approval state without storing tool arguments or user content."""

    def __init__(self, path: Path, *, ttl: timedelta = timedelta(minutes=5)) -> None:
        self.path = Path(path)
        self.ttl = ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS plugin_mcp_approvals (
                    id TEXT PRIMARY KEY,
                    plugin_id TEXT NOT NULL,
                    connector TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def request(self, operation: PluginMcpOperation) -> dict[str, Any]:
        now = _now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM plugin_mcp_approvals
                WHERE plugin_id=? AND connector=? AND tool_name=? AND arguments_hash=?
                  AND status IN ('pending','approved') AND expires_at>?
                ORDER BY created_at DESC LIMIT 1
                """,
                (
                    operation.plugin_id,
                    operation.connector,
                    operation.tool_name,
                    operation.arguments_hash,
                    now.isoformat(),
                ),
            ).fetchone()
            if row is not None:
                return self._public(row)
            approval_id = uuid4().hex
            expires_at = now + self.ttl
            connection.execute(
                """
                INSERT INTO plugin_mcp_approvals
                (id,plugin_id,connector,tool_name,arguments_hash,status,created_at,expires_at,updated_at)
                VALUES (?,?,?,?,?,'pending',?,?,?)
                """,
                (
                    approval_id,
                    operation.plugin_id,
                    operation.connector,
                    operation.tool_name,
                    operation.arguments_hash,
                    now.isoformat(),
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )
            return self.get(approval_id, connection=connection)

    def approve(self, approval_id: str) -> dict[str, Any]:
        return self._transition(approval_id, expected="pending", target="approved")

    def reject(self, approval_id: str) -> dict[str, Any]:
        return self._transition(approval_id, expected="pending", target="rejected")

    def consume(self, approval_id: str, operation: PluginMcpOperation) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM plugin_mcp_approvals WHERE id=?", (approval_id,)
            ).fetchone()
            if row is None:
                raise PluginMcpApprovalError("plugin MCP approval was not found")
            status = str(row["status"])
            if datetime.fromisoformat(str(row["expires_at"])).astimezone(UTC) <= _now():
                connection.execute(
                    "UPDATE plugin_mcp_approvals SET status='expired',updated_at=? WHERE id=?",
                    (_now().isoformat(), approval_id),
                )
                raise PluginMcpApprovalError("plugin MCP approval expired")
            if status == "pending":
                raise PluginMcpApprovalError("plugin MCP approval is not approved")
            if status == "consumed":
                raise PluginMcpApprovalError("plugin MCP approval was already consumed")
            if status != "approved":
                raise PluginMcpApprovalError(f"plugin MCP approval is {status}")
            expected = (
                str(row["plugin_id"]),
                str(row["connector"]),
                str(row["tool_name"]),
                str(row["arguments_hash"]),
            )
            actual = (
                operation.plugin_id,
                operation.connector,
                operation.tool_name,
                operation.arguments_hash,
            )
            if expected != actual:
                raise PluginMcpApprovalError("plugin MCP approval does not match requested operation")
            connection.execute(
                "UPDATE plugin_mcp_approvals SET status='consumed',updated_at=? WHERE id=?",
                (_now().isoformat(), approval_id),
            )
            return self.get(approval_id, connection=connection)

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM plugin_mcp_approvals"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status=?"
            params = (status,)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            return [self._public(row) for row in connection.execute(query, params).fetchall()]

    def get(
        self,
        approval_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        if connection is not None:
            row = connection.execute(
                "SELECT * FROM plugin_mcp_approvals WHERE id=?", (approval_id,)
            ).fetchone()
            if row is None:
                raise PluginMcpApprovalError("plugin MCP approval was not found")
            return self._public(row)
        with self._connect() as active:
            return self.get(approval_id, connection=active)

    def _transition(self, approval_id: str, *, expected: str, target: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM plugin_mcp_approvals WHERE id=?", (approval_id,)
            ).fetchone()
            if row is None:
                raise PluginMcpApprovalError("plugin MCP approval was not found")
            if str(row["status"]) != expected:
                raise PluginMcpApprovalError(
                    f"plugin MCP approval cannot move from {row['status']} to {target}"
                )
            if datetime.fromisoformat(str(row["expires_at"])).astimezone(UTC) <= _now():
                connection.execute(
                    "UPDATE plugin_mcp_approvals SET status='expired',updated_at=? WHERE id=?",
                    (_now().isoformat(), approval_id),
                )
                raise PluginMcpApprovalError("plugin MCP approval expired")
            connection.execute(
                "UPDATE plugin_mcp_approvals SET status=?,updated_at=? WHERE id=?",
                (target, _now().isoformat(), approval_id),
            )
            return self.get(approval_id, connection=connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "plugin_id": str(row["plugin_id"]),
            "connector": str(row["connector"]),
            "tool_name": str(row["tool_name"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "expires_at": str(row["expires_at"]),
            "updated_at": str(row["updated_at"]),
        }


@lru_cache(maxsize=1)
def get_plugin_mcp_approval_store() -> PluginMcpApprovalStore:
    return PluginMcpApprovalStore(REPO_ROOT / "data" / "memory" / "plugin-mcp-approvals.db")
