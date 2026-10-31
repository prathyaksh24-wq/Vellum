"""Hosted replay into the canonical upload owner; no Google/Cloudflare credentials."""
from contextlib import closing
from datetime import UTC, datetime, timedelta
import json

import httpx
import pytest

from agent.knowledge.models import ObservationActor, ObservationInput, SourceItemInput
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_creator_tracking import YouTubeCreatorTracking
from agent.plugins.youtube_push import YouTubePushDelivery
from agent.plugins.youtube_relay import YouTubeRelayClient

BASE='https://personal.example.workers.dev'
CHANNEL='UC'+'a'*22
VIDEO='abcdefghijk'
NOW=datetime(2026,10,17,12,tzinfo=UTC)


@pytest.fixture
def relay(tmp_path):
    store=KnowledgeStore(tmp_path/'knowledge.db',tmp_path/'blobs')
    moment=[NOW]
    tracker=YouTubeCreatorTracking(store=store,clock=lambda:moment[0])
    tracker.configure({'account_id':'me','history_accounts':['me'],'enabled':True,'min_duration_seconds':180,
        'api_fallback':False,'discovery_units_per_day':0,
        'rules':[{'channel_id':CHANNEL,'name':'Creator','relationship':'long_term'}]})
    tracker.duration_provider=lambda ids:{video:{'channel_id':CHANNEL,'duration_seconds':600} for video in ids}
    service=YouTubePushDelivery(tracking=tracker,callback_base=BASE)
    requests=[]
    entries=[]
    remote={'contract_version':1,'epoch':'epoch1','revision':'manifest','desired_channels':1,'active_channels':1,
        'last_received_at':int(NOW.timestamp()),'last_maintenance':int(NOW.timestamp()),
        'buffered_events':0,'stored_bytes':0,'retention_days':7,'warnings':[],
        'channels':[{'channel_id':CHANNEL,'lease_expires':int(NOW.timestamp())+86400}]}
    def backend(request):
        requests.append(request)
        assert request.headers['Authorization']=='Bearer '+'A'*43
        if request.url.path=='/v1/channels':
            body=json.loads(request.content)
            assert set(body)=={'contract_version','channels'}
            assert all(set(item)=={'channel_id','token','secret'} for item in body['channels'])
            return httpx.Response(200,json={'contract_version':1,'revision':'manifest','desired_channels':len(body['channels'])})
        if request.url.path=='/v1/status':return httpx.Response(200,json=remote)
        if request.url.path=='/v1/ack':
            body=json.loads(request.content)
            # The server must only receive a checkpoint already durably saved.
            saved=store.get_sync_cursor('youtube_push_relay','me')['state']
            assert saved['after']==body['after'] and saved['epoch']==body['epoch']
            return httpx.Response(200,json={**body,'pruned':0})
        after=int(request.url.params['after'])
        page=[entry for entry in entries if entry['id']>after][:20]
        return httpx.Response(200,json={'contract_version':1,'epoch':remote['epoch'],'gap':False,'retention_floor':0,
            'events':page,'next_after':page[-1]['id'] if page else after,'has_more':False})
    client=YouTubeRelayClient(service,token='A'*43,request_backend=httpx.MockTransport(backend))
    service.hosted=True;service.relay=client
    return store,moment,tracker,service,client,requests,entries,remote


def event(*,identity=1,video=VIDEO,channel=CHANNEL,published=NOW):
    return {'id':identity,'channel_id':channel,'received_at':int(NOW.timestamp()),'bytes':400,
        'body':f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
        f'<entry><yt:videoId>{video}</yt:videoId><yt:channelId>{channel}</yt:channelId><title>Upload</title>'
        f'<author><name>Creator</name></author><published>{published.isoformat()}</published></entry></feed>'}


