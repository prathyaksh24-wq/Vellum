"""Provider protocol and durable delivery tests; no live hub or account required."""
from datetime import UTC, datetime, timedelta
import hashlib
import hmac

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent.knowledge.store import KnowledgeStore
from agent.knowledge.models import SourceItemInput
from agent.plugins.youtube_creator_tracking import YouTubeCreatorTracking
from agent.plugins.youtube_push import YouTubePushDelivery, create_callback_app

C1 = 'UC' + 'a' * 22
C2 = 'UC' + 'b' * 22
VIDEO = 'abcdefghijk'
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
BASE = 'https://youtube.example.com'


class Clock:
    value = NOW
    def __call__(self):
        return self.value


class Hub:
    def __init__(self):
        self.calls = []
    def subscribe(self, fields):
        self.calls.append(fields)


@pytest.fixture
def setup(tmp_path):
    store = KnowledgeStore(tmp_path / 'knowledge.db', tmp_path / 'blobs')
    clock, hub = Clock(), Hub()
    tracking = YouTubeCreatorTracking(store=store, clock=clock)
    tracking.configure(dict(account_id='me', history_accounts=['me'], enabled=True,
        api_fallback=False, discovery_units_per_day=0, min_duration_seconds=180,
        rules=[dict(channel_id=C1, name='Creator', relationship='long_term')]))
    tracking.duration_provider = lambda ids: {video: dict(channel_id=C1, duration_seconds=600) for video in ids}
    service = YouTubePushDelivery(tracking=tracking, callback_base=BASE, hub=hub, clock=clock)
    return store, clock, hub, tracking, service


def activate(service, hub, channel=C1):
    service.reconcile()
    fields = next(item for item in hub.calls if item['hub.topic'].endswith(channel))
    token = fields['hub.callback'].rsplit('/', 1)[1]
    with TestClient(create_callback_app(service_provider=lambda: service)) as client:
        response = client.get('/youtube/websub/' + token, params={
            'hub.mode': 'subscribe', 'hub.topic': fields['hub.topic'],
            'hub.challenge': 'challenge', 'hub.lease_seconds': '86400'})
    assert response.status_code == 200
    assert response.text == 'challenge'
    return token, fields['hub.secret']


def body(clock, *, video=VIDEO, title='New upload', channel=C1, published=None):
    return (f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
        f'<entry><yt:videoId>{video}</yt:videoId><yt:channelId>{channel}</yt:channelId>'
        f'<title>{title}</title><author><name>Creator</name></author>'
        f'<published>{(published or clock()).isoformat()}</published></entry></feed>').encode()


def post(service, token, secret, payload):
    signature = 'sha1=' + hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
    with TestClient(create_callback_app(service_provider=lambda: service)) as client:
        return client.post('/youtube/websub/' + token, content=payload,
                           headers={'X-Hub-Signature': signature, 'Content-Type': 'application/atom+xml'})


def test_signed_upload_is_durable_then_delivers_once_without_rss_poll(setup):
    store, clock, hub, tracking, service = setup
    token, secret = activate(service, hub)
    clock.value += timedelta(seconds=10)
    payload = body(clock)
    assert post(service, token, secret, payload).status_code == 204
    # Reconstruct the service: accepting the webhook must not depend on a background task.
    restarted = YouTubePushDelivery(tracking=tracking, callback_base=BASE, hub=hub, clock=clock)
    deliveries = []
    result = restarted.drain(deliver=lambda *args: deliveries.append(args))
    assert result['delivered'] == 1
    assert VIDEO in deliveries[0][1]
    assert post(service, token, secret, payload).status_code == 204
    assert restarted.drain(deliver=lambda *args: deliveries.append(args))['delivered'] == 0
    assert len(deliveries) == 1
    assert store.youtube_tracking_saved_uploads('me', [C1])[0]['video_id'] == VIDEO


