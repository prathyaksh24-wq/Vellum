"""Handle configuration registry for multi-handle X scraping."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


XAI_SOURCE_LABEL = "xAI X Search OAuth"


@dataclass(frozen=True)
class HandleConfig:
    name: str             # X handle, case preserved (e.g. "NavalismHQ")
    filter_profile: str   # key into filter_profiles.PROFILES
    dedup_group: str      # cross-handle dedup scope
    source_label: str     # for tweet frontmatter


_KNOWN_HANDLES: dict[str, tuple[str, str]] = {
    "naval": ("aphorism", "naval"),
    "NavalismHQ": ("aphorism", "naval"),
    "rumilyrics": ("multiline_quote", "rumi"),
    "AlexHormozi": ("original_tweet", "hormozi"),
}


def _config_for_name(name: str) -> HandleConfig:
    filter_profile, dedup_group = _KNOWN_HANDLES.get(name, ("original_tweet", name))
    return HandleConfig(
        name=name,
        filter_profile=filter_profile,
        dedup_group=dedup_group,
        source_label=XAI_SOURCE_LABEL,
    )


HANDLES: list[HandleConfig] = [_config_for_name(name) for name in _KNOWN_HANDLES]


def vault_base_for(handle: HandleConfig, vault_root: Path) -> Path:
    """Return the per-handle vault folder under Library/X/."""
    return vault_root / "Library" / "X" / handle.name


def handles_in_dedup_group(group: str) -> list[HandleConfig]:
    """Return every configured handle in the named dedup group."""
    return [h for h in HANDLES if h.dedup_group == group]


def get_handle(name: str) -> HandleConfig:
    """Lookup a handle by its name, defaulting unknown handles to original tweets."""
    for h in HANDLES:
        if h.name == name:
            return h
    return _config_for_name(name)


def handles_for_vault(vault_root: Path) -> list[HandleConfig]:
    """Discover X handles from Vault/Library/X, falling back to the registry."""
    x_root = vault_root / "Library" / "X"
    if not x_root.exists():
        return HANDLES
    names = [
        path.name
        for path in sorted(x_root.iterdir(), key=lambda p: p.name.casefold())
        if path.is_dir()
    ]
    return [_config_for_name(name) for name in names] or HANDLES