def test_full_302_target_manifest_is_sent_without_private_profile_data_or_capacity_truncation(relay):
    store,_,tracker,service,_,requests,_,_=relay
    for index in range(301):
        channel='UC'+str(index).zfill(22)
        store.upsert_source(SourceItemInput(kind='youtube_subscription',external_id=channel,account_id='me',title='Saved',
            metadata={'subscribed_channel_id':channel}))
    service.reconcile()
    manifest=json.loads(next(request.content for request in requests if request.method=='PUT'))
    assert len(manifest['channels'])==302
    public=service.status().model_dump_json()
    assert 'A'*43 not in public
    assert service.status().saved_subscriptions==301
    assert service.status().transport=='hosted'
    assert 'history_accounts' not in json.dumps(manifest)
    service.reconcile()
    assert sum(request.method=='PUT' for request in requests)==1


def test_offline_event_is_committed_locally_then_delivered_once_with_live_duration_gate(relay):
    store,moment,_,service,client,_,entries,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1);entries.append(event())
    delivered=[]
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==1
    assert len(delivered)==1 and VIDEO in delivered[0][1]
    assert client.state()['after']==1
    assert service.status().last_relay_sync_at
    moment[0]+=timedelta(seconds=16)
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==0
    assert len(delivered)==1
    assert store.youtube_tracking_saved_uploads('me',[CHANNEL])[0]['video_id']==VIDEO


def test_unknown_duration_stays_pending_and_short_video_never_pings(relay):
    store,moment,tracker,service,_,_,entries,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1);entries.append(event())
    tracker.duration_provider=lambda ids:{}
    assert service.drain(deliver=lambda *_:pytest.fail('Unknown duration pinged'))['delivered']==0
    assert store.youtube_tracking_uploads('me',pending=True)[0]['video_id']==VIDEO
    moment[0]+=timedelta(minutes=3)
    tracker.duration_provider=lambda ids:{video:{'channel_id':CHANNEL,'duration_seconds':180} for video in ids}
    assert service.drain(deliver=lambda *_:pytest.fail('Short video pinged'))['delivered']==0
    assert not store.youtube_tracking_uploads('me',pending=True)


def test_catchup_older_than_24h_is_saved_quietly_instead_of_becoming_a_fresh_ping(relay):
    store,moment,_,service,client,_,entries,_=relay
    service.reconcile();moment[0]+=timedelta(days=2);entries.append(event())
    assert service.drain(deliver=lambda *_:pytest.fail('Old catchup pinged'))['delivered']==0
    assert client.state()['after']==1
    assert store.youtube_tracking_saved_uploads('me',[CHANNEL])[0]['status']=='baseline'


def test_failed_local_commit_does_not_advance_checkpoint_and_replay_remains_deduplicated(relay,monkeypatch):
    store,moment,_,service,client,requests,entries,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1);entries.extend([event(),event(identity=2,video='12345678901')])
    original=store.youtube_push_enqueue
    def partial(account,channel,items,now):
        if items[0]['video_id']=='12345678901':raise RuntimeError('Local write failed')
        return original(account,channel,items,now)
    monkeypatch.setattr(store,'youtube_push_enqueue',partial)
    with pytest.raises(RuntimeError):client.pull()
    assert client.state().get('after',0)==0
    assert not any(request.url.path=='/v1/ack' for request in requests)
    monkeypatch.setattr(store,'youtube_push_enqueue',original);moment[0]+=timedelta(minutes=2)
    client.pull()
    assert client.state()['after']==2
    with closing(store._connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM youtube_upload_outbox WHERE account_id='me'").fetchone()[0]==2


def test_rotation_ack_retries_without_rewinding_committed_local_uploads(relay,monkeypatch):
    _,moment,_,service,client,requests,entries,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1);entries.append(event())
    original=client._request
    def fail_ack(method,path,**kwargs):
        if path=='/v1/ack':raise RuntimeError('Network unavailable')
        return original(method,path,**kwargs)
    monkeypatch.setattr(client,'_request',fail_ack)
    client.pull()
    assert client.state()['after']==1
    assert client.state().get('rotation_warning')
    monkeypatch.setattr(client,'_request',original);moment[0]+=timedelta(minutes=6);client.pull()
    assert client.state()['after']==1
    assert not client.state().get('rotation_warning')
    acks=[request for request in requests if request.url.path=='/v1/ack'];assert len(acks)==1
    moment[0]+=timedelta(seconds=16);client.pull()
    assert sum(request.url.path=='/v1/ack' for request in requests)==1


