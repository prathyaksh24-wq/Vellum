from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from typing import Any, Callable

from agent.skills.hub import HubLockFile
from agent.skills.manager import SkillManager
from agent.skills.usage import SkillUsageStore


@dataclass
class CuratorConfig:
    enabled: bool = True
    interval_hours: float = 168
    min_idle_hours: float = 2
    stale_after_days: int = 30
    archive_after_days: int = 90
    consolidate: bool = False
    prune_builtins: bool = True
    backup_enabled: bool = True
    backup_keep: int = 5


class CuratorBackupStore:
    def __init__(self, root: str | Path, *, keep: int = 5):
        self.root = Path(root)
        self.directory = self.root / ".curator_backups"
        self.keep = max(1, keep)

    def create(self, reason: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        identifier = now.strftime("%Y%m%dT%H%M%S.%fZ")
        target = self.directory / identifier
        target.mkdir(parents=True, exist_ok=False)
        archive = target / "skills.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            if self.root.exists():
                for child in sorted(self.root.iterdir()):
                    if child.name == ".curator_backups":
                        continue
                    handle.add(child, arcname=child.name, recursive=True)
        manifest = {
            "id": identifier,
            "reason": reason,
            "created_at": now.isoformat(),
            "size_bytes": archive.stat().st_size,
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        self._prune()
        return manifest

    def list(self) -> list[dict[str, Any]]:
        if not self.directory.exists():
            return []
        manifests = []
        for path in sorted(self.directory.glob("*/manifest.json")):
            try:
                manifests.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return manifests

    def rollback(self, identifier: str | None = None) -> dict[str, Any]:
        backups = self.list()
        if not backups:
            raise ValueError("no curator backups available")
        target_id = identifier or backups[-1]["id"]
        archive = self.directory / target_id / "skills.tar.gz"
        if not archive.is_file():
            raise ValueError(f"curator backup not found: {target_id}")
        self.create(f"pre-rollback to {target_id}")
        staging = Path(tempfile.mkdtemp(prefix="curator-restore-", dir=self.root.parent))
        try:
            with tarfile.open(archive, "r:gz") as handle:
                members = handle.getmembers()
                for member in members:
                    relative = PurePosixPath(member.name)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("unsafe curator backup member")
                handle.extractall(staging, members=members, filter="data")
            self.root.mkdir(parents=True, exist_ok=True)
            for child in list(self.root.iterdir()):
                if child.name != ".curator_backups":
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
            for child in staging.iterdir():
                os.replace(child, self.root / child.name)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return {"ok": True, "restored": target_id}

    def _prune(self) -> None:
        if not self.directory.exists():
            return
        backups = sorted(path for path in self.directory.iterdir() if path.is_dir())
        for path in backups[: max(0, len(backups) - self.keep)]:
            shutil.rmtree(path, ignore_errors=True)


class SkillCurator:
    def __init__(
        self,
        root: str | Path,
        *,
        logs_root: str | Path,
        config: CuratorConfig | None = None,
        protected: set[str] | None = None,
        reviewer: Callable | None = None,
    ):
        self.root = Path(root)
        self.logs_root = Path(logs_root)
        self.config = config or CuratorConfig()
        self.protected = protected or {"skill-skill-creator-v1", "plan"}
        self.reviewer = reviewer
        self.usage = SkillUsageStore(self.root)
        self.manager = SkillManager(self.root)
        self.backups = CuratorBackupStore(self.root, keep=self.config.backup_keep)
        self.state_path = self.root / ".curator_state.json"

    def run(
        self,
        *,
        now: datetime | None = None,
        idle_hours: float = 0,
        force: bool = False,
        dry_run: bool = False,
        consolidate: bool | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        state = self._state()
        if not self.config.enabled:
            return {"status": "disabled"}
        if state.get("paused"):
            return {"status": "paused"}
        if not state.get("last_run_at"):
            state["last_run_at"] = current.isoformat()
            self._write_state(state)
            return {"status": "deferred_first_run", "last_run_at": state["last_run_at"]}
        if not force:
            last_run = self._parse_time(state["last_run_at"])
            elapsed_hours = (current - last_run).total_seconds() / 3600
            if elapsed_hours < self.config.interval_hours:
                return {"status": "interval_not_elapsed"}
            if idle_hours < self.config.min_idle_hours:
                return {"status": "not_idle"}

        decisions = self._decisions(current)
        run_id = current.strftime("%Y%m%d-%H%M%S") + ("-dry" if dry_run else "")
        result = {
            "status": "dry_run" if dry_run else "completed",
            "run_id": run_id,
            "stale": decisions["stale"],
            "archived": decisions["archived"],
            "kept": decisions["kept"],
            "consolidated": [],
        }
        if not dry_run:
            if self.config.backup_enabled:
                self.backups.create(f"curator run {run_id}")
            for name in decisions["stale"]:
                self.usage.set_state(name, "stale")
            for name in decisions["archived"]:
                self.manager.archive(name, confirm=True)
            should_consolidate = self.config.consolidate if consolidate is None else consolidate
            if should_consolidate and self.reviewer and decisions["review"]:
                review_result = self.reviewer(decisions["review"], max_iterations=8)
                result["consolidated"] = list(review_result or [])
            state["last_run_at"] = current.isoformat()
            self._write_state(state)
        self._write_report(result)
        return result

    def status(self) -> dict[str, Any]:
        state = self._state()
        usage = self.usage.all()
        return {
            "enabled": self.config.enabled,
            "paused": bool(state.get("paused")),
            "last_run_at": state.get("last_run_at"),
            "counts": {
                "active": sum(1 for item in usage.values() if item.get("state") == "active"),
                "stale": sum(1 for item in usage.values() if item.get("state") == "stale"),
                "archived": sum(1 for item in usage.values() if item.get("state") == "archived"),
                "pinned": sum(1 for item in usage.values() if item.get("pinned")),
            },
        }

    def pause(self) -> None:
        state = self._state()
        state["paused"] = True
        self._write_state(state)

    def resume(self) -> None:
        state = self._state()
        state["paused"] = False
        self._write_state(state)

    def pin(self, name: str) -> None:
        if not self._is_agent_created(name):
            raise ValueError(f"only agent-created skills can be pinned: {name}")
        self.usage.pin(name)

    def unpin(self, name: str) -> None:
        if not self._is_agent_created(name):
            raise ValueError(f"only agent-created skills can be unpinned: {name}")
        self.usage.unpin(name)

    def backup(self, reason: str = "manual") -> dict[str, Any]:
        if not self.config.backup_enabled:
            raise ValueError("curator backups are disabled")
        return self.backups.create(reason)

    def rollback(self, identifier: str | None = None) -> dict[str, Any]:
        if not self.config.backup_enabled:
            raise ValueError("curator backups are disabled")
        return self.backups.rollback(identifier)

    def archive(self, name: str) -> dict[str, Any]:
        if not self._is_agent_created(name):
            raise ValueError(f"only agent-created skills can be curated: {name}")
        return self.manager.archive(name, confirm=True)

    def restore(self, name: str) -> dict[str, Any]:
        return self.manager.restore(name, confirm=True)

    def list_archived(self) -> list[str]:
        root = self.root / ".archive"
        if not root.exists():
            return []
        return sorted(path.parent.name for path in root.rglob("SKILL.md"))

    def prune(self, *, days: int = 90, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        names = []
        for name, record in self.usage.all().items():
            if not self._is_agent_created(name) or record.get("pinned") or record.get("state") == "archived":
                continue
            timestamp = record.get("last_used_at") or record.get("last_viewed_at") or record.get("created_at")
            if timestamp and (current - self._parse_time(timestamp)).total_seconds() / 86400 >= days:
                names.append(name)
        if not dry_run:
            if names and self.config.backup_enabled:
                self.backups.create(f"curator prune {days} days")
            for name in names:
                self.manager.archive(name, confirm=True)
        return {"ok": True, "archived": sorted(names), "dry_run": dry_run}

    def _is_agent_created(self, name: str) -> bool:
        if HubLockFile(self.root).get(name) is not None or name in self._bundled_names():
            return False
        return self.usage.get(name).get("created_by") == "agent"

    def _decisions(self, now: datetime) -> dict[str, list]:
        usage = self.usage.all()
        hub_names = set(HubLockFile(self.root).all())
        bundled = self._bundled_names()
        stale: list[str] = []
        archived: list[str] = []
        kept: list[str] = []
        review: list[dict[str, Any]] = []
        for name, record in sorted(usage.items()):
            is_builtin = name in bundled
            eligible = record.get("created_by") == "agent" or (self.config.prune_builtins and is_builtin)
            if (
                not eligible
                or name in hub_names
                or name in self.protected
                or record.get("pinned")
                or record.get("state") == "archived"
            ):
                kept.append(name)
                continue
            timestamp = record.get("last_used_at") or record.get("last_viewed_at") or record.get("created_at")
            if not timestamp:
                kept.append(name)
                continue
            age_days = (now - self._parse_time(timestamp)).total_seconds() / 86400
            if age_days >= self.config.archive_after_days:
                archived.append(name)
            elif not is_builtin and age_days >= self.config.stale_after_days:
                stale.append(name)
            else:
                kept.append(name)
            if not is_builtin:
                review.append({"name": name, "age_days": age_days, "state": record.get("state", "active")})
        return {"stale": stale, "archived": archived, "kept": kept, "review": review}

    def _bundled_names(self) -> set[str]:
        path = self.root / ".bundled_manifest"
        if not path.exists():
            return set()
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        return set(loaded) if isinstance(loaded, dict) else set()

    def _write_report(self, result: dict[str, Any]) -> None:
        directory = self.logs_root / result["run_id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "run.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        lines = [
            "# Skill Curator Report",
            "",
            f"Status: {result['status']}",
            f"Stale: {', '.join(result['stale']) or 'none'}",
            f"Archived: {', '.join(result['archived']) or 'none'}",
            f"Consolidated: {', '.join(result['consolidated']) or 'none'}",
        ]
        (directory / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