def test_all_account_subscriptions_are_registered_without_profile_capacity_limit(setup):
    store, _, hub, _, service = setup
    for index in range(130):
        channel = 'UC' + f'{index:022d}'
        store.upsert_source(SourceItemInput(kind='youtube_subscription', external_id=channel,
            account_id='me', title=channel, metadata={'subscribed_channel_id': channel}))
    store.upsert_source(SourceItemInput(kind='youtube_subscription', external_id='other',
        account_id='other-account', title='Other', metadata={'subscribed_channel_id': C2}))
    for _ in range(20):
        service.reconcile()
    topics = {item['hub.topic'] for item in hub.calls}
    assert len(topics) == 131  # subscriptions plus the explicitly tracked creator
    assert not any(topic.endswith(C2) for topic in topics)


def test_explicit_subscription_source_does_not_move_aggregate_history_account(setup):
    store, _, hub, tracking, service = setup
    source_account = 'UC' + 'z'*22
    args = tracking._config().model_dump()
    args['subscription_account_id'] = source_account
    tracking.configure(args)
    store.upsert_source(SourceItemInput(kind='youtube_subscription', external_id='linked',
        account_id=source_account, title='Linked subscription', metadata={'subscribed_channel_id':C2}))
    service.reconcile()
    assert any(item['hub.topic'].endswith(C2) for item in hub.calls)
    assert tracking._config().account_id == 'me'
    assert tracking._config().history_accounts == ['me']
    assert all(row['account_id'] == 'me' for row in store.youtube_push_subscriptions('me'))
    del args['subscription_account_id']
    tracking.configure(args)
    assert tracking._config().subscription_account_id == source_account


def test_callback_only_surface_rejects_forgery_wrong_channels_and_private_routes(setup):
    _, clock, hub, _, service = setup
    token, secret = activate(service, hub)
    with TestClient(create_callback_app(service_provider=lambda: service)) as client:
        assert client.get('/api/automations').status_code == 404
        assert client.get('/docs').status_code == 404
        assert client.get('/openapi.json').status_code == 404
        assert client.post('/youtube/websub/' + token, content=body(clock)).status_code == 403
        assert client.get('/youtube/websub/' + token, params={'hub.mode':'subscribe',
            'hub.topic':'https://evil.example/feed', 'hub.challenge':'x', 'hub.lease_seconds':'100'}).status_code == 404
    assert post(service, token, secret, body(clock, channel=C2)).status_code == 400
    assert post(service, token, secret, b'<!DOCTYPE feed><feed/>').status_code == 400
    assert post(service, token, secret, b'x' * 262145).status_code == 413


def test_push_checks_duration_promptly_but_shares_daily_quota_and_holds_shorts(setup):
    store, clock, hub, tracking, service = setup
    token, secret = activate(service, hub)
    clock.value += timedelta(seconds=10)
    for video, seconds in [(VIDEO, 180), ('12345678901', 600)]:
        tracking.duration_provider = lambda ids, seconds=seconds: {
            item:dict(channel_id=C1, duration_seconds=seconds) for item in ids}
        assert post(service, token, secret, body(clock, video=video)).status_code == 204
        calls = []
        result = service.drain(deliver=lambda *args: calls.append(args))
        assert result['delivered'] == int(seconds > 180)
        clock.value += timedelta(seconds=11)
    assert store.get_sync_cursor('youtube_creator_feed','me:budget')['state']['duration_units'] == 2


def test_delivery_failure_is_retried_and_title_edits_do_not_reping(setup):
    _, clock, hub, _, service = setup
    token, secret = activate(service, hub)
    clock.value += timedelta(seconds=10)
    payload = body(clock)
    assert post(service, token, secret, payload).status_code == 204
    def broken(*_):
        raise RuntimeError('delivery unavailable')
    with pytest.raises(RuntimeError):
        service.drain(deliver=broken)
    calls = []
    assert service.drain(deliver=lambda *args: calls.append(args))['delivered'] == 1
    assert post(service, token, secret, body(clock, title='Edited title')).status_code == 204
    assert service.drain(deliver=lambda *args: calls.append(args))['delivered'] == 0
    assert len(calls) == 1