def test_hosted_outage_does_not_block_delivery_of_uploads_already_saved_locally(relay,monkeypatch):
    store,moment,_,service,client,_,_,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1)
    store.youtube_push_enqueue('me',CHANNEL,service.parse(event()['body'].encode(),CHANNEL),moment[0].isoformat())
    monkeypatch.setattr(client,'_request',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('Receiver unavailable')))
    delivered=[]
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==1
    assert len(delivered)==1
    assert service.status().status=='partial'


def test_channel_notification_dislike_reduces_volume_without_excluding_topic_and_survives_restart(relay):
    store,moment,tracker,service,_,_,entries,_=relay
    config=tracker._config().model_dump();config['conversation_topics']=True
    config['rules'][0].update(name='ChessBase India');tracker.configure(config)
    tracker.conversation_provider=lambda:[{'updated_at':moment[0].isoformat(),'messages':[{'role':'user',
        'text':"I don't like receiving notifications from ChessBase India"}]}]
    service.reconcile();moment[0]+=timedelta(minutes=1)
    entries.extend([event(),event(identity=2,video='12345678901')])
    delivered=[]
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==1
    creator=tracker.snapshot()['creators'][0]
    assert creator['state']=='monitoring' and creator['notification_frequency']=='reduced'
    assert 'chess' not in {topic for topic,value in tracker.snapshot()['topic_evidence'].items() if value.get('excluded')}
    assert len(store.youtube_tracking_saved_uploads('me',[CHANNEL]))==2
    # A new runtime instance reads the persisted channel cooldown.
    restarted=YouTubeCreatorTracking(store=store,clock=tracker.clock,conversation_provider=tracker.conversation_provider,
        duration_provider=tracker.duration_provider)
    service.tracking=restarted;moment[0]+=timedelta(hours=1);entries.append(event(identity=3,video='00000000003',published=moment[0]))
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==0
    moment[0]+=timedelta(days=1);entries.append(event(identity=4,video='00000000004',published=moment[0]))
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==1
    assert len(delivered)==2


@pytest.mark.parametrize('text,expected',[
    ('Mute notifications from ChessBase India','muted'),
    ('Stop notifications from ChessBase India','muted'),
    ('Send fewer notifications from ChessBase India','reduced'),
    ('Send more notifications from ChessBase India','adaptive'),
])
def test_explicit_frequency_language_has_channel_scope(relay,text,expected):
    _,moment,tracker,_,_,_,_,_=relay
    config=tracker._config().model_dump();config['conversation_topics']=True
    config['rules'][0].update(name='ChessBase India');tracker.configure(config)
    tracker.conversation_provider=lambda:[{'updated_at':moment[0].isoformat(),'messages':[{'role':'user','text':text}]}]
    creator=tracker.snapshot()['creators'][0]
    assert creator['notification_frequency']==expected and creator['state']=='monitoring'


def test_assistant_hypothetical_and_private_notification_preferences_are_ignored(relay):
    _,moment,tracker,_,_,_,_,_=relay
    config=tracker._config().model_dump();config['conversation_topics']=True;tracker.configure(config)
    tracker.conversation_provider=lambda:[{'updated_at':moment[0].isoformat(),'messages':[
        {'role':'assistant','text':'Mute notifications from Creator'},
        {'role':'user','text':'For example, send fewer notifications from Creator'}]},
        {'memory_enabled':False,'updated_at':moment[0].isoformat(),'messages':[{'role':'user','text':'Mute notifications from Creator'}]}]
    assert tracker.snapshot()['creators'][0]['notification_frequency']=='adaptive'


