import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.automations.store import AutomationStore, MAX_NOTIFICATION_HISTORY
from agent.automations import api, runner
from agent.app_actions.automations import AutomationActionService
from agent.app_actions.models import AppActionContext


def job(store, **fields):
    return store.create(name="Creator uploads", instructions="Check uploads",
        schedule={"kind": "interval", "seconds": 900}, destination={"kind": "notification"}, **fields)


def test_notification_stream_observes_durable_writes_and_reconnects_without_private_content(tmp_path):
    store = AutomationStore(tmp_path)
    record = job(store)
    class Request:
        async def is_disconnected(self): return False
    async def read():
        events = api._notification_changes(store, Request(), interval=0)
        initial = await anext(events)
        assert 'notifications.changed' in initial
        AutomationStore(tmp_path).deliver_notification(record['id'], 'fresh', 'PRIVATE TITLE')
        changed = await anext(events)
        assert changed != initial
        assert 'PRIVATE TITLE' not in changed
        await events.aclose()
        reconnected = api._notification_changes(AutomationStore(tmp_path), Request(), interval=0)
        assert await anext(reconnected) == changed
        await reconnected.aclose()
    asyncio.run(read())


def test_notifications_persist_once_and_read_state_survives_restart(tmp_path):
    store = AutomationStore(tmp_path)
    record = job(store)
    assert runner._deliver_creator_upload(record, 'upload-1', 'Creator: New video\nhttps://www.youtube.com/watch?v=abcdefghijk', store)
    assert not runner._deliver_creator_upload(record, 'upload-1', 'Same video', store)
    store.deliver_notification(record['id'], 'imported', 'Retained upload', read_at='2026-10-11T02:00:00Z', created_at='2026-10-10T02:00:00Z')
    restarted = AutomationStore(tmp_path)
    snapshot = restarted.notification_snapshot()
    assert snapshot['unread_count'] == 1
    assert snapshot['items'][0]['url'] == 'https://www.youtube.com/watch?v=abcdefghijk'
    assert snapshot['items'][1]['created_at'] == '2026-10-10T02:00:00Z'
    assert not (tmp_path / 'ui' / 'conversations.json').exists()
    service = AutomationActionService(store_provider=lambda: restarted)
    result = service.execute('automation.notifications.read', {'ids':['upload-1']}, AppActionContext(source='ui'))
    assert result['read_count'] == 1
    assert not service.execute('automation.notifications.read', {'ids':['upload-1']}, AppActionContext(source='ui'))['changed']
    assert AutomationStore(tmp_path).notification_snapshot()['unread_count'] == 0


def test_multiple_store_instances_preserve_run_and_notification_writes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    first, second = AutomationStore(tmp_path), AutomationStore(tmp_path)
    record = job(first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(first.record_run, record['id'], 'run-1'),
                   pool.submit(second.deliver_notification, record['id'], 'upload-1', 'New upload')]
        for future in futures:
            future.result()
    assert len(first.runs(record['id'])) == 1
    assert second.notification_snapshot()['unread_count'] == 1


def test_notification_history_is_bounded_and_preferences_are_respected(tmp_path):
    store = AutomationStore(tmp_path)
    record = job(store)
    for index in range(MAX_NOTIFICATION_HISTORY + 3):
        store.deliver_notification(record['id'], str(index), 'New upload')
    assert len(store.get(record['id'])['notification_history']) == MAX_NOTIFICATION_HISTORY
    assert len(store.notification_snapshot(limit=2)['items']) == 2
    assert store.mark_notifications_read([], all_items=True) == MAX_NOTIFICATION_HISTORY
    store.update(record['id'], notifications={'level':'none'})
    assert not store.deliver_notification(record['id'], 'muted', 'Quiet')
    assert store.notification_snapshot()['unread_count'] == 0


