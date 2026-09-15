"""App Action adapter over Vellum's existing observability owners."""

from __future__ import annotations

from typing import Any, Callable

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.tools.registry import CapabilityAccess


OBSERVABILITY_OPEN_ACTION_ID = "observability.open"
OBSERVABILITY_STATUS_ACTION_ID = "observability.status"
OBSERVABILITY_STREAM_SET_ACTION_ID = "observability.stream.set"
OBSERVABILITY_REFRESH_ACTION_ID = "observability.refresh"

OBSERVABILITY_ACTION_IDS = frozenset({
    OBSERVABILITY_OPEN_ACTION_ID,
    OBSERVABILITY_STATUS_ACTION_ID,
    OBSERVABILITY_STREAM_SET_ACTION_ID,
    OBSERVABILITY_REFRESH_ACTION_ID,
})

_PERIODS = frozenset({"today", "7d", "30d", "month", "all"})
_USAGE_TOTAL_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_usd",
    "calls",
    "sessions",
    "state",
)
_USAGE_MODEL_FIELDS = ("model", "input_tokens", "output_tokens", "cost_usd", "calls")
_USAGE_DAILY_FIELDS = ("day", "input_tokens", "output_tokens", "cost_usd")
_USAGE_RECENT_FIELDS = (
    "id",
    "ts",
    "thread_id",
    "model",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "source",
)
_RUN_FIELDS = (
    "response_id",
    "thread_id",
    "status",
    "started_at",
    "completed_at",
    "event_count",
    "tool_count",
    "source_count",
)


class ObservabilityActionError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