def test_rediscovery_uses_established_past_watches_and_sends_at_most_one_weekly_ping(relay):
    store,moment,tracker,service,_,_,entries,_=relay
    config=tracker._config().model_dump();config['rediscovery_notifications']=True
    other='UC'+'b'*22
    config['rules'][0].update(relationship='auto',name='Old favourite')
    config['rules'].append({'channel_id':other,'name':'Earlier creator','relationship':'auto'})
    tracker.configure(config)
    source=store.upsert_source(SourceItemInput(kind='youtube_takeout_archive',external_id='archive',account_id='me'))['source_id']
    store.record_observations([ObservationInput(origin='youtube_takeout',action='youtube.watch',actor=ObservationActor.IMPORTED,
        source_id=source,event_key='old-'+channel+str(index),observed_at=NOW-timedelta(days=100+index),
        payload={'video_id':str(index+100*number).zfill(11),'channel_id':channel,'channel_title':name})
        for number,(channel,name) in enumerate([(CHANNEL,'Old favourite'),(other,'Earlier creator')]) for index in range(10)])
    tracker.duration_provider=lambda ids:{video:{'channel_id':other if video=='12345678901' else CHANNEL,'duration_seconds':600} for video in ids}
    service.reconcile();moment[0]+=timedelta(minutes=1)
    entries.extend([event(published=NOW+timedelta(seconds=1)),event(identity=2,video='12345678901',channel=other)])
    delivered=[]
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==1
    assert 'Rediscover' in delivered[0][1] and 'Old favourite' in delivered[0][1]
    assert len(store.youtube_tracking_saved_uploads('me',[CHANNEL,other]))==2
    moment[0]+=timedelta(days=1);entries.append(event(identity=3,video='00000000003',published=moment[0]))
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==0
    # One creator is not resurfaced repeatedly every week.
    moment[0]+=timedelta(days=7);entries.append(event(identity=4,video='00000000004',published=moment[0]))
    assert service.drain(deliver=lambda *args:delivered.append(args))['delivered']==0
    assert tracker.snapshot()['creators'][0]['state']=='quiet'
    moment[0]+=timedelta(days=100)
    config['rules'][0]['relationship']='former';config['rules'][1]['notification_frequency']='muted'
    tracker.configure(config)
    assert not any(creator['rediscovery'] for creator in tracker.snapshot()['creators'])


def test_channel_feedback_is_durable_and_later_feedback_can_restore_frequency(relay):
    _,moment,tracker,_,_,_,_,_=relay
    config=tracker._config().model_dump();config['conversation_topics']=True;tracker.configure(config)
    tracker.conversation_provider=lambda:[{'updated_at':moment[0].isoformat(),'messages':[{'role':'user','text':'Send fewer notifications from Creator'}]}]
    assert tracker.snapshot()['creators'][0]['notification_frequency']=='reduced'
    tracker.conversation_provider=lambda:[];moment[0]+=timedelta(days=40)
    assert tracker.snapshot()['creators'][0]['notification_frequency']=='reduced'
    tracker.conversation_provider=lambda:[{'updated_at':moment[0].isoformat(),'messages':[{'role':'user','text':'Send more notifications from Creator'}]}]
    assert tracker.snapshot()['creators'][0]['notification_frequency']=='adaptive'


def test_removed_or_unknown_channels_are_not_imported_and_malformed_events_do_not_poison_sync(relay):
    store,moment,_,service,client,_,entries,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1)
    entries.extend([dict(event(),body='<!DOCTYPE feed><feed/>'),event(identity=2,channel='UC'+'b'*22),event(identity=3)])
    client.pull()
    assert client.state()['after']==3
    assert client.state()['rejected_events']==[1]
    assert store.youtube_push_queue_status('me')==1


def test_database_recreation_resets_sequence_and_requests_full_manifest_again(relay):
    _,moment,_,service,client,requests,entries,remote=relay
    service.reconcile();moment[0]+=timedelta(minutes=1);entries.append(event(identity=100));client.pull()
    remote.update(epoch='epoch2',revision='');entries[:]=[event()];moment[0]+=timedelta(minutes=1)
    client.pull();assert client.state()['after']==0
    assert client.state()['gap']
    client.pull();assert client.state()['after']==1
    service.reconcile();service.reconcile()
    assert sum(request.method=='PUT' for request in requests)==2


