"""Text-hash dedup for X handles, both within-handle and cross-handle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def text_hash(text: str) -> str:
    """Normalize and hash tweet text. 16 hex chars of SHA-256.

    Normalization: lowercase, whitespace-collapsed. Punctuation kept.
    """
    normalized = " ".join((text or "").lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def load_text_hashes(base: Path) -> set[str]:
    """Read the handle's manifest and return the set of text_hash values.

    Returns empty set if the manifest doesn't exist or is malformed.
    """
    manifest = base / "tweets.json"
    if not manifest.exists():
        return set()
    try:
        records = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {row["text_hash"] for row in records if row.get("text_hash")}


def collect_group_text_hashes(
    *,
    handles: Iterable,
    vault_root: Path,
    exclude_name: str,
) -> set[str]:
    """Union the text_hash sets from every handle in `handles` whose name
    is not `exclude_name`. Used to compute the cross-handle dedup set."""
    out: set[str] = set()
    for h in handles:
        if h.name == exclude_name:
            continue
        base = vault_root / "Library" / "X" / h.name
        out |= load_text_hashes(base)
    return out
