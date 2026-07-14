from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from agent.skills import SkillUsageIntelligence, usage_scope


def test_usage_outcomes_success_rate_feedback_and_privacy(tmp_path: Path) -> None:
    store = SkillUsageIntelligence(tmp_path / ".skills", db_path=tmp_path / "usage.db")
    with usage_scope("Deploy from C:\\Users\\private\\repo for person@example.com", "thread-secret", store=store) as scope:
        scope.activate("deploy", "skill_view")
        event_id = scope.event_ids[0]
        scope.finish("completed", tool_count=3)

    recent = store.recent("deploy")[0]
    aggregate = store.aggregate("deploy")
    assert "private" not in recent["task_summary"]
    assert "person@example.com" not in recent["task_summary"]
    assert aggregate["success_rate"] == 1.0

    store.finish(event_id, outcome="corrected")
    aggregate = store.aggregate("deploy")
    assert aggregate["completed"] == 0
    assert aggregate["corrected"] == 1
    assert aggregate["success_rate"] == 0.0


def test_usage_retention_preserves_permanent_aggregates_and_concurrent_reads(tmp_path: Path) -> None:
    store = SkillUsageIntelligence(tmp_path / ".skills", db_path=tmp_path / "usage.db")
    event = store.activate("deploy", task_summary="Deploy safely", thread_id="thread", source="slash")
    store.finish(event, outcome="completed", latency_ms=10)
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    with store._connect() as connection:
        connection.execute("UPDATE usage_events SET created_at=? WHERE id=?", (old, event))
        connection.commit()

    assert store.purge() == 1
    assert store.aggregate("deploy")["total_uses"] == 1
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _index: store.aggregate("deploy")["total_uses"], range(20)))
    assert results == [1] * 20