def test_renewal_uses_granted_lease_and_restarts_preserve_secret(setup):
    _, clock, hub, tracking, service = setup
    token, secret = activate(service, hub)
    assert service.status().active_channels == 1
    clock.value += timedelta(hours=21)
    restarted = YouTubePushDelivery(tracking=tracking, callback_base=BASE, hub=hub, clock=clock)
    restarted.reconcile()
    assert len(hub.calls) == 2
    assert hub.calls[-1]['hub.secret'] == secret
    assert hub.calls[-1]['hub.callback'].endswith(token)


def test_old_edits_exclusions_pause_and_quiet_creators_never_ping(setup):
    store, clock, hub, tracking, service = setup
    token, secret = activate(service, hub)
    clock.value += timedelta(seconds=10)
    assert post(service, token, secret, body(clock, published=NOW-timedelta(hours=1))).status_code == 204
    assert service.drain(deliver=lambda *_: pytest.fail('Old baseline pinged'))['delivered'] == 0
    args = tracking._config().model_dump()
    args['rules'][0]['relationship'] = 'excluded'
    tracking.configure(args)
    assert post(service, token, secret, body(clock, video='12345678901')).status_code == 404
    service.reconcile()
    assert hub.calls[-1]['hub.mode'] == 'unsubscribe'


def test_no_endpoint_is_truthfully_unconfigured_and_rejects_non_https(setup):
    _, clock, hub, tracking, _ = setup
    service = YouTubePushDelivery(tracking=tracking, callback_base='', hub=hub, clock=clock)
    assert service.status().status == 'endpoint_required'
    assert service.reconcile()['requests'] == 0
    assert not hub.calls
    with pytest.raises(ValueError):
        YouTubePushDelivery(tracking=tracking, callback_base='http://localhost:8000', hub=hub, clock=clock)


def test_unknown_duration_retries_without_replaying_event_and_budget_is_not_bypassed(setup):
    store, clock, hub, tracking, service = setup
    token, secret = activate(service, hub)
    clock.value += timedelta(seconds=10)
    tracking.duration_provider = lambda _: {}
    assert post(service, token, secret, body(clock)).status_code == 204
    assert service.drain(deliver=lambda *_:pytest.fail('Unknown duration pinged'))['delivered'] == 0
    assert service.status().queued_uploads == 1
    calls = []
    tracking.duration_provider = lambda ids: calls.append(ids) or {VIDEO:{'channel_id':C1,'duration_seconds':600}}
    clock.value += timedelta(seconds=11)
    assert service.drain(deliver=lambda *_:None)['delivered'] == 0
    assert not calls
    clock.value += timedelta(minutes=2)
    assert service.drain(deliver=lambda *_:None)['delivered'] == 1
    assert len(calls) == 1
    args = tracking._config().model_dump()
    args['duration_units_per_day'] = 2
    tracking.configure(args)
    clock.value += timedelta(seconds=11)
    assert post(service, token, secret, body(clock, video='12345678901')).status_code == 204
    assert service.drain(deliver=lambda *_:pytest.fail('Quota was bypassed'))['delivered'] == 0
    assert store.get_sync_cursor('youtube_creator_feed','me:budget')['state']['duration_units'] == 2
    assert any('quota' in warning for warning in service.status().warnings)


def test_profile_capacity_does_not_suppress_push_or_rss_reconciliation(setup, monkeypatch):
    _, clock, hub, tracking, service = setup
    args = tracking._config().model_dump()
    args.update(max_channels=1, rules=[*args['rules'],dict(channel_id=C2,name='Second',relationship='long_term')])
    tracking.configure(args)
    token, secret = activate(service, hub, channel=C2)
    clock.value += timedelta(seconds=10)
    tracking.duration_provider = lambda ids: {video:{'channel_id':C2,'duration_seconds':600} for video in ids}
    assert post(service, token, secret, body(clock, channel=C2)).status_code == 204
    tracking.reader = type('Reader', (), {'fetch': lambda self, *_:{'entries':[]}})()
    calls = []
    assert service.drain(deliver=lambda *args:calls.append(args))['delivered'] == 1
    monkeypatch.setenv('YOUTUBE_PUSH_CALLBACK_BASE', BASE)
    from agent.config import get_settings
    get_settings.cache_clear()
    assert tracking.refresh(deliver=lambda *args:calls.append(args))['delivered'] == 0
    assert len(calls) == 1


