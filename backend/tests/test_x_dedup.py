import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "x_dedup.py"


def _load():
    spec = importlib.util.spec_from_file_location("x_dedup", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_text_hash_lowercases_and_collapses_whitespace():
    mod = _load()
    h1 = mod.text_hash("Be honest with yourself.")
    h2 = mod.text_hash("be honest   with yourself.")
    assert h1 == h2


def test_text_hash_preserves_punctuation():
    mod = _load()
    h1 = mod.text_hash("Be present.")
    h2 = mod.text_hash("Be present")
    assert h1 != h2


def test_text_hash_returns_16_hex_chars():
    mod = _load()
    h = mod.text_hash("anything")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_load_text_hashes_returns_empty_for_missing_manifest(tmp_path):
    mod = _load()
    base = tmp_path / "X" / "naval"
    base.mkdir(parents=True)
    hashes = mod.load_text_hashes(base)
    assert hashes == set()


def test_load_text_hashes_reads_existing_manifest(tmp_path):
    mod = _load()
    base = tmp_path / "X" / "naval"
    base.mkdir(parents=True)
    records = [
        {"status_id": "1", "text_hash": "abc1234567890def"},
        {"status_id": "2", "text_hash": "1234567890abcdef"},
    ]
    (base / "tweets.json").write_text(json.dumps(records), encoding="utf-8")
    hashes = mod.load_text_hashes(base)
    assert hashes == {"abc1234567890def", "1234567890abcdef"}


def test_collect_group_text_hashes_unions_siblings(tmp_path):
    mod = _load()
    naval = tmp_path / "Library" / "X" / "naval"
    nhq = tmp_path / "Library" / "X" / "NavalismHQ"
    naval.mkdir(parents=True)
    nhq.mkdir(parents=True)
    (naval / "tweets.json").write_text(
        json.dumps([{"status_id": "n1", "text_hash": "aaaa111122223333"}]),
        encoding="utf-8",
    )
    (nhq / "tweets.json").write_text(
        json.dumps([{"status_id": "h1", "text_hash": "bbbb444455556666"}]),
        encoding="utf-8",
    )

    # Use a stub handle list to avoid coupling to handle_config
    class _H:
        def __init__(self, name): self.name = name
    handles = [_H("naval"), _H("NavalismHQ")]

    hashes = mod.collect_group_text_hashes(
        handles=handles, vault_root=tmp_path, exclude_name="rumilyrics"
    )
    assert hashes == {"aaaa111122223333", "bbbb444455556666"}


def test_collect_group_text_hashes_excludes_self(tmp_path):
    mod = _load()
    naval = tmp_path / "Library" / "X" / "naval"
    nhq = tmp_path / "Library" / "X" / "NavalismHQ"
    naval.mkdir(parents=True)
    nhq.mkdir(parents=True)
    (naval / "tweets.json").write_text(
        json.dumps([{"status_id": "n1", "text_hash": "aaaa"}]),
        encoding="utf-8",
    )
    (nhq / "tweets.json").write_text(
        json.dumps([{"status_id": "h1", "text_hash": "bbbb"}]),
        encoding="utf-8",
    )

    class _H:
        def __init__(self, name): self.name = name
    handles = [_H("naval"), _H("NavalismHQ")]

    hashes = mod.collect_group_text_hashes(
        handles=handles, vault_root=tmp_path, exclude_name="naval"
    )
    # naval excluded, only NavalismHQ contributes
    assert hashes == {"bbbb"}