def test_notification_api_is_typed_uncached_and_bounded(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path)
    record = job(store)
    store.deliver_notification(record['id'], 'upload-1', 'New upload')
    monkeypatch.setattr(api, 'get_store', lambda: store)
    app = FastAPI()
    app.include_router(api.router, prefix='/api')
    with TestClient(app) as client:
        response = client.get('/api/automations/notifications')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['local_only']
        assert response.json()['unread_count'] == 1
        assert client.get('/api/automations/notifications?limit=201').status_code == 422


def test_recent_inbox_excludes_old_read_invalid_and_future_items_without_removing_history(tmp_path, monkeypatch):
    from agent.automations import store as store_module
    fixed=datetime(2026,10,12,12,tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return fixed
    monkeypatch.setattr(store_module,'datetime',Clock)
    store=AutomationStore(tmp_path);record=job(store)
    for key,stamp,read in [('fresh',fixed-timedelta(hours=1),None),
                           ('boundary',fixed-timedelta(hours=24),None),
                           ('old',fixed-timedelta(days=2),None),
                           ('read',fixed-timedelta(minutes=1),fixed.isoformat()),
                           ('future',fixed+timedelta(hours=1),None)]:
        store.deliver_notification(record['id'],key,'Creator: '+key,created_at=stamp.isoformat(),read_at=read)
    store.deliver_notification(record['id'],'invalid','Creator: invalid',created_at='unknown')
    recent=store.notification_snapshot(view='recent',limit=1)
    assert [item['id'] for item in recent['items']]==['fresh']
    assert recent['recent_unread_count']==2 and recent['has_more']
    assert store.notification_snapshot(view='recent',offset=1)['items'][0]['id']=='boundary'
    history=store.notification_snapshot(view='history',query='old',limit=1)
    assert history['items'][0]['id']=='old' and history['matched_count']==1
    service=AutomationActionService(store_provider=lambda:store)
    result=service.execute('automation.notifications.read',{'recent':True},AppActionContext(source='ui'))
    assert result['read_count']==2
    restarted=AutomationStore(tmp_path)
    assert restarted.notification_snapshot(view='recent')['items']==[]
    retained={item['id']:item for item in restarted.notification_snapshot(view='history')['items']}
    assert len(retained)==6 and retained['fresh']['read_at'] and not retained['old']['read_at']


def test_notification_history_filters_before_pagination_and_exposes_query_bounds(tmp_path,monkeypatch):
    store=AutomationStore(tmp_path);record=job(store)
    for index in range(55):
        store.deliver_notification(record['id'],str(index),'Kenny: video '+str(index))
    store.deliver_notification(record['id'],'target','Other creator: matched title')
    monkeypatch.setattr(api,'get_store',lambda:store)
    app=FastAPI();app.include_router(api.router,prefix='/api')
    with TestClient(app) as client:
        result=client.get('/api/automations/notifications?view=history&query=matched&limit=1').json()
        assert [item['id'] for item in result['items']]==['target']
        assert result['matched_count']==1 and result['total_count']==56
        page=client.get('/api/automations/notifications?view=history&limit=50&offset=50').json()
        assert len(page['items'])==6 and not page['has_more']
        assert client.get('/api/automations/notifications?view=unknown').status_code==422
        assert client.get('/api/automations/notifications?offset=-1').status_code==422
        assert client.get('/api/automations/notifications?query='+'x'*201).status_code==422


def test_reasoning_automation_can_deliver_a_ping_without_creating_a_chat(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path)
    record = job(store)
    async def execute(_):
        return 'A new result'
    monkeypatch.setattr(runner, '_execute_reasoning_turn', execute)
    def no_chat(*_):
        raise AssertionError('Notification destinations must not create conversations')
    monkeypatch.setattr(runner, '_deliver_result', no_chat)
    result = asyncio.run(runner.run_automation_now(record, store))
    assert result['status'] == 'complete'
    assert store.notification_snapshot()['items'][0]['message'] == 'A new result'
