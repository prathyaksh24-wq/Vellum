from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.coding.workspace import WorkspaceSnapshot


DEFAULT_MAX_CHECKPOINTS_PER_SESSION = 50


@dataclass(frozen=True)
class CodingCheckpoint:
    id: str
    session_id: str
    turn_id: str
    status: str
    before: WorkspaceSnapshot
    after: WorkspaceSnapshot | None
    created_at: str
    finalized_at: str | None = None

    def payload(self, *, include_patch: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "before": snapshot_payload(self.before, include_patch=include_patch),
            "after": snapshot_payload(self.after, include_patch=include_patch) if self.after else None,
            "created_at": self.created_at,
            "finalized_at": self.finalized_at,
        }


def snapshot_payload(snapshot: WorkspaceSnapshot, *, include_patch: bool) -> dict[str, Any]:
    payload = snapshot.metadata()
    if include_patch:
        payload["patch"] = snapshot.patch
    else:
        payload["patch_bytes"] = len(snapshot.patch.encode("utf-8"))
    return payload


def snapshot_from_payload(payload: dict[str, Any]) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        captured_at=str(payload.get("captured_at") or ""),
        git_head=str(payload.get("git_head") or ""),
        snapshot_commit=str(payload.get("snapshot_commit") or ""),
        changed_files=tuple(str(value) for value in payload.get("changed_files") or ()),
        patch=str(payload.get("patch") or ""),
        files_truncated=bool(payload.get("files_truncated")),
        patch_truncated=bool(payload.get("patch_truncated")),
        capture_error=str(payload.get("capture_error") or ""),
    )
