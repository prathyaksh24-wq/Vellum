"""Verify relative paths in Settings resolve to the same absolute path
regardless of the process CWD. Embedded Chroma is keyed by storage path,
so a CWD-dependent path produces split-brain DBs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.config import REPO_ROOT, _resolve_against_repo


def test_resolve_against_repo_absolute_stays_absolute(tmp_path: Path) -> None:
    abs_p = tmp_path / "x"
    out = _resolve_against_repo(abs_p)
    assert out == abs_p.resolve()


def test_resolve_against_repo_relative_anchors_to_repo() -> None:
    out = _resolve_against_repo(Path("data/embeddings/chroma"))
    assert out == (REPO_ROOT / "data/embeddings/chroma").resolve()


def test_resolve_against_repo_is_cwd_independent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Same relative path resolves to the same absolute path from any CWD."""
    p = Path("data/embeddings/chroma")

    monkeypatch.chdir(REPO_ROOT)
    from_root = _resolve_against_repo(p)

    monkeypatch.chdir(REPO_ROOT / "backend")
    from_backend = _resolve_against_repo(p)

    monkeypatch.chdir(tmp_path)
    from_tmp = _resolve_against_repo(p)

    assert from_root == from_backend == from_tmp


def test_repo_root_points_at_vellum_repo() -> None:
    """REPO_ROOT should be the directory containing both backend/ and frontend/."""
    assert (REPO_ROOT / "backend").is_dir()
    assert (REPO_ROOT / "backend" / "agent" / "config.py").is_file()
