from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import re
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.skills import SkillCatalog
from agent.skills.surface import SkillSurfaceService


LEGACY_TOOL_GUIDES = (
    'skill-browser-automation-v1', 'skill-context-mode-mcp-v1',
    'skill-context7-mcp-v1', 'skill-find-skills-v1', 'skill-github-mcp-v1',
    'skill-gitmcp-mcp-v1', 'skill-obsidian-mcp-v1', 'skill-skill-creator-v1',
    'skill-systematic-debugging-v1',
)


def cleanup_legacy_skills(root: Path, *, names=None, apply: bool = False) -> dict:
    """Explicit, recoverable cleanup; profile dependencies always take precedence."""
    from agent.profiles.catalog import AgentCatalog
    from agent.skills.registry import SkillRegistry
    root = root.resolve()
    protected = {name for profile in AgentCatalog(profile_dir=root.parent / 'data' / 'agent_profiles').list()
        for name in profile.skills.allow}
    selected = tuple(dict.fromkeys(LEGACY_TOOL_GUIDES if names is None else names))
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,127}', name) for name in selected):
        raise ValueError('Use normalized skill names, never paths.')
    packages = {p.metadata.name: p for p in SkillRegistry(local_root=root / 'packages').list_packages(include_unavailable=True)}
    plan = [{'name': name, 'status': 'protected_agent_dependency' if name in protected else
        'would_archive' if name in packages else 'not_active'} for name in selected]
    if apply:
        from agent.skills.mutation import SkillMutationCoordinator
        coordinator = SkillMutationCoordinator(root)
        operation_id = uuid.uuid4().hex
        for item in plan:
            if item['status'] != 'would_archive':
                continue
            package = packages[item['name']]
            source = package.root.resolve()
            destination = root / '.archive' / source.parent.name / item['name']
            if not source.is_relative_to(root / 'packages') or not destination.resolve().is_relative_to(root / '.archive'):
                raise ValueError('Cleanup target must remain within the local skill tree.')
            pending = coordinator.submit('archive', name=item['name'], origin='foreground',
                gist='Explicit cleanup of an unbound legacy instruction package.',
                idempotency_key='legacy-cleanup-' + operation_id + '-' + item['name'])
            if pending.get('status') == 'pending':
                coordinator.approve(pending['id'])
            item['status'] = 'archived' if destination.is_dir() and not source.exists() else 'not_archived'
    return {'ok': all(item['status'] != 'not_archived' for item in plan),
        'dry_run': not apply, 'protected_agent_skills': sorted(protected), 'plan': plan}


def main() -> int:
    parser = argparse.ArgumentParser(description="Vellum skill-system operational diagnostics.")
    parser.add_argument("command", choices=("health", "rebuild", "duplicates", "sources", "cleanup"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / ".skills")
    parser.add_argument('--apply', action='store_true', help='Apply the explicit cleanup plan through the mutation coordinator.')
    parser.add_argument('--archive', action='append', help='Cleanup one named package instead of the default legacy-tool-guide list; repeatable.')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command != 'cleanup' and (args.apply or args.archive):
        parser.error('--apply and --archive are only valid with cleanup')
    catalog = SkillCatalog(root) if args.command != 'cleanup' else None
    if args.command == 'cleanup':
        payload = cleanup_legacy_skills(root, names=args.archive, apply=args.apply)
    elif args.command == "rebuild":
        payload = {"ok": True, "reconcile": asdict(catalog.reconcile(embed_semantics=False))}
    elif args.command == "duplicates":
        report = catalog.reconcile(embed_semantics=False)
        reviews = catalog.duplicate_reviews()
        payload = {"ok": not reviews and not report.errors, "reviews": reviews, "errors": list(report.errors)}
    else:
        overview = SkillSurfaceService(root, logs_root=root.parent / "data" / "logs" / "curator", sources=[]).catalog()
        if args.command == "sources":
            installed_sources = sorted({item.get("source", "unknown") for item in overview.get("hub_installed", [])})
            payload = {"ok": True, "configured_hub_sources": installed_sources, "external": overview.get("external_diagnostics", [])}
        else:
            counts = {state: len(rows) for state, rows in overview.get("skills", {}).items()}
            payload = {
                "ok": True,
                "counts": counts,
                "pending": len(overview.get("pending_writes", [])),
                "curator": overview.get("curator", {}),
                "write_approval": overview.get("write_approval", True),
            }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
