from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.skills.authoring import build_learn_prompt
from agent.skills.bundles import SkillBundleStore
from agent.skills.curator import SkillCurator
from agent.skills.hub import SkillHub
from agent.skills.manager import SkillManager
from agent.skills.parser import SkillPackageError, SkillPackageParser
from agent.skills.registry import SkillRegistry
from agent.skills.suggestions import BlueprintSuggestionStore
from agent.skills.usage import SkillUsageStore


class SkillSurfaceService:
    def __init__(self, root: str | Path, *, logs_root: str | Path, sources: list):
        self.root = Path(root)
        self.registry = SkillRegistry(local_root=self.root / "packages")
        self.manager = SkillManager(self.root)
        self.usage = SkillUsageStore(self.root)
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
        }

    def detail(self, name: str, *, path: str = "") -> dict[str, Any]:
        if path:
            return {"name": name, "path": path, "content": self.registry.view_file(name, path)}
        package = self.registry.view(name)
        return {
            "name": name,
            "description": package.metadata.description,
            "metadata": package.metadata.model_dump(mode="json", exclude_none=True),
            "content": package.body,
            "usage": self.usage.get(name),
        }

    def action(self, action: str, *, name: str = "", confirm: bool = False, **payload) -> dict[str, Any]:
        normalized = action.strip().casefold().replace("-", "_")
        if normalized == "approve":
            return self.manager.approve(name, confirm=confirm)
        if normalized == "retire":
            return self.manager.retire(name, confirm=confirm)
        if normalized == "archive":
            return self.manager.archive(name, confirm=confirm)
        if normalized == "restore":
            return self.manager.restore(name, confirm=confirm)
        if normalized == "delete":
            return self.manager.delete(name, confirm=confirm)
        if normalized == "create":
            return self.manager.create(
                str(payload.get("skill_md") or ""),
                category=str(payload.get("category") or "uncategorized"),
                origin="foreground",
                confirm=confirm,
            )
        if normalized == "patch":
            return self.manager.patch(
                name,
                str(payload.get("old_text") or ""),
                str(payload.get("new_text") or ""),
                confirm=confirm,
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
                return {"handled": True, "answer": "\n".join(lines)}
            action = args[0].casefold()
            if action in {"approve", "retire", "archive", "restore", "delete"} and len(args) > 1:
                result = self.action(action, name=args[1], confirm=True)
                return {"handled": True, "answer": f"{result['action']}: {result['name']}"}
            return {"handled": True, "answer": "Usage: /skills [approve|retire|archive|restore|delete] <name>"}
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
            "pinned": bool(usage.get("pinned")),
            "created_by": usage.get("created_by"),
        }
