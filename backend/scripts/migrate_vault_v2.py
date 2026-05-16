"""One-time migration: Vault → Meta/Projects/Library/Agent.

Dry-run by default; --apply executes."""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agent.memory.templates import load_template


REFERENCE_FOLDERS = ("X", "Youtube", "Books", "Sports", "Claude code", "Codex", "feedback")


class MigrationAborted(Exception):
    pass


@dataclass
class Action:
    kind: str  # "create_dir" | "move" | "write_template" | "rewrite_wikilinks" | "reindex"
    args: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        return f"{self.kind}: {self.args}"


def plan_actions(vault: Path) -> list[Action]:
    actions: list[Action] = []

    for top in ("Meta", "Projects", "Library"):
        if not (vault / top).exists():
            actions.append(Action("create_dir", {"path": str(vault / top)}))

    # Drop Meta templates if Meta/* missing
    if not (vault / "Meta" / "profile.md").exists():
        actions.append(Action("write_template", {"name": "profile", "dest": str(vault / "Meta" / "profile.md")}))
    if not (vault / "Meta" / "goals.md").exists():
        actions.append(Action("write_template", {"name": "goals", "dest": str(vault / "Meta" / "goals.md")}))
    if not (vault / "Meta" / "principles.md").exists():
        actions.append(Action("write_template", {"name": "principles", "dest": str(vault / "Meta" / "principles.md")}))

    for folder in REFERENCE_FOLDERS:
        src = vault / folder
        if src.exists():
            actions.append(Action("move", {
                "src": str(src),
                "dst": str(vault / "Library" / folder),
            }))

    if any(a.kind == "move" for a in actions):
        actions.append(Action("rewrite_wikilinks", {"vault": str(vault)}))
        actions.append(Action("reindex", {"target": "qdrant"}))
        actions.append(Action("reindex", {"target": "fts5"}))
    return actions


@dataclass
class Migrator:
    vault_root: Path
    data_root: Path

    def lock_path(self) -> Path:
        return self.data_root / ".migration.lock"

    @contextlib.contextmanager
    def lock(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        lp = self.lock_path()
        if lp.exists():
            try:
                pid = int(lp.read_text().strip() or "0")
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                raise MigrationAborted(f"migration in progress (pid {pid})")
            lp.unlink(missing_ok=True)
        lp.write_text(str(os.getpid()))
        try:
            yield
        finally:
            lp.unlink(missing_ok=True)

    def assert_clean_git(self, allow_dirty: bool) -> None:
        if allow_dirty:
            return
        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.vault_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode == 0 and r.stdout.strip():
                raise MigrationAborted("vault has uncommitted changes; use --allow-dirty or commit first")
        except FileNotFoundError:
            pass

    def backup_tarball(self) -> Path:
        stamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
        out = self.data_root / "backups" / f"vault-pre-v2-{stamp}.tar.gz"
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, "w:gz") as tar:
            tar.add(self.vault_root, arcname=self.vault_root.name)
        return out


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness check; portable across POSIX and Windows."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default="Vellum/Vault", type=Path)
    parser.add_argument("--data", default="Vellum/backend/data", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--no-backup", action="store_true", help="Skip tarball; use only if vault is already committed to git")
    args = parser.parse_args(argv)

    m = Migrator(vault_root=args.vault, data_root=args.data)
    plan = plan_actions(args.vault)

    if not plan:
        print("nothing to migrate")
        return 0

    print("planned actions:")
    for a in plan:
        print(f"  - {a.render()}")

    if not args.apply:
        print("\n(dry-run; pass --apply to execute)")
        return 0

    try:
        with m.lock():
            m.assert_clean_git(args.allow_dirty)
            if not args.no_backup:
                print(f"backup: {m.backup_tarball()}")
            else:
                print("skipping tarball backup (--no-backup); ensure your vault is committed in git")
            _execute_plan(plan)
    except MigrationAborted as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return 2
    return 0


def _execute_plan(plan: list[Action]) -> None:
    for action in plan:
        if action.kind == "create_dir":
            Path(action.args["path"]).mkdir(parents=True, exist_ok=True)
        elif action.kind == "write_template":
            Path(action.args["dest"]).write_text(load_template(action.args["name"]), encoding="utf-8")
        elif action.kind == "move":
            src = Path(action.args["src"])
            dst = Path(action.args["dst"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        elif action.kind == "rewrite_wikilinks":
            from scripts.migrate_vault_v2 import rewrite_wikilinks
            rewrite_wikilinks(Path(action.args["vault"]))
        elif action.kind == "reindex":
            from scripts.migrate_vault_v2 import run_reindex
            run_reindex(action.args["target"])


if __name__ == "__main__":
    sys.exit(main())
