from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.skills import SkillCatalog
from agent.skills.surface import SkillSurfaceService


def main() -> int:
    parser = argparse.ArgumentParser(description="Vellum skill-system operational diagnostics.")
    parser.add_argument("command", choices=("health", "rebuild", "duplicates", "sources"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / ".skills")
    args = parser.parse_args()
    root = args.root.resolve()
    catalog = SkillCatalog(root)
    if args.command == "rebuild":
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