def test_quiet_subscription_is_saved_for_recall_without_notification(setup):
    store, clock, hub, _, service = setup
    store.upsert_source(SourceItemInput(kind='youtube_subscription', external_id='quiet', account_id='me',
        title='Quiet creator', metadata={'subscribed_channel_id':C2}))
    token, secret = activate(service, hub, channel=C2)
    clock.value += timedelta(seconds=10)
    assert post(service, token, secret, body(clock, channel=C2)).status_code == 204
    assert service.drain(deliver=lambda *_:pytest.fail('Quiet subscription pinged'))['delivered'] == 0
    assert service.tracking.saved_uploads(creator='Quiet creator')['uploads'][0]['video_id'] == VIDEO


def test_changed_tunnel_can_register_again_even_if_old_url_is_unreachable(setup):
    _, _, hub, tracking, service = setup
    _, secret = activate(service, hub)
    changed = YouTubePushDelivery(tracking=tracking, callback_base='https://replacement.example.com', hub=hub)
    # Rotating an endpoint must not briefly report an empty or fully active list.
    assert changed.status().desired_channels == 1
    assert changed.status().active_channels == 0
    assert changed.status().pending_channels == 1
    changed.reconcile()
    changed.reconcile()
    assert hub.calls[-1]['hub.mode'] == 'subscribe'
    assert hub.calls[-1]['hub.callback'].startswith('https://replacement.example.com/')
    assert hub.calls[-1]['hub.secret'] == secret


def test_automation_pause_and_permission_gate_apply_to_push_worker(setup, monkeypatch, tmp_path):
    import asyncio
    from agent.plugins import youtube_push
    from agent.automations import api as automations_api
    from agent.automations.store import AutomationStore
    from agent.config import get_settings
    store = AutomationStore(tmp_path/'automations')
    automation = store.create(name='YT', instructions='Track creators', schedule={'kind':'interval','seconds':900},
        destination={'kind':'notification'}, builtin=True, builtin_key='youtube_creator_tracking', state='paused')
    monkeypatch.setattr(automations_api, 'get_store', lambda:store)
    monkeypatch.setenv('YOUTUBE_PUSH_CALLBACK_BASE', BASE)
    get_settings.cache_clear()
    monkeypatch.setattr(youtube_push, 'YouTubePushDelivery', lambda:pytest.fail('Paused task performed push work'))
    asyncio.run(youtube_push.run_push_tick())
    store.update(automation['id'], state='active')
    asyncio.run(youtube_push.run_push_tick())  # full_access still false


def test_schema_upgrade_and_status_preserve_state_without_disclosing_credentials(setup):
    import sqlite3
    store, _, hub, _, service = setup
    activate(service, hub)
    public = service.status().model_dump_json()
    fields = hub.calls[0]
    assert fields['hub.secret'] not in public
    assert fields['hub.callback'] not in public
    with sqlite3.connect(store.db_path) as connection:
        connection.execute('PRAGMA user_version = 15')
    reopened = KnowledgeStore(store.db_path, store.db_path.parent/'blobs')
    assert reopened.youtube_push_subscriptions('me')[0]['channel_id'] == C1


def test_runtime_commits_canonical_notification_and_batch_receipt_once(setup, monkeypatch, tmp_path):
    import asyncio
    from agent.plugins import youtube_push
    from agent.automations import api as automations_api
    from agent.automations.store import AutomationStore
    from agent.config import get_settings
    _, clock, hub, _, service = setup
    token, secret = activate(service, hub)
    clock.value += timedelta(seconds=10)
    assert post(service, token, secret, body(clock)).status_code == 204
    store = AutomationStore(tmp_path/'automations')
    automation = store.create(name='YT', instructions='Track creators', schedule={'kind':'interval','seconds':900},
        destination={'kind':'notification'}, permission={'full_access':True}, builtin=True, builtin_key='youtube_creator_tracking')
    monkeypatch.setattr(automations_api, 'get_store', lambda:store)
    monkeypatch.setattr(youtube_push, 'YouTubePushDelivery', lambda:service)
    monkeypatch.setenv('YOUTUBE_PUSH_CALLBACK_BASE', BASE)
    get_settings.cache_clear()
    asyncio.run(youtube_push.run_push_tick())
    asyncio.run(youtube_push.run_push_tick())
    assert store.notification_snapshot()['unread_count'] == 1
    assert store.notification_snapshot()['items'][0]['url'].endswith(VIDEO)
    assert len(store.runs(automation['id'])) == 1
    assert 'YouTube push: 1 qualified uploads' in store.runs(automation['id'])[0]['output']
    assert not (tmp_path/'ui'/'conversations.json').exists()


