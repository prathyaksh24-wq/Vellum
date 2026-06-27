import sqlite3
from pathlib import Path

import pytest

from agent.memory.sessions import SessionsReader


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memory").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def reader(workdir: Path) -> SessionsReader:
    return SessionsReader(
        checkpoints_db=workdir / "data" / "memory" / "checkpoints.db",
        sessions_db=workdir / "data" / "memory" / "sessions.db",
    )


def _seed_checkpoint(path: Path, thread_id: str, checkpoint_ids: list[str]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint BLOB,
            metadata BLOB,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )
    for cid in checkpoint_ids:
        conn.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id) VALUES (?, '', ?)",
            (thread_id, cid),
        )
    conn.commit()
    conn.close()


def test_list_sessions_empty_when_no_db(reader: SessionsReader) -> None:
    assert reader.list_sessions() == []


def test_list_sessions_reads_checkpoints(reader: SessionsReader, workdir: Path) -> None:
    cp_db = workdir / "data" / "memory" / "checkpoints.db"
    # "default" thread has the higher-sorting checkpoint id -> appears first
    _seed_checkpoint(cp_db, "default", ["01J000", "01J001", "01J002"])
    _seed_checkpoint(cp_db, "research", ["01H900", "01H901"])
    sessions = reader.list_sessions()
    assert len(sessions) == 2
    by_id = {s["thread_id"]: s for s in sessions}
    assert by_id["default"]["msgs"] == 3
    assert by_id["research"]["msgs"] == 2
    assert sessions[0]["thread_id"] == "default"


def test_list_sessions_joins_title_when_set(reader: SessionsReader, workdir: Path) -> None:
    _seed_checkpoint(workdir / "data" / "memory" / "checkpoints.db", "t1", ["01J0"])
    reader.rename("t1", "my research")
    sessions = reader.list_sessions()
    assert sessions[0]["title"] == "my research"


def test_list_sessions_title_falls_back_to_thread_id(reader: SessionsReader, workdir: Path) -> None:
    _seed_checkpoint(workdir / "data" / "memory" / "checkpoints.db", "t9", ["01J0"])
    assert reader.list_sessions()[0]["title"] == "t9"


def test_delete_removes_checkpoints_and_title(reader: SessionsReader, workdir: Path) -> None:
    _seed_checkpoint(workdir / "data" / "memory" / "checkpoints.db", "t1", ["01J0", "01J1"])
    reader.rename("t1", "named")
    reader.delete("t1")
    assert reader.list_sessions() == []
