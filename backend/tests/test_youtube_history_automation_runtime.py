"""Run-now and scheduled history refreshes must use the same local reader."""
import asyncio
from types import SimpleNamespace

import pytest

from agent.automations import builtins, runner
from agent.automations.scheduler import AutomationScheduler
from agent.automations.store import AutomationStore


def setup_job(tmp_path, monkeypatch, *, status='ready'):
    store = AutomationStore(tmp_path/'automations')
    builtins.seed_builtins(store)
    job = next(row for row in store.list() if row.get('builtin_key') == 'youtube_browser_history')
    job = store.update(job['id'], state='active')
    calls = []
    def refresh(*, automatic):
        calls.append(automatic)
        return {'status':status, 'records':13, 'message':'Sign into YouTube.' if status == 'sign_in_required' else 'History refreshed.',
            'private_title':'Do not export this video title', 'account_fingerprint':'private-account'}
    from agent.plugins import youtube_browser_history
    monkeypatch.setattr(youtube_browser_history, 'YouTubeBrowserHistory', lambda:SimpleNamespace(refresh=refresh))
    async def unexpected_reasoning(*_args):
        pytest.fail('A history maintenance job must not launch a model turn')
    monkeypatch.setattr(runner, '_execute_reasoning_turn', unexpected_reasoning)
    monkeypatch.setattr(runner, '_deliver_result', lambda *_:pytest.fail('A quiet refresh must not create a chat'))
    return store, job, calls


def test_history_run_now_reads_locally_and_records_content_free_result(tmp_path, monkeypatch):
    store, job, calls = setup_job(tmp_path, monkeypatch)
    result = asyncio.run(runner.run_automation_now(job, store))
    assert result['status'] == 'complete' and calls == [True]
    assert '13' in result['output']
    assert 'private' not in str(result)
    assert store.runs(job['id'])[-1]['id'] == result['id']


def test_scheduled_history_run_records_the_same_reader_outcome(tmp_path, monkeypatch):
    store, job, calls = setup_job(tmp_path, monkeypatch)
    scheduler = AutomationScheduler(store)
    asyncio.run(scheduler._fire(job['id']))
    assert calls == [True]
    assert store.runs(job['id'])[-1]['status'] == 'complete'


def test_history_run_failure_is_visible_in_run_history(tmp_path, monkeypatch):
    store, job, calls = setup_job(tmp_path, monkeypatch, status='sign_in_required')
    result = asyncio.run(runner.run_automation_now(job, store))
    assert calls == [True] and result['status'] == 'failed'
    assert result['error'] == 'Sign into YouTube.'
