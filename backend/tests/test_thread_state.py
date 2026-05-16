from pathlib import Path

from agent.memory.sessions import ThreadStateStore


def test_thread_state_round_trip(tmp_path: Path) -> None:
    store = ThreadStateStore(sessions_db=tmp_path / "sessions.db")

    # Defaults
    assert store.get_active_project("t1") is None
    assert store.get_turns_since_hot_rewrite("t1") == 0

    # Set + read back
    store.set_active_project("t1", "fitness")
    assert store.get_active_project("t1") == "fitness"

    assert store.bump_turns("t1") == 1
    assert store.bump_turns("t1") == 2
    assert store.get_turns_since_hot_rewrite("t1") == 2

    store.reset_turns("t1")
    assert store.get_turns_since_hot_rewrite("t1") == 0

    # Clear active project
    store.set_active_project("t1", None)
    assert store.get_active_project("t1") is None


def test_thread_state_independent_threads(tmp_path: Path) -> None:
    store = ThreadStateStore(sessions_db=tmp_path / "sessions.db")
    store.set_active_project("t1", "fitness")
    store.set_active_project("t2", "writing")
    assert store.get_active_project("t1") == "fitness"
    assert store.get_active_project("t2") == "writing"


def test_thread_state_idempotent_init(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    store1 = ThreadStateStore(sessions_db=db)
    store1.set_active_project("t1", "fitness")
    store1.bump_turns("t1")
    store1.bump_turns("t1")

    # Re-init must not raise and must preserve existing data
    store2 = ThreadStateStore(sessions_db=db)
    assert store2.get_active_project("t1") == "fitness"
    assert store2.get_turns_since_hot_rewrite("t1") == 2


def test_bump_turns_creates_row_on_first_call(tmp_path: Path) -> None:
    store = ThreadStateStore(sessions_db=tmp_path / "sessions.db")
    # Brand-new thread_id; no row exists yet
    result = store.bump_turns("never-seen")
    assert result == 1
    assert store.get_turns_since_hot_rewrite("never-seen") == 1
