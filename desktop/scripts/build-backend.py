"""Stage a Windows Python runtime and installed backend dependencies for Forge.

Publisher-side only. Does not install packages, read .env, copy application data,
or run the backend. Large ML libraries are included if installed in the chosen
build environment; model weights stay in the user's workspace/model service.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from agent.desktop_runtime import PROTOCOL_VERSION, source_build_id, source_files


def validate_environment() -> None:
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise RuntimeError("The bundled desktop backend currently supports Windows x64 builds only.")
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Build from a dedicated backend virtual environment, not the system Python.")
    from packaging.requirements import Requirement
    metadata = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    missing = []
    for raw in metadata["project"]["dependencies"]:
        requirement = Requirement(raw)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = importlib.metadata.version(requirement.name)
            if requirement.specifier and version not in requirement.specifier:
                missing.append(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(requirement.name)
    if missing:
        raise RuntimeError("The build environment needs these backend dependencies: " + ", ".join(missing))


def ignored(_directory, names):
    return {name for name in names if name in {"__pycache__", ".git", ".env", "tests", "test", "fixtures"}
            or name.endswith((".pyc", ".pyo", ".pth"))
            or name.startswith("__editable__")}


def remove_generated(directory: Path, parent: Path) -> None:
    resolved = directory.resolve()
    if not resolved.is_relative_to(parent.resolve()) or resolved == parent.resolve():
        raise RuntimeError("Refusing to remove a path outside the backend staging directory.")
    if directory.exists():
        shutil.rmtree(directory)


def build() -> None:
    validate_environment()
    parent = ROOT / "desktop/resources"
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / "backend-runtime"
    staging = Path(tempfile.mkdtemp(prefix="backend-staging-", dir=parent))
    try:
        python = staging / "python"
        python.mkdir()
        base = Path(sys.base_prefix)
        for file in base.iterdir():
            if file.is_file() and (file.suffix.lower() in {".exe", ".dll", ".zip"} or file.name.startswith("LICENSE")):
                shutil.copy2(file, python / file.name)
        for directory in ("DLLs", "Lib", "tcl"):
            source = base / directory
            if source.is_dir():
                def base_ignore(directory_path, names):
                    skipped = ignored(directory_path, names)
                    if Path(directory_path) == base / "Lib":
                        skipped.add("site-packages")
                    return skipped
                shutil.copytree(source, python / directory, ignore=base_ignore)
        packages = Path(sys.prefix) / "Lib/site-packages"
        if not packages.is_dir():
            raise RuntimeError("Use the dedicated Windows backend virtual environment to build the release.")
        shutil.copytree(packages, python / "Lib/site-packages", ignore=ignored)
        app = staging / "app"
        files = source_files(ROOT)
        identity = source_build_id(ROOT)
        for source in files:
            target = app / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        # License/readme assets are explicit. Never copy a checkout or data tree.
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
            if (ROOT / name).is_file():
                shutil.copy2(ROOT / name, app / name)
        manifest = {"protocol_version": PROTOCOL_VERSION, "build_id": identity,
                    "platform": "win32", "arch": "x64", "python": sys.version.split()[0]}
        (app / "desktop-backend.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if source_build_id(app) != identity:
            raise RuntimeError("Backend sources changed during staging; build again from a stable checkout.")
        if destination.exists():
            remove_generated(destination, parent)
        staging.rename(destination)
        total = sum(p.stat().st_size for p in destination.rglob("*") if p.is_file())
        print(f"Staged backend {identity[:12]} ({total / 1024**3:.2f} GiB). No workspace data or model cache directories copied.")
    finally:
        if staging.exists():
            remove_generated(staging, parent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check publisher dependencies without copying or installing anything.")
    options = parser.parse_args()
    if options.check:
        validate_environment()
        print("Backend build environment is ready. No files were staged or installed.")
    else:
        build()
