from __future__ import annotations

from datetime import datetime, timezone
import json
from threading import Thread

from langchain_core.tools import tool

from agent.skills import SkillCurator
from agent.skills.runtime import SKILLS_PATH


_CURATOR: SkillCurator | None = None


def _curator() -> SkillCurator:
    global _CURATOR
    if _CURATOR is None:
        _CURATOR = SkillCurator(SKILLS_PATH, logs_root=SKILLS_PATH.parent / "data" / "logs" / "curator")
    return _CURATOR


def curator_tick(*, idle_hours: float, now: datetime | None = None) -> dict:
    return _curator().run(now=now or datetime.now(timezone.utc), idle_hours=idle_hours)


@tool
def skill_curator(
    action: str,
    name: str = "",
    backup_id: str = "",
    reason: str = "manual",
    days: int = 90,
    idle_hours: float = 0,
    force: bool = False,
    dry_run: bool = False,
    consolidate: bool | None = None,
    confirm: bool = False,
) -> str:
    """Inspect and operate Vellum's recoverable skill curator."""
    normalized = action.strip().casefold().replace("-", "_")
    curator = _curator()
    try:
        if normalized == "status":
            result = curator.status()
        elif normalized == "run":
            result = curator.run(
                idle_hours=idle_hours,
                force=force,
                dry_run=dry_run,
                consolidate=consolidate,
            )
        elif normalized == "run_background":
            Thread(
                target=curator.run,
                kwargs={"idle_hours": idle_hours, "force": force, "dry_run": dry_run, "consolidate": consolidate},
                daemon=True,
            ).start()
            result = {"ok": True, "status": "started"}
        elif normalized == "backup":
            result = curator.backup(reason)
        elif normalized == "rollback":
            if not confirm:
                raise ValueError("curator rollback requires confirmation")
            result = curator.rollback(backup_id or None)
        elif normalized == "pause":
            curator.pause()
            result = {"ok": True, "paused": True}
        elif normalized == "resume":
            curator.resume()
            result = {"ok": True, "paused": False}
        elif normalized == "pin":
            curator.pin(name)
            result = {"ok": True, "name": name, "pinned": True}
        elif normalized == "unpin":
            curator.unpin(name)
            result = {"ok": True, "name": name, "pinned": False}
        elif normalized == "archive":
            if not confirm:
                raise ValueError("curator archive requires confirmation")
            result = curator.archive(name)
        elif normalized == "restore":
            if not confirm:
                raise ValueError("curator restore requires confirmation")
            result = curator.restore(name)
        elif normalized == "list_archived":
            result = {"ok": True, "skills": curator.list_archived()}
        elif normalized == "prune":
            result = curator.prune(days=days, dry_run=dry_run)
        else:
            result = {"ok": False, "error": f"Unsupported curator action: {normalized}"}
    except (OSError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)
