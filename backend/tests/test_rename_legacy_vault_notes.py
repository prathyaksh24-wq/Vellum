import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rename_legacy_vault_notes.py"
SPEC = importlib.util.spec_from_file_location("rename_legacy_vault_notes", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
rename_tree = MODULE.rename_tree


def test_rename_tree_uses_question_and_handles_duplicate_titles(tmp_path: Path):
    root = tmp_path / "Archive" / "Legacy Agent Logs"
    root.mkdir(parents=True)
    for name in ("QA 20260707_034938.md", "QA 20260707_034939.md"):
        (root / name).write_text("## Question\nWhen is the next F1 race?\n", encoding="utf-8")

    result = rename_tree(root, dry_run=False)

    assert result["renamed"] == 2
    assert (root / "When is the next F1 race.md").exists()
    assert (root / "When is the next F1 race (2).md").exists()


def test_rename_tree_dry_run_does_not_move_note(tmp_path: Path):
    root = tmp_path / "Archive" / "Legacy Memory Cards"
    root.mkdir(parents=True)
    source = root / "20260626-053044-953785-f1.md"
    source.write_text("# Formula One standings\n", encoding="utf-8")

    result = rename_tree(root, dry_run=True)

    assert result["renamed"] == 1
    assert source.exists()


def test_generated_only_preserves_curated_filenames(tmp_path: Path):
    root = tmp_path / "Sports"
    root.mkdir()
    (root / "latest.md").write_text("# Latest sports", encoding="utf-8")
    generated = root / "20260616-093052-sports-response.md"
    generated.write_text("## Question\nwhen is the next f1 race?", encoding="utf-8")

    result = rename_tree(root, dry_run=False, generated_only=True)

    assert result["renamed"] == 1
    assert (root / "latest.md").exists()
    assert (root / "When is the next F1 race.md").exists()
