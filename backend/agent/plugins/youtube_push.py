"""YouTube WebSub transport over the canonical creator tracker and upload outbox.

The ingress app deliberately mounts no Vellum API or documentation routes. Run
it on loopback behind an HTTPS tunnel. The existing backend scheduler owns
renewals and outbox delivery; this app only verifies and durably accepts events.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
from urllib.parse import urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from agent.contracts.youtube_push import YouTubePushStatus
from agent.knowledge.models import SyncCursorInput
from agent.plugins.youtube_creator_tracking import ATOM, YT, CHANNEL, VIDEO, YouTubeCreatorTracking, _time

logger = logging.getLogger(__name__)
HUB = 'https://pubsubhubbub.appspot.com/subscribe'
TOPIC = 'https://www.youtube.com/xml/feeds/videos.xml?channel_id='
MAX_BODY = 262144
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')


def callback_origin(value):
    value = value.strip().rstrip('/')
    if not value:
        return ''
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path or parsed.port not in (None, 443)
            or parsed.hostname in {'localhost', 'localhost.localdomain'} or '.' not in parsed.hostname):
        raise ValueError('Push delivery requires a public HTTPS origin without a path or credentials.')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('Push delivery requires a public HTTPS origin.')
    return value


class YouTubeHub:
    def subscribe(self, fields):
        # Fixed Google destination; no operator-supplied hub URL or redirects.
        with httpx.Client(timeout=httpx.Timeout(8, connect=3), follow_redirects=False) as client:
            response = client.post(HUB, data=fields)
        if response.status_code != 202:
            raise RuntimeError('YouTube hub registration was not accepted.')


class YouTubePushDelivery:
    def __init__(self, *, tracking=None, callback_base=None, hub=None, clock=None, relay=None):
        self.hosted = relay is not None
        if callback_base is None:
            from agent.config import get_settings
            settings = get_settings()
            self.hosted = bool(settings.youtube_push_relay_base)
            callback_base = settings.youtube_push_relay_base or settings.youtube_push_callback_base
        self.callback_base = callback_origin(callback_base)
        self.tracking = tracking if tracking is not None else YouTubeCreatorTracking()
        self.store = self.tracking.store
        self.clock = clock or self.tracking.clock
        self.hub = hub if hub is not None else YouTubeHub()
        self.relay = relay
        if self.hosted and self.relay is None:
            from agent.plugins.youtube_relay import YouTubeRelayClient
            self.relay = YouTubeRelayClient(self)

    def targets(self):
        config = self.tracking._config()
        if not config or not config.enabled:
            return {}
        targets = self.store.youtube_push_targets(config.subscription_account_id or config.account_id)
        # Capture active creators outside subscriptions too, without the RSS cap.
        profile = self.tracking.snapshot(limit=10000, apply_capacity=False)
        targets.update({item['channel_id']: item['name'] for item in profile['creators'] if item['state'] == 'monitoring' or item.get('rediscovery')})
        for rule in config.rules:
            if rule.channel_id and rule.relationship not in {'former', 'excluded'}:
                targets.setdefault(rule.channel_id, rule.name)
        return {channel: str(name)[:200] for channel, name in targets.items() if CHANNEL.fullmatch(channel)
                and not ((rule := self.tracking._rule(channel, name, config)) and rule.relationship in {'excluded','former'})}

    def status(self):
        config = self.tracking._config()
        result = YouTubePushStatus(endpoint_configured=bool(self.callback_base))
        result.transport = 'hosted' if self.hosted else 'local'
        if not self.callback_base:
            return result
        if not config or not config.enabled:
            result.status = 'paused'
            return result
        rows = self.store.youtube_push_subscriptions(config.account_id)
        subscriptions = self.store.youtube_push_targets(config.subscription_account_id or config.account_id)
        result.saved_subscriptions = len(subscriptions)
        result.eligible_subscriptions = sum(not ((rule := self.tracking._rule(channel,name,config)) and rule.relationship in {'excluded','former'})
                                            for channel,name in subscriptions.items() if CHANNEL.fullmatch(channel))
        desired = [row for row in rows if row.get('desired')]
        now = self.clock().timestamp()
        result.desired_channels = len(desired)
        result.active_channels = sum(row.get('base') == self.callback_base and row.get('lease_expires', 0) > now for row in desired)
        result.expired_channels = sum(bool(row.get('lease_expires')) and row['lease_expires'] <= now for row in desired)
        result.pending_channels = len(desired) - result.active_channels
        result.queued_uploads = self.store.youtube_push_queue_status(config.account_id, include_pending=True)
        result.last_received_at = max((row.get('last_received_at', '') for row in rows), default='')
        result.warnings = sorted({row['error'] for row in rows if row.get('error')})
        result.status = 'partial' if result.pending_channels or result.warnings else 'ready' if desired else 'awaiting_registration'
        duration = (self.store.get_sync_cursor('youtube_upload_durations', config.account_id) or {}).get('state') or {}
        result.authorization_required = self.tracking.authorization_required(config)
        if result.authorization_required:
            result.warnings.append('Reconnect YouTube with Google to resume video-length checks and upload notifications. Saved uploads are retained.')
            result.status = 'authorization_required'
        elif (_time(duration.get('provider_next_at')) or self.clock()) > self.clock():
            result.warnings.append('Duration metadata is unavailable; unverified uploads stay queued.')
            result.status = 'partial'
        budget = (self.store.get_sync_cursor('youtube_creator_feed', config.account_id + ':budget') or {}).get('state') or {}
        if config.min_duration_seconds and budget.get('day') == self.clock().date().isoformat() and budget.get('duration_units', 0) >= config.duration_units_per_day:
            result.warnings.append('Daily duration quota reached; unverified uploads wait for quota reset.')
            result.status = 'partial'
        sync = (self.store.get_sync_cursor('youtube_push_subscription_sync', config.account_id) or {}).get('state') or {}
        if sync.get('status') in {'unavailable', 'account_mismatch'}:
            result.warnings.append('Subscription refresh is unavailable; coverage uses the last saved account subscription list.')
            result.status = 'partial'
        health = (self.store.get_sync_cursor('youtube_push_delivery_health', config.account_id) or {}).get('state') or {}
        if health.get('error'):
            result.warnings.append(health['error'])
            result.status = 'partial'
        result = self.relay.decorate_status(result) if self.hosted else result
        if result.authorization_required:
            result.status = 'authorization_required'
        return result

    def reconcile(self):
        if not self.callback_base:
            return {'requests': 0}
        config = self.tracking._config()
        if not config:
            return {'requests': 0}
        owner, now = uuid4().hex, self.clock()
        lease = config.account_id + ':push-registration'
        if not self.store.youtube_tracking_lock(lease, owner, now.timestamp(), duration=120):
            return {'requests': 0}
        try:
            targets = self.targets()
            saved = {row['channel_id']: row for row in self.store.youtube_push_subscriptions(config.account_id)}
            for channel, name in targets.items():
                if channel not in saved:
                    self.store.youtube_push_register(config.account_id, channel, secrets.token_urlsafe(32), {
                        'name': name, 'base': self.callback_base, 'secret': secrets.token_hex(32),
                        'started_at': now.isoformat(), 'desired': True, 'mode': 'subscribe', 'next_at': 0})
            if self.hosted:
                return self.relay.reconcile(targets)
            requests = 0
            for row in sorted(self.store.youtube_push_subscriptions(config.account_id), key=lambda item: item.get('next_at', 0)):
                wanted = row['channel_id'] in targets
                base_changed = row['base'] != self.callback_base
                if base_changed:
                    # The old tunnel may no longer exist. Attempt retirement,
                    # but never wait for verification at an unreachable URL.
                    if requests >= 8:
                        break
                    try:
                        self.hub.subscribe({'hub.mode':'unsubscribe', 'hub.topic':TOPIC+row['channel_id'],
                            'hub.callback':row['base']+'/youtube/websub/'+row['token'], 'hub.verify':'async'})
                    except Exception:
                        pass  # The old lease also expires at the hub.
                    requests += 1
                    self.store.youtube_push_patch(row['token'], {'base': self.callback_base, 'desired': wanted,
                        'mode': 'subscribe' if wanted else 'unsubscribe', 'status': 'pending' if wanted else 'unsubscribed',
                        'next_at': 0, 'lease_expires': 0, 'renew_at': 0, 'error': ''})
                    continue
                mode = 'subscribe' if wanted else 'unsubscribe'
                if mode == 'unsubscribe' and row.get('status') == 'unsubscribed':
                    continue
                change = row.get('desired') != wanted or row.get('mode') != mode
                if not change and row.get('next_at', 0) > now.timestamp():
                    continue
                if wanted and not change and row.get('renew_at', 0) > now.timestamp():
                    continue
                if requests >= 8:
                    break
                fields = {'hub.mode': mode, 'hub.topic': TOPIC + row['channel_id'],
                    'hub.callback': row['base'] + '/youtube/websub/' + row['token'],
                    'hub.verify': 'async', 'hub.secret': row['secret'], 'hub.lease_seconds': '864000'}
                # Reserve before I/O; callback verification can arrive before POST returns.
                self.store.youtube_push_patch(row['token'], {'desired': wanted, 'mode': mode,
                    'requested_at': now.isoformat(), 'next_at': now.timestamp()+600,
                    'error': 'Awaiting YouTube callback verification.'})
                requests += 1
                try:
                    self.hub.subscribe(fields)
                except Exception:
                    failures = min(int(row.get('failures', 0))+1, 8)
                    self.store.youtube_push_patch(row['token'], {'error': 'YouTube hub registration unavailable.',
                        'failures': failures, 'next_at': now.timestamp()+min(60 * 2**failures, 3600)})
            return {'requests': requests}
        finally:
            self.store.youtube_tracking_unlock(lease, owner)

    def subscription(self, token):
        row = self.store.youtube_push_subscription(token) if TOKEN.fullmatch(token) else None
        config = self.tracking._config()
        if not row or not config or row['account_id'] != config.account_id or row.get('base') != self.callback_base:
            raise HTTPException(404, 'Unknown push subscription.')
        return row

    def verify(self, token, params):
        row = self.subscription(token)
        mode, topic, challenge = (params.get(key, '') for key in ('hub.mode', 'hub.topic', 'hub.challenge'))
        requested = _time(row.get('requested_at'))
        if (mode != row.get('mode') or mode not in {'subscribe','unsubscribe'} or topic != TOPIC + row['channel_id']
                or not requested or abs((self.clock()-requested).total_seconds()) > 600):
            raise HTTPException(404, 'Unknown verification request.')
        if not challenge or len(challenge) > 1024 or any(ord(char) < 32 or ord(char) > 126 for char in challenge):
            raise HTTPException(400, 'Invalid challenge.')
        if mode == 'unsubscribe':
            fields = {'status': 'unsubscribed', 'lease_expires': 0, 'renew_at': 0, 'error': ''}
        else:
            try:
                lease = int(params.get('hub.lease_seconds', ''))
            except ValueError:
                raise HTTPException(400, 'Invalid subscription lease.') from None
            if not 1 <= lease <= 31 * 86400:
                raise HTTPException(400, 'Invalid subscription lease.')
            now = self.clock().timestamp()
            fields = {'status': 'active', 'lease_expires': now+lease, 'renew_at': now+lease*0.8,
                      'next_at': now+lease*0.8, 'failures': 0, 'error': ''}
        self.store.youtube_push_patch(token, fields)
        return challenge

    def receive(self, token, raw, signature):
        row = self.subscription(token)
        config = self.tracking._config()
        rule = self.tracking._rule(row['channel_id'], row.get('name',''), config)
        if (not config.enabled or not row.get('desired') or row.get('lease_expires', 0) <= self.clock().timestamp()
                or rule and rule.relationship in {'excluded','former'}):
            raise HTTPException(404, 'Inactive push subscription.')
        if len(raw) > MAX_BODY:
            raise HTTPException(413, 'Callback body too large.')
        algorithm, _, supplied = signature.partition('=')
        valid_digest = algorithm in {'sha1','sha256'} and re.fullmatch(
            r'[0-9a-f]{' + ('40' if algorithm == 'sha1' else '64') + r'}', supplied)
        if not valid_digest or not hmac.compare_digest(
                hmac.new(row['secret'].encode(), raw, algorithm).hexdigest(), supplied):
            raise HTTPException(403, 'Invalid callback signature.')
        try:
            entries = self.parse(raw, row['channel_id'])
        except (ValueError, ET.ParseError, UnicodeError):
            raise HTTPException(400, 'Invalid upload event.') from None
        try:
            self.store.youtube_push_enqueue(config.account_id, row['channel_id'], entries, self.clock().isoformat())
        except OverflowError:
            raise HTTPException(503, 'Upload queue is full; retry later.') from None
        self.store.youtube_push_patch(token, {'last_received_at': self.clock().isoformat()})

    @staticmethod
    def parse(raw, channel):
        if b'\x00' in raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('Unsupported XML.')
        root = ET.fromstring(raw.decode('utf-8'))
        nodes = root.findall(ATOM+'entry')
        if root.tag != ATOM+'feed' or len(nodes) > 50:
            raise ValueError('Unsupported feed.')
        entries = []
        for node in nodes:
            video = node.findtext(YT+'videoId', '')
            published = _time(node.findtext(ATOM+'published', ''))
            title = node.findtext(ATOM+'title', '').strip()[:500]
            if node.findtext(YT+'channelId') != channel or not VIDEO.fullmatch(video) or not published or not title:
                raise ValueError('Invalid upload identity.')
            entries.append({'video_id': video, 'title': title, 'creator': node.findtext(ATOM+'author/'+ATOM+'name', '')[:200],
                            'published_at': published.isoformat()})
        return entries

    def drain(self, *, deliver):
        config = self.tracking._config()
        if not self.callback_base or not config or not config.enabled:
            return {'delivered': 0, 'status': 'paused'}
        recovery=(self.store.get_sync_cursor('youtube_push_reauthorization',config.account_id) or {}).get('state') or {}
        if recovery.get('pending') and not self.tracking.authorization_required(config):
            self.tracking.resume_after_authorization(recovery.get('channel_id',''))
        if self.hosted:
            try:
                self.relay.pull()
            except RuntimeError:
                # The adapter persists a visible sync warning and retains its
                # checkpoint. A cloud outage must not block already-local work.
                pass
        if not self.store.youtube_push_queue_status(config.account_id):
            pending = self.store.youtube_tracking_uploads(config.account_id, pending=True, limit=10000)
            if not pending:
                return {'delivered': 0, 'status': 'idle'}
            if config.min_duration_seconds:
                now = self.clock()
                verified = self.tracking._verified_durations(config)
                state = (self.store.get_sync_cursor('youtube_upload_durations', config.account_id) or {}).get('state') or {}
                budget = (self.store.get_sync_cursor('youtube_creator_feed', config.account_id+':budget') or {}).get('state') or {}
                quota_closed = budget.get('day') == now.date().isoformat() and budget.get('duration_units',0) >= config.duration_units_per_day
                provider_waiting = self.tracking.authorization_required(config) or (_time(state.get('provider_next_at')) or now) > now
                due = any(not (cached := (state.get('videos') or {}).get(item['video_id'])) or
                    cached.get('channel_id') != item['channel_id'] or
                    (cached.get('duration_seconds') is None and (_time(cached.get('next_at')) or now) <= now) or
                    (cached.get('duration_seconds') is not None and (_time(cached.get('checked_at')) or now) < now-timedelta(hours=6))
                    for item in pending)
                can_deliver = any(item['video_id']+':'+item['channel_id'] in verified for item in pending)
                if not can_deliver and (quota_closed or provider_waiting or not due):
                    return {'delivered':0,'status':'deferred','pending_duration_checks':len(pending)}
        now, owner = self.clock(), uuid4().hex
        if not self.store.youtube_tracking_lock(config.account_id, owner, now.timestamp(), duration=600):
            return {'delivered': 0, 'status': 'busy'}
        try:
            # Bring recent saved activity into the existing incremental
            # projection before deciding whether this upload deserves a ping.
            self.tracking.project(max_pages=2)
            profile = self.tracking.snapshot(limit=10000, apply_capacity=False)
            active = {item['channel_id']:item for item in profile['creators'] if item['state'] == 'monitoring' or item.get('rediscovery')}
            blocked = {topic for topic,value in profile['topic_evidence'].items() if value.get('excluded')}
            registrations = {row['channel_id']: row for row in self.store.youtube_push_subscriptions(config.account_id)}
            for item in self.store.youtube_push_queued(config.account_id):
                creator, row = active.get(item['channel_id']), registrations.get(item['channel_id'], {})
                rule = self.tracking._rule(item['channel_id'], item['creator'], config)
                published = _time(item['published_at'])
                excluded = rule and rule.relationship in {'excluded','former'}
                fresh = published and max(now-timedelta(days=2), _time(row.get('started_at')) or now) <= published <= now
                relevant = self.tracking._upload_relevant(creator, item['title'], blocked)
                status = 'suppressed' if excluded else 'pending' if fresh and relevant else 'baseline'
                self.store.youtube_push_promote(config.account_id, item['channel_id'], item['video_id'], status)
            budget = dict((self.store.get_sync_cursor('youtube_creator_feed', config.account_id+':budget') or {}).get('state') or {})
            pending = self.tracking._check_durations(config, active, budget, push=True)
            delivered = self.tracking._deliver_pending(config, active, blocked, deliver)
            self.store.youtube_tracking_prune(config.account_id, (now-timedelta(days=90)).isoformat())
            return {'delivered': delivered, 'pending_duration_checks': pending, 'status': 'partial' if pending else 'ready'}
        finally:
            self.store.youtube_tracking_unlock(config.account_id, owner)


def create_callback_app(*, service_provider=None):
    provider = service_provider or YouTubePushDelivery
    app = FastAPI(title='YouTube callback receiver', docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/youtube/websub/{token}', response_class=PlainTextResponse)
    async def verify(token: str, request: Request):
        return PlainTextResponse(await asyncio.to_thread(provider().verify, token, request.query_params),
                                 headers={'Cache-Control':'no-store'})

    @app.post('/youtube/websub/{token}', status_code=204)
    async def receive(token: str, request: Request):
        # Bound streamed input before parsing or retaining it, including chunked requests.
        raw = bytearray()
        try:
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > MAX_BODY:
                        raise HTTPException(413, 'Callback body too large.')
                    raw.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, 'Callback read deadline exceeded.') from None
        await asyncio.to_thread(provider().receive, token, bytes(raw), request.headers.get('x-hub-signature',''))
        return Response(status_code=204)

    return app


def refresh_subscription_snapshot(tracking):
    """Use the existing OAuth ingestion owner, at most once per six hours.

    No browser history, search terms, or profile inference is sent to Google.
    An account mismatch never silently links private subscription snapshots.
    """
    config = tracking._config()
    if not config or not config.enabled:
        return
    now = tracking.clock()
    subscription_account = config.subscription_account_id or config.account_id
    saved = (tracking.store.get_sync_cursor('youtube_push_subscription_sync', config.account_id) or {}).get('state') or {}
    if saved.get('subscription_account_id') == subscription_account and (_time(saved.get('next_at')) or now) > now:
        return
    state = {'next_at': (now+timedelta(hours=6)).isoformat(), 'status':'pending', 'subscription_account_id':subscription_account}
    tracking.store.save_sync_cursor(SyncCursorInput(connector='youtube_push_subscription_sync', account_id=config.account_id, state=state))
    try:
        from agent.plugins.youtube_runtime import YouTubeKnowledgeSync, youtube_status
        status = youtube_status()
        if status.get('channel_id') != subscription_account:
            state['status'] = 'account_mismatch'
        elif not status.get('connected') or status.get('authorization_required'):
            state['status'] = 'unavailable'
        else:
            key = f'youtube-push-subscriptions:{config.account_id}:{int(now.timestamp())//21600}'
            result = YouTubeKnowledgeSync().run(idempotency_key=key, requested_by='automation')
            state['status'] = 'ready' if result.get('status') == 'completed' else 'pending'
            if state['status'] == 'pending':
                state['next_at'] = (now+timedelta(minutes=1)).isoformat()
    except Exception:
        state['status'] = 'unavailable'
        state['next_at'] = (now+timedelta(hours=1)).isoformat()
    tracking.store.save_sync_cursor(SyncCursorInput(connector='youtube_push_subscription_sync', account_id=config.account_id, state=state))


async def run_push_tick(*, registration=False):
    """Called by the existing backend scheduler; paused automation policy still wins."""
    from agent.automations.api import get_store
    from agent.automations.runner import _deliver_creator_upload
    from agent.config import get_settings
    if not (get_settings().youtube_push_callback_base or get_settings().youtube_push_relay_base):
        return
    store = get_store()
    automation = next((item for item in store.list() if item.get('builtin_key') == 'youtube_creator_tracking'), None)
    if not automation or automation.get('state') != 'active' or not (automation.get('permission') or {}).get('full_access'):
        return
    def run():
        service = YouTubePushDelivery()
        if registration:
            result = service.reconcile()
            refresh_subscription_snapshot(service.tracking)
            return result
        def deliver(delivery_id, text):
            current = store.get(automation['id'])
            if current.get('state') != 'active' or not (current.get('permission') or {}).get('full_access'):
                raise RuntimeError('Push delivery paused before notification commit.')
            return _deliver_creator_upload(current, delivery_id, text, store)
        config = service.tracking._config()
        try:
            result = service.drain(deliver=deliver)
        except Exception:
            if config:
                service.store.save_sync_cursor(SyncCursorInput(connector='youtube_push_delivery_health', account_id=config.account_id,
                    state={'error':'Upload delivery is deferred; pending uploads are retained.', 'checked_at':service.clock().isoformat()}))
            raise
        if config:
            health = (service.store.get_sync_cursor('youtube_push_delivery_health', config.account_id) or {}).get('state') or {}
            if health.get('error') or result['delivered']:
                service.store.save_sync_cursor(SyncCursorInput(connector='youtube_push_delivery_health', account_id=config.account_id,
                    state={'error':'', 'checked_at':service.clock().isoformat()}))
        if result['delivered']:
            run_id = 'push-' + uuid4().hex[:16]
            store.record_run(automation['id'], run_id)
            store.finish_run(automation['id'], run_id, status='complete',
                output=f"YouTube push: {result['delivered']} qualified uploads delivered; {result.get('pending_duration_checks', 0)} awaiting duration verification.")
        return result
    try:
        await asyncio.to_thread(run)
    except Exception:
        # Provider bodies, callback secrets and private account state stay out of logs.
        logger.warning('YouTube push processing deferred; durable outbox retained.')


async def renew_push_subscriptions():
    await run_push_tick(registration=True)


def install_push_jobs(scheduler):
    """Register maintenance on Vellum's scheduler, without a second scheduler."""
    scheduler.add_job(run_push_tick, 'interval', seconds=5, id='youtube-push-delivery',
        replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(renew_push_subscriptions, 'interval', seconds=30, id='youtube-push-registration',
        replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=60)


app = create_callback_app()
