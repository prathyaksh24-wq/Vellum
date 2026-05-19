import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "x_budget.py"


def _load():
    spec = importlib.util.spec_from_file_location("x_budget", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_record_creates_monthly_bucket(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    bookkeeper = mod.BudgetLedger(ledger_path, month="2026-05")
    bookkeeper.record(handle="naval", run_usd=0.50)
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert "2026-05" in data
    assert data["2026-05"]["used_usd"] == 0.50
    assert len(data["2026-05"]["runs"]) == 1
    assert data["2026-05"]["runs"][0]["handle"] == "naval"


def test_record_accumulates_within_month(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    b.record(handle="naval", run_usd=0.30)
    b.record(handle="NavalismHQ", run_usd=0.20)
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert data["2026-05"]["used_usd"] == 0.50
    assert len(data["2026-05"]["runs"]) == 2


def test_new_month_starts_fresh(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    mod.BudgetLedger(ledger_path, month="2026-05").record(handle="naval", run_usd=4.90)
    mod.BudgetLedger(ledger_path, month="2026-06").record(handle="naval", run_usd=0.10)
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert data["2026-05"]["used_usd"] == 4.90
    assert data["2026-06"]["used_usd"] == 0.10


def test_used_returns_current_month_total(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    assert b.used() == 0.0
    b.record(handle="naval", run_usd=1.25)
    assert b.used() == 1.25


def test_pre_call_check_passes_under_cap(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    b.record(handle="naval", run_usd=4.49)
    b.pre_call_check()  # must not raise


def test_pre_call_check_raises_at_or_above_cap(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    b.record(handle="naval", run_usd=5.00)
    import pytest
    with pytest.raises(mod.BudgetExhausted):
        b.pre_call_check()


def test_near_cap_threshold(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    assert b.near_cap() is False
    b.record(handle="naval", run_usd=4.49)
    assert b.near_cap() is False
    b.record(handle="naval", run_usd=0.05)  # 4.54 cumulative
    assert b.near_cap() is True


def test_parse_run_usage_handles_both_field_names():
    mod = _load()
    assert mod.parse_run_usage({"usageTotalUsd": 0.5}) == 0.5
    assert mod.parse_run_usage({"usageUsd": 0.3}) == 0.3
    assert mod.parse_run_usage({"unrelated": 1}) == 0.0
    assert mod.parse_run_usage(None) == 0.0
