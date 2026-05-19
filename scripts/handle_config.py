"""Handle configuration registry for multi-handle X scraping."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APIFY_SOURCE_LABEL = "Apify apidojo/tweet-scraper"


@dataclass(frozen=True)
class HandleConfig:
    name: str             # X handle, case preserved (e.g. "NavalismHQ")
    filter_profile: str   # key into filter_profiles.PROFILES
    dedup_group: str      # cross-handle dedup scope
    source_label: str     # for tweet frontmatter


HANDLES: list[HandleConfig] = [
    HandleConfig(name="naval",       filter_profile="aphorism",        dedup_group="naval",   source_label=APIFY_SOURCE_LABEL),
    HandleConfig(name="NavalismHQ",  filter_profile="aphorism",        dedup_group="naval",   source_label=APIFY_SOURCE_LABEL),
    HandleConfig(name="rumilyrics",  filter_profile="multiline_quote", dedup_group="rumi",    source_label=APIFY_SOURCE_LABEL),
    HandleConfig(name="AlexHormozi", filter_profile="original_tweet",  dedup_group="hormozi", source_label=APIFY_SOURCE_LABEL),
]


def vault_base_for(handle: HandleConfig, vault_root: Path) -> Path:
    """Return the per-handle vault folder under Library/X/."""
    return vault_root / "Library" / "X" / handle.name


def handles_in_dedup_group(group: str) -> list[HandleConfig]:
    """Return every configured handle in the named dedup group."""
    return [h for h in HANDLES if h.dedup_group == group]


def get_handle(name: str) -> HandleConfig:
    """Lookup a handle by its name. Raises KeyError if not found."""
    for h in HANDLES:
        if h.name == name:
            return h
    raise KeyError(f"Unknown handle: {name}")