def test_remote_error_is_sanitized_and_never_redirects_bearer_credentials(relay):
    _,_,_,service,client,requests,_,_=relay
    def fail(request):return httpx.Response(302,headers={'Location':'https://other.example/PRIVATE'})
    client.request_backend=httpx.MockTransport(fail)
    with pytest.raises(RuntimeError):service.reconcile()
    public=service.status().model_dump_json()
    assert 'PRIVATE' not in public and 'A'*43 not in public
    assert 'deferred' in public


def test_known_daily_database_limit_is_visible_without_echoing_provider_body(relay):
    _,moment,_,service,client,_,_,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1)
    client.request_backend=httpx.MockTransport(lambda _:httpx.Response(503,json={
        'code':'daily_database_limit','error':'PRIVATE PROVIDER BODY'}))
    with pytest.raises(RuntimeError):client.pull()
    public=service.status().model_dump_json()
    assert 'daily allowance exhausted' in public and 'PRIVATE' not in public


def test_settings_redacts_token_and_hosted_mode_uses_receiver_instead_of_local_tunnel(relay,monkeypatch):
    from agent.config import get_settings
    _,_,tracker,_,_,_,_,_=relay
    monkeypatch.setenv('YOUTUBE_PUSH_RELAY_BASE',BASE);monkeypatch.setenv('YOUTUBE_PUSH_RELAY_TOKEN','A'*43)
    get_settings.cache_clear()
    try:
        service=YouTubePushDelivery(tracking=tracker)
        assert service.hosted and service.callback_base==BASE
        assert 'A'*43 not in repr(get_settings())
        assert 'A'*43 not in service.status().model_dump_json()
    finally:get_settings.cache_clear()


def test_fast_worker_does_not_spend_duration_quota_on_quiet_baselines_and_backs_off_unknowns(relay):
    store,moment,tracker,service,_,_,entries,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1)
    old=event(published=NOW-timedelta(days=3))
    store.youtube_push_enqueue('me',CHANNEL,service.parse(old['body'].encode(),CHANNEL),moment[0].isoformat())
    store.youtube_push_promote('me',CHANNEL,VIDEO,'baseline')
    tracker.duration_provider=lambda _:pytest.fail('Quiet baseline consumed fast duration quota')
    service.drain(deliver=lambda *_:None)
    # One unresolved new upload must not consume all 200 calls by mid-morning.
    moment[0]+=timedelta(seconds=16)
    entries.append(event(video='12345678901'))
    calls=[]
    def unavailable(ids):calls.append(ids);return {}
    tracker.duration_provider=unavailable
    end=moment[0]+timedelta(hours=12)
    while moment[0]<end:
        service.drain(deliver=lambda *_:pytest.fail('Unverified duration pinged'))
        assert len(calls)<20
        cache=store.get_sync_cursor('youtube_upload_durations','me')['state']['videos']['12345678901']
        moment[0]=datetime.fromisoformat(cache['next_at'])+timedelta(seconds=1)
    assert len(calls)<20
    assert all(VIDEO not in ids for ids in calls)


def test_quota_deferred_upload_does_not_rebuild_the_large_profile_every_five_seconds(relay,monkeypatch):
    from agent.knowledge.models import SyncCursorInput
    store,moment,tracker,service,_,_,entries,_=relay
    service.reconcile();moment[0]+=timedelta(minutes=1);entries.append(event())
    tracker.duration_provider=lambda _:{}
    service.drain(deliver=lambda *_:None)
    store.save_sync_cursor(SyncCursorInput(connector='youtube_creator_feed',account_id='me:budget',
        state={'day':moment[0].date().isoformat(),'duration_units':tracker._config().duration_units_per_day}))
    monkeypatch.setattr(tracker,'snapshot',lambda **_:pytest.fail('Quota-deferred worker rebuilt the profile'))
    for _ in range(3):
        moment[0]+=timedelta(seconds=15)
        assert service.drain(deliver=lambda *_:pytest.fail('Quota-deferred upload pinged'))['status']=='deferred'