def test_exclusion_changed_during_metadata_read_is_rechecked_before_delivery(setup):
    _, clock, hub, tracking, service = setup
    token, secret = activate(service, hub)
    clock.value += timedelta(seconds=10)
    assert post(service, token, secret, body(clock)).status_code == 204
    def metadata(ids):
        args = tracking._config().model_dump()
        args['rules'][0]['relationship'] = 'excluded'
        tracking.configure(args)
        return {video:{'channel_id':C1,'duration_seconds':600} for video in ids}
    tracking.duration_provider = metadata
    assert service.drain(deliver=lambda *_:pytest.fail('Changed exclusion was ignored'))['delivered'] == 0


def test_malformed_signature_and_worker_lock_leave_queue_safe(setup):
    store, clock, hub, _, service = setup
    token, secret = activate(service, hub)
    clock.value += timedelta(seconds=10)
    with pytest.raises(HTTPException) as rejected:
        service.receive(token, body(clock), 'sha1=é')
    assert rejected.value.status_code == 403
    assert post(service, token, secret, body(clock)).status_code == 204
    store.youtube_tracking_lock('me', 'other-worker', clock().timestamp(), duration=600)
    assert service.drain(deliver=lambda *_:pytest.fail('Worker lease ignored'))['status'] == 'busy'
    clock.value += timedelta(seconds=601)
    assert service.drain(deliver=lambda *_:None)['delivered'] == 1


def test_failed_hub_request_is_reserved_and_retries_with_sanitized_status(setup):
    _, clock, hub, _, service = setup
    def fail(fields):
        hub.calls.append(fields)
        raise RuntimeError('PRIVATE PROVIDER BODY')
    hub.subscribe = fail
    assert service.reconcile()['requests'] == 1
    assert service.reconcile()['requests'] == 0
    assert service.status().active_channels == 0
    assert 'PRIVATE PROVIDER BODY' not in service.status().model_dump_json()
    clock.value += timedelta(seconds=121)
    assert service.reconcile()['requests'] == 1


def test_subscription_refresh_uses_existing_owner_and_is_account_scoped_and_bounded(setup, monkeypatch):
    from agent.plugins import youtube_push, youtube_runtime
    store, clock, _, tracking, _ = setup
    calls = []
    monkeypatch.setattr(youtube_runtime, 'youtube_status', lambda:{'channel_id':'other','connected':True})
    monkeypatch.setattr(youtube_runtime, 'YouTubeKnowledgeSync', lambda:pytest.fail('Wrong account was synced'))
    youtube_push.refresh_subscription_snapshot(tracking)
    assert store.get_sync_cursor('youtube_push_subscription_sync','me')['state']['status'] == 'account_mismatch'
    clock.value += timedelta(hours=6)
    monkeypatch.setattr(youtube_runtime, 'youtube_status', lambda:{'channel_id':'me','connected':True})
    class Sync:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {'status':'completed'}
    monkeypatch.setattr(youtube_runtime, 'YouTubeKnowledgeSync', Sync)
    youtube_push.refresh_subscription_snapshot(tracking)
    youtube_push.refresh_subscription_snapshot(tracking)
    assert len(calls) == 1
    assert calls[0]['requested_by'] == 'automation'
    assert store.get_sync_cursor('youtube_push_subscription_sync','me')['state']['status'] == 'ready'