class ObservabilityActionService:
    """Translate semantic actions into reads from the native observability view."""

    def __init__(self, snapshot_provider: Callable[[str], dict[str, Any]]) -> None:
        self._snapshot_provider = snapshot_provider

    def execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        _context: AppActionContext,
    ) -> dict[str, Any]:
        if action_id == OBSERVABILITY_OPEN_ACTION_ID:
            return {
                "changed": True,
                "navigation": {"view": "ledger"},
                "_target_kind": "ui_surface",
                "_target_id": "observability",
                "_message": "Observability opened.",
            }
        if action_id == OBSERVABILITY_STREAM_SET_ACTION_ID:
            return self._set_stream(arguments)
        if action_id in {OBSERVABILITY_STATUS_ACTION_ID, OBSERVABILITY_REFRESH_ACTION_ID}:
            return self._read_snapshot(action_id, arguments)
        raise ObservabilityActionError(
            "ACTION_UNAVAILABLE",
            f"{action_id} is unavailable.",
            unavailable=True,
        )

    def _set_stream(self, arguments: dict[str, Any]) -> dict[str, Any]:
        enabled = arguments.get("enabled")
        if not isinstance(enabled, bool):
            raise ObservabilityActionError(
                "INVALID_ACTION_ARGUMENTS",
                "Observability streaming enabled must be true or false.",
            )
        reconnect = arguments.get("reconnect", False)
        if not isinstance(reconnect, bool):
            raise ObservabilityActionError(
                "INVALID_ACTION_ARGUMENTS",
                "Observability reconnect must be true or false.",
            )
        label = "resumed" if enabled else "paused"
        return {
            "changed": True,
            "observability_control_patch": {
                "version": 1,
                "streaming": enabled,
                "reconnect": reconnect,
            },
            "_target_kind": "observability_stream",
            "_target_id": "local-browser",
            "_message": f"Observability {label}.",
        }

    def _read_snapshot(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        period = str(arguments.get("period") or "7d").strip().casefold()
        if period not in _PERIODS:
            raise ObservabilityActionError(
                "INVALID_ACTION_ARGUMENTS",
                "Observability period must be today, 7d, 30d, month, or all.",
            )
        try:
            raw_snapshot = self._snapshot_provider(period)
        except OSError as exc:
            raise ObservabilityActionError(
                "OBSERVABILITY_UNAVAILABLE",
                "Observability collectors are unavailable.",
                unavailable=True,
            ) from exc
        except Exception as exc:
            raise ObservabilityActionError(
                "OBSERVABILITY_REFRESH_FAILED",
                "Observability could not be refreshed.",
            ) from exc
        snapshot = content_free_snapshot(raw_snapshot)
        if action_id == OBSERVABILITY_STATUS_ACTION_ID:
            runs = snapshot.get("runs") or {}
            usage = snapshot.get("usage") or {}
            active = int(runs.get("active") or 0)
            calls = int(usage.get("calls") or 0)
            state = str((snapshot.get("freshness") or {}).get("state") or "ready")
            return {
                "changed": False,
                "status": {
                    "collector": state,
                    "active_runs": active,
                    "total_runs": int(runs.get("total") or 0),
                    "failed_runs": int(runs.get("failed") or 0),
                    "usage_state": str(usage.get("state") or "empty"),
                    "calls": calls,
                    "total_tokens": int(usage.get("total_tokens") or 0),
                    "generated_at": snapshot.get("generated_at"),
                    "period": snapshot.get("period"),
                },
                "_target_kind": "observability_status",
                "_target_id": "native",
                "_message": (
                    f"Observability is {state} with {active} active run"
                    f"{'s' if active != 1 else ''} and {calls} recorded call"
                    f"{'s' if calls != 1 else ''} over {snapshot.get('period') or period}."
                ),
            }
        return {
            "changed": False,
            "observability_snapshot": snapshot,
            "_target_kind": "observability_snapshot",
            "_target_id": period,
            "_message": "Observability refreshed.",
        }


def _pick(source: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {field: source[field] for field in fields if field in source}


def _pick_rows(source: Any, fields: tuple[str, ...], *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(source, list):
        return []
    return [_pick(row, fields) for row in source[:limit] if isinstance(row, dict)]


def content_free_snapshot(raw_snapshot: Any) -> dict[str, Any]:
    """Allowlist operational fields before placing a snapshot in an Action Receipt."""

    raw = raw_snapshot if isinstance(raw_snapshot, dict) else {}
    raw_usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    raw_runs = raw.get("runs") if isinstance(raw.get("runs"), dict) else {}
    usage = _pick(raw_usage, _USAGE_TOTAL_FIELDS)
    usage["models"] = _pick_rows(raw_usage.get("models"), _USAGE_MODEL_FIELDS, limit=50)
    usage["daily"] = _pick_rows(raw_usage.get("daily"), _USAGE_DAILY_FIELDS, limit=400)
    usage["recent"] = _pick_rows(raw_usage.get("recent"), _USAGE_RECENT_FIELDS, limit=20)
    runs = _pick(raw_runs, ("total", "completed", "failed", "active", "success_rate"))
    active_run = raw_runs.get("active_run")
    runs["active_run"] = _pick(active_run, _RUN_FIELDS) if isinstance(active_run, dict) else None
    return {
        "schema_version": raw.get("schema_version", 1),
        "source": raw.get("source", "vellum-native"),
        "generated_at": raw.get("generated_at"),
        "period": raw.get("period"),
        "freshness": _pick(raw.get("freshness"), ("state", "updated_at")),
        "usage": usage,
        "runs": runs,
        "recent_runs": _pick_rows(raw.get("recent_runs"), _RUN_FIELDS, limit=12),
    }


def observability_action_definitions() -> list[AppActionDefinition]:
    result_schema = {"type": "object", "required": ["changed"]}
    period_schema = {"period": {"enum": ["today", "7d", "30d", "month", "all"]}}
    return [
        AppActionDefinition(
            id=OBSERVABILITY_OPEN_ACTION_ID,
            version="1",
            owner="observability",
            title="Open observability",
            description="Open Vellum's native observability surface.",
            scope="session",
            access_class=CapabilityAccess.READ.value,
            confirmation_rule="none",
            executor_location="client",
            supports_undo=False,
            idempotent=True,
            argument_schema={"type": "object", "additionalProperties": False},
            result_schema=result_schema,
            ui_reference="observability",
            audit_label="observability.open",
        ),
        AppActionDefinition(
            id=OBSERVABILITY_STATUS_ACTION_ID,
            version="1",
            owner="observability",
            title="Get observability status",
            description="Read current collector, run, and usage status without logged content.",
            scope="application",
            access_class=CapabilityAccess.READ.value,
            confirmation_rule="none",
            executor_location="server",
            supports_undo=False,
            idempotent=True,
            argument_schema={"type": "object", "properties": period_schema, "additionalProperties": False},
            result_schema=result_schema,
            ui_reference="observability",
            audit_label="observability.status",
        ),
        AppActionDefinition(
            id=OBSERVABILITY_STREAM_SET_ACTION_ID,
            version="1",
            owner="observability",
            title="Set observability live stream",
            description="Pause, resume, or reconnect this browser's live observability feed.",
            scope="session",
            access_class=CapabilityAccess.WRITE.value,
            confirmation_rule="none",
            executor_location="client",
            supports_undo=False,
            idempotent=True,
            argument_schema={
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}, "reconnect": {"type": "boolean"}},
                "required": ["enabled"],
                "additionalProperties": False,
            },
            result_schema=result_schema,
            ui_reference="observability",
            audit_label="observability.stream.set",
        ),
        AppActionDefinition(
            id=OBSERVABILITY_REFRESH_ACTION_ID,
            version="1",
            owner="observability",
            title="Refresh observability",
            description="Read a fresh operational snapshot from Vellum's native stores.",
            scope="application",
            access_class=CapabilityAccess.READ.value,
            confirmation_rule="none",
            executor_location="server",
            supports_undo=False,
            idempotent=True,
            argument_schema={"type": "object", "properties": period_schema, "additionalProperties": False},
            result_schema=result_schema,
            ui_reference="observability",
            audit_label="observability.refresh",
        ),
    ]
