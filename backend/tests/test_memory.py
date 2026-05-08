from agent.memory import long_term
from agent.memory.long_term import LongTermMemory


def test_store_and_get_recent_facts(tmp_path):
    memory = LongTermMemory(tmp_path / "memory.db")

    first_id = memory.store_fact("User likes NBA", category="sports")
    second_id = memory.store_fact("User reads books", category="books")

    assert first_id == 1
    assert second_id == 2
    assert memory.get_recent_facts() == ["User reads books", "User likes NBA"]
    assert memory.get_recent_facts(category="sports") == ["User likes NBA"]


def test_get_recent_facts_increments_access_count(tmp_path):
    db_path = tmp_path / "memory.db"
    memory = LongTermMemory(db_path)
    memory.store_fact("Fact one")

    assert memory.get_recent_facts(limit=1) == ["Fact one"]

    with memory._connect() as conn:
        count = conn.execute("SELECT access_count FROM facts").fetchone()["access_count"]
    assert count == 1


def test_query_log_round_trip(tmp_path):
    memory = LongTermMemory(tmp_path / "memory.db")

    row_id = memory.log_query("What is new?", "vault", 0.87)
    queries = memory.get_recent_queries()

    assert row_id == 1
    assert queries[0]["query"] == "What is new?"
    assert queries[0]["answer_source"] == "vault"
    assert queries[0]["confidence"] == 0.87


def test_default_memory_path_is_configured_under_data_memory():
    assert long_term.DB_PATH.as_posix() == "data/memory/long_term.db"
