import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "handle_config.py"


def _load():
    spec = importlib.util.spec_from_file_location("handle_config", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_handles_registry_has_four_handles():
    mod = _load()
    names = [h.name for h in mod.HANDLES]
    assert names == ["naval", "NavalismHQ", "rumilyrics", "AlexHormozi"]


def test_handles_have_no_duplicate_names():
    mod = _load()
    names = [h.name for h in mod.HANDLES]
    assert len(names) == len(set(names))


def test_naval_and_navalismhq_share_dedup_group():
    mod = _load()
    by_name = {h.name: h for h in mod.HANDLES}
    assert by_name["naval"].dedup_group == "naval"
    assert by_name["NavalismHQ"].dedup_group == "naval"


def test_rumi_and_hormozi_have_isolated_dedup_groups():
    mod = _load()
    by_name = {h.name: h for h in mod.HANDLES}
    assert by_name["rumilyrics"].dedup_group == "rumi"
    assert by_name["AlexHormozi"].dedup_group == "hormozi"


def test_filter_profiles_assigned_correctly():
    mod = _load()
    by_name = {h.name: h for h in mod.HANDLES}
    assert by_name["naval"].filter_profile == "aphorism"
    assert by_name["NavalismHQ"].filter_profile == "aphorism"
    assert by_name["rumilyrics"].filter_profile == "multiline_quote"
    assert by_name["AlexHormozi"].filter_profile == "original_tweet"


def test_vault_base_for_returns_library_path(tmp_path):
    mod = _load()
    h = mod.HandleConfig(
        name="naval",
        filter_profile="aphorism",
        dedup_group="naval",
        source_label="Apify apidojo/tweet-scraper",
    )
    base = mod.vault_base_for(h, tmp_path)
    assert base == tmp_path / "Library" / "X" / "naval"


def test_vault_base_preserves_case():
    mod = _load()
    h = mod.HandleConfig(
        name="NavalismHQ",
        filter_profile="aphorism",
        dedup_group="naval",
        source_label="x",
    )
    base = mod.vault_base_for(h, Path("/v"))
    assert base.name == "NavalismHQ"


def test_handles_in_dedup_group_returns_siblings():
    mod = _load()
    siblings = mod.handles_in_dedup_group("naval")
    names = sorted(h.name for h in siblings)
    assert names == ["NavalismHQ", "naval"]


def test_handles_in_dedup_group_for_solo_handle():
    mod = _load()
    siblings = mod.handles_in_dedup_group("hormozi")
    assert [h.name for h in siblings] == ["AlexHormozi"]
