from __future__ import annotations

from pathlib import Path
import os
from typing import Any

from agent.skills.authoring import build_learn_prompt
from agent.skills.bundles import SkillBundleStore
from agent.skills.curator import SkillCurator
from agent.skills.hub import SkillHub
from agent.skills.manager import SkillManager
from agent.skills.mutation import SkillMutationCoordinator
from agent.skills.migration import JsonSkillMigrator
from agent.skills.parser import SkillPackageError, SkillPackageParser
from agent.skills.registry import SkillRegistry
from agent.skills.suggestions import BlueprintSuggestionStore
from agent.skills.usage import SkillUsageStore
from agent.skills.configuration import SkillConfigStore
from agent.skills.usage_intelligence import SkillUsageIntelligence
from agent.skills.hub import HubLockFile


class SkillSurfaceService:
    def __init__(self, root: str | Path, *, logs_root: str | Path, sources: list):
        self.root = Path(root)
        config = SkillConfigStore(self.root / "config.yaml")
        external_dirs = [Path(os.path.expandvars(os.path.expanduser(str(path)))) for path in config.get_option("external_dirs", []) or []]
        self.registry = SkillRegistry(local_root=self.root / "packages", external_dirs=external_dirs)
        self.manager = SkillManager(self.root)
        self.mutations = SkillMutationCoordinator(self.root)
        self.migrator = JsonSkillMigrator(self.root)
        self.usage = SkillUsageStore(self.root)
        self.usage_intelligence = SkillUsageIntelligence(self.root)
        self.parser = SkillPackageParser()
        self.bundles = SkillBundleStore(self.root, self.registry)
        self.hub = SkillHub(self.root, sources=sources)
        self.curator = SkillCurator(self.root, logs_root=logs_root)
        self.suggestions = BlueprintSuggestionStore(self.root)

    def catalog(self) -> dict[str, Any]:
        active = [self._card(self.registry.view(entry.name), "active") for entry in self.registry.list_skills()]
        proposed = [self._card(package, "proposed") for package in self._packages(self.root / "proposed", "proposed")]
        retired = [self._card(package, "retired") for package in self._packages(self.root / "retired", "retired")]
        archived = [self._card(package, "archived") for package in self._packages(self.root / ".archive", "archived")]
        return {
            "mock": False,
            "skills": {
                "proposed": sorted(proposed, key=lambda item: item["id"]),
                "active": sorted(active, key=lambda item: item["id"]),
                "retired": sorted(retired, key=lambda item: item["id"]),
                "archived": sorted(archived, key=lambda item: item["id"]),
            },
            "bundles": self.bundles.list(),
            "hub_installed": self.hub.list_installed(),
            "suggestions": self.suggestions.list(),
            "curator": self.curator.status(),
            "pending_writes": self.mutations.list_pending(),
            "write_approval": self.mutations.write_approval,
            "external_diagnostics": self.registry.diagnostics(),
        }

    def detail(self, name: str, *, path: str = "") -> dict[str, Any]:
        try:
            package = self.registry.view(name)
        except KeyError:
            lifecycle = None
            for base in (self.root / "proposed", self.root / "retired", self.root / ".archive"):
                lifecycle = self.manager._locate(base, name)
                if lifecycle is not None:
                    break
            if lifecycle is None:
                raise
            package = self.parser.parse(lifecycle)
        if path:
            return {"name": name, "path": path, "content": self.parser.read_support_file(package.root, path)}
        provenance = HubLockFile(self.root).get(name) or {}
        support_files = sorted(
            path.relative_to(package.root).as_posix()
            for path in package.root.rglob("*")
            if path.is_file() and not path.is_symlink() and path.name != "SKILL.md"
        )
        return {
            "name": name,
            "description": package.metadata.description,
            "metadata": package.metadata.model_dump(mode="json", exclude_none=True),
            "content": package.body,
            "skill_md": package.skill_file.read_text(encoding="utf-8"),
            "usage": self.usage.get(name),
            "origin": self._origin(package, self.usage.get(name)),
            "usage_intelligence": self.usage_intelligence.aggregate(name),
            "recent_usage": self.usage_intelligence.recent(name),
            "provenance": {
                "source": provenance.get("source") or ("external" if package.is_external else "local"),
                "identifier": provenance.get("identifier"),
                "repository_url": provenance.get("repository_url"),
                "source_ref": provenance.get("source_ref"),
                "source_path": provenance.get("source_path"),
                "content_hash": provenance.get("content_hash"),
                "trust_level": provenance.get("trust_level") or ("local" if not package.is_external else "external"),
                "scan_verdict": provenance.get("scan_verdict"),
            },
            "support_files": support_files,
        }

    def action(self, action: str, *, name: str = "", confirm: bool = False, **payload) -> dict[str, Any]:
        normalized = action.strip().casefold().replace("-", "_")
        if normalized == "pending_diff":
            return self.mutations.diff(name)
        if normalized == "pending_approve":
            return self.mutations.approve(name)
        if normalized == "pending_reject":
            return self.mutations.reject(name)
        if normalized == "approve_all":
            return self.mutations.approve_all()
        if normalized == "reject_all":
            return self.mutations.reject_all()
        if normalized == "approval_on":
            return self.mutations.set_write_approval(True)
        if normalized == "approval_off":
            return self.mutations.set_write_approval(False)
        if normalized == "approve":
            return self.mutations.submit("approve_proposed", name=name, origin="foreground")
        if normalized in {"retire", "archive", "restore", "delete"}:
            return self.mutations.submit(normalized, name=name, origin="foreground", **payload)
        if normalized == "create":
            return self.mutations.submit(
                "create",
                skill_md=str(payload.get("skill_md") or ""),
                category=str(payload.get("category") or "uncategorized"),
                origin="foreground",
            )
        if normalized == "patch":
            return self.mutations.submit(
                "patch",
                name=name,
                old_text=str(payload.get("old_text") or ""),
                new_text=str(payload.get("new_text") or ""),
                origin="foreground",
            )
        raise ValueError(f"unsupported skill action: {normalized}")

    def slash(self, command: str) -> dict[str, Any]:
        clean = command.strip()
        if not clean.startswith("/"):
            return {"handled": False, "expanded": clean}
        if clean.casefold().startswith("/learn"):
            source = clean[6:].strip()
            return {"handled": False, "expanded": build_learn_prompt(source)}
        parts = clean.split()
        head = parts[0][1:]
        args = parts[1:]
        if head.casefold() == "skills":
            if not args:
                catalog = self.catalog()["skills"]
                lines = ["Installed skills:"]
                for state in ("proposed", "active", "retired", "archived"):
                    names = ", ".join(item["id"] for item in catalog[state]) or "none"
                    lines.append(f"- {state}: {names}")
                lines.append(f"- pending writes: {len(self.mutations.list_pending())}")
                return {"handled": True, "answer": "\n".join(lines)}
            action = args[0].casefold()
            if action == "pending":
                records = self.mutations.list_pending()
                answer = "\n".join(f"- {item['id']}: {item['gist']}" for item in records) or "No pending skill mutations."
                return {"handled": True, "answer": answer}
            if action == "migrate" and len(args) >= 2 and args[1] == "--dry-run":
                return {"handled": True, "answer": str(self.migrator.dry_run().to_dict())}
            if action == "migrate" and len(args) >= 3 and args[1] == "--rollback":
                return {"handled": True, "answer": str(self.migrator.rollback(args[2]))}
            if action == "diff" and len(args) == 2:
                return {"handled": True, "answer": self.mutations.diff(args[1])["diff"] or "No textual changes."}
            if action in {"approve", "reject"} and len(args) == 2:
                result = getattr(self.mutations, f"{action}_all")() if args[1].casefold() == "all" else getattr(self.mutations, action)(args[1])
                return {"handled": True, "answer": str(result)}
            if action == "approval" and len(args) == 2 and args[1].casefold() in {"on", "off"}:
                result = self.mutations.set_write_approval(args[1].casefold() == "on")
                return {"handled": True, "answer": str(result)}
            if action in {"retire", "archive", "restore", "delete"} and len(args) > 1:
                result = self.action(action, name=args[1])
                return {"handled": True, "answer": f"pending: {result['id']} — {result['gist']}"}
            return {
                "handled": True,
                "answer": "Usage: /skills [pending|diff <id>|approve <id|all>|reject <id|all>|approval on|off|archive|restore|delete]",
            }
        if head.casefold() == "curator":
            if not args or args[0].casefold() == "status":
                return {"handled": True, "answer": str(self.curator.status())}
            return {"handled": True, "answer": "Use the skill_curator tool for this curator operation."}
        try:
            self.registry.view(head)
        except (KeyError, SkillPackageError):
            try:
                self.bundles.show(head)
            except Exception:
                return {"handled": False, "expanded": clean}
            request = " ".join(args)
            return {
                "handled": False,
                "expanded": f"Load {head} with skill_bundles, then follow the bundle for this request: {request}",
            }
        request = " ".join(args)
        return {
            "handled": False,
            "expanded": f"Load {head} with skill_view, then follow it for this request: {request}",
        }

    def _packages(self, root: Path, state: str) -> list:
        if not root.exists():
            return []
        packages = []
        for skill_file in sorted(root.rglob("SKILL.md")):
            try:
                packages.append(self.parser.parse(skill_file.parent, state=state, source_root=root))
            except SkillPackageError:
                continue
        return packages

    def _card(self, package, state: str) -> dict[str, Any]:
        name = package.metadata.name
        usage = self.usage.get(name)
        vellum = package.metadata.metadata.vellum
        trigger_values = vellum.trigger or package.metadata.metadata.hermes.tags
        return {
            "id": name,
            "name": name,
            "description": package.metadata.description,
            "trigger": " · ".join(trigger_values) if trigger_values else "manual",
            "note": package.metadata.description,
            "uses": int(usage.get("use_count") or 0),
            "last": usage.get("last_used_at") or "never",
            "state": state,
            "category": package.metadata.metadata.hermes.category or package.root.parent.name,
            "origin": self._origin(package, usage),
            "pinned": bool(usage.get("pinned")),
            "created_by": usage.get("created_by"),
            "is_external": bool(package.is_external),
        }

    def _origin(self, package, usage: dict[str, Any]) -> str:
        if package.is_external:
            return "external"
        if HubLockFile(self.root).get(package.metadata.name) is not None:
            return "hub_installed"
        explicit = usage.get("origin")
        if explicit in {"builtin", "user_learned", "agent_learned", "hub_installed", "external"}:
            return explicit
        if usage.get("created_by") == "agent":
            return "agent_learned"
        if "migrated" in package.metadata.metadata.hermes.tags:
            return "builtin"
        return "user_learned"