def test_push_status_route_is_typed_uncached_and_redacted(setup, monkeypatch):
    from fastapi import FastAPI
    from agent.plugins import youtube_push, youtube_api
    _, _, hub, _, service = setup
    activate(service, hub)
    monkeypatch.setattr(youtube_push, 'YouTubePushDelivery', lambda:service)
    app = FastAPI()
    app.include_router(youtube_api.router, prefix='/api')
    with TestClient(app) as client:
        response = client.get('/api/plugins/youtube/creators/push')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.json()['active_channels'] == 1
    assert hub.calls[0]['hub.secret'] not in response.text


def test_rejected_google_grant_is_explicit_and_does_not_consume_repeated_duration_budget(setup,monkeypatch):
    from agent.plugins import youtube_runtime
    store,clock,hub,tracking,service=setup
    config=tracking._config().model_dump();config['subscription_account_id']=C1;tracking.configure(config)
    tracking.duration_provider=None
    monkeypatch.setattr(youtube_runtime,'youtube_status',lambda:{'connected':True,'authorization_required':True})
    monkeypatch.setattr(youtube_runtime,'youtube_client',lambda:pytest.fail('Known rejected authorization retried provider'))
    token,secret=activate(service,hub);clock.value+=timedelta(seconds=10)
    assert post(service,token,secret,body(clock)).status_code==204
    for _ in range(3):
        service.drain(deliver=lambda *_:pytest.fail('Unverified upload delivered'))
        clock.value+=timedelta(seconds=15)
    budget=(store.get_sync_cursor('youtube_creator_feed','me:budget') or {}).get('state') or {}
    assert budget.get('duration_units',0)==0
    status=service.status()
    assert status.authorization_required
    assert any('Reconnect YouTube' in warning for warning in status.warnings)


def test_reconnect_releases_failed_duration_and_subscription_waits_without_resetting_budget(setup,monkeypatch):
    from agent.knowledge.models import SyncCursorInput
    store,clock,hub,tracking,service=setup
    config=tracking._config().model_dump();config['subscription_account_id']=C1;tracking.configure(config)
    token,secret=activate(service,hub);clock.value+=timedelta(seconds=10)
    post(service,token,secret,body(clock))
    tracking.duration_provider=lambda _:{}
    service.drain(deliver=lambda *_:None)
    waiting=(clock.value+timedelta(hours=1)).isoformat()
    duration=store.get_sync_cursor('youtube_upload_durations','me')['state']
    duration['provider_next_at']=waiting;duration['videos'][VIDEO]['next_at']=waiting
    store.save_sync_cursor(SyncCursorInput(connector='youtube_upload_durations',account_id='me',state=duration))
    store.save_sync_cursor(SyncCursorInput(connector='youtube_push_subscription_sync',account_id='me',state={'status':'unavailable','next_at':waiting}))
    reserved=store.get_sync_cursor('youtube_creator_feed','me:budget')['state']['duration_units']
    assert not tracking.resume_after_authorization(C2)
    assert store.get_sync_cursor('youtube_upload_durations','me')['state']['provider_next_at']==waiting
    assert tracking.resume_after_authorization(C1)
    assert store.get_sync_cursor('youtube_creator_feed','me:budget')['state']['duration_units']==reserved
    assert store.get_sync_cursor('youtube_push_subscription_sync','me')['state']['status']=='pending'
    tracking.duration_provider=lambda ids:{video:{'channel_id':C1,'duration_seconds':600} for video in ids}
    clock.value+=timedelta(seconds=15)
    delivered=[]
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==1
    assert len(delivered)==1


def test_reconnect_recovery_survives_busy_worker_and_is_retried_by_normal_tick(setup):
    store,clock,hub,tracking,service=setup
    config=tracking._config().model_dump();config['subscription_account_id']=C1;tracking.configure(config)
    token,secret=activate(service,hub);clock.value+=timedelta(seconds=10)
    post(service,token,secret,body(clock))
    assert store.youtube_tracking_lock('me','existing-worker',clock().timestamp(),duration=60)
    assert not tracking.resume_after_authorization(C1)
    assert store.get_sync_cursor('youtube_push_reauthorization','me')['state']['pending']
    store.youtube_tracking_unlock('me','existing-worker')
    delivered=[]
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==1
    assert not store.get_sync_cursor('youtube_push_reauthorization','me')['state']['pending']
