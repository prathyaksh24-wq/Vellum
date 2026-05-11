from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.telemetry.usage_ledger import UsageLedger


@pytest.fixture
def ledger(tmp_path: Path) -> UsageLedger:
    return UsageLedger(tmp_path / "usage.db")


def test_ledger_creates_db_on_first_write(ledger: UsageLedger, tmp_path: Path) -> None:
    assert not (tmp_path / "usage.db").exists()
    ledger.record(
        thread_id="t1", model="google/gemma-4-31b-it",
        in_tokens=100, out_tokens=50, source="tui",
    )
    assert (tmp_path / "usage.db").exists()


def test_record_persists_row(ledger: UsageLedger) -> None:
    ledger.record(
        thread_id="t1", model="google/gemma-4-31b-it",
        in_tokens=100, out_tokens=50, source="tui",
    )
    rows = ledger.all_rows()
    assert len(rows) == 1
    assert rows[0]["thread_id"] == "t1"
    assert rows[0]["model"] == "google/gemma-4-31b-it"
    assert rows[0]["in_tokens"] == 100
    assert rows[0]["out_tokens"] == 50
    assert rows[0]["source"] == "tui"
    assert rows[0]["cost_usd"] == pytest.approx(0.0000350)  # 100*0.2/1M + 50*0.3/1M


def test_summarize_window_filters_by_days(ledger: UsageLedger) -> None:
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=1_000_000, out_tokens=0, source="tui", ts=old_ts)
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=2_000_000, out_tokens=0, source="tui", ts=new_ts)
    summary = ledger.summarize(days=7)
    assert len(summary) == 1
    assert summary[0]["in_tokens"] == 2_000_000


def test_summarize_aggregates_per_model(ledger: UsageLedger) -> None:
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=100, out_tokens=50, source="tui")
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=200, out_tokens=100, source="cli")
    ledger.record(thread_id="t1", model="google/gemma-3-12b-it",
                  in_tokens=10, out_tokens=5, source="api")
    summary = sorted(ledger.summarize(days=7), key=lambda r: r["model"])
    assert len(summary) == 2
    gemma3 = summary[0]
    gemma4 = summary[1]
    assert gemma3["model"] == "google/gemma-3-12b-it"
    assert gemma3["in_tokens"] == 10
    assert gemma4["model"] == "google/gemma-4-31b-it"
    assert gemma4["in_tokens"] == 300
    assert gemma4["out_tokens"] == 150


def test_pragma_user_version_is_one(ledger: UsageLedger) -> None:
    ledger.record(thread_id="t1", model="x", in_tokens=0, out_tokens=0, source="tui")
    assert ledger.user_version() == 1
