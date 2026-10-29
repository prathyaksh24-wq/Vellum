"""Hosted transport adapter for the canonical local YouTube push owner.

Cloudflare retains public signed events while the PC is off. No hosted
notification writer or private-profile projection is introduced here.
"""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from uuid import uuid4
import xml.etree.ElementTree as ET

import httpx

from agent.contracts.youtube_push import HostedRelayAck, HostedRelayEvents, HostedRelayStatus
from agent.knowledge.models import SyncCursorInput


class RelayDailyQuotaError(RuntimeError):
    """Only a known public provider error code may become a status warning."""


class YouTubeRelayClient:
    def __init__(self, service, *, token=None, request_backend=None):
        from agent.config import get_settings
        self.service = service
        self.store = service.store
        self.clock = service.clock
        config = service.tracking._config()
        self.account_id = config.account_id if config else ''
        self.token = token if token is not None else get_settings().youtube_push_relay_token.get_secret_value()
        self.request_backend = request_backend

    def _request(self, method, path, *, payload=None):
        if not self.token or len(self.token) != 43:
            raise ValueError('Hosted receiver credentials are missing.')
        # No redirects, cookies, bearer URLs, provider bodies or secrets in errors.
        with httpx.Client(timeout=httpx.Timeout(10, connect=3), follow_redirects=False,
                          transport=self.request_backend) as client:
            with client.stream(method, self.service.callback_base+path,
                    headers={'Authorization':'Bearer '+self.token}, json=payload) as response:
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 7 * 1048576:
                        raise ValueError('Hosted receiver response exceeded the bounded page size.')
                if response.status_code != 200:
                    try:
                        code=json.loads(raw).get('code')
                    except (ValueError,AttributeError):
                        code=None
                    if response.status_code==503 and code=='daily_database_limit':
                        raise RelayDailyQuotaError('Hosted database daily allowance exhausted; push sync waits until the next UTC midnight.')
                    raise RuntimeError('Hosted receiver is unavailable or requires authorization.')
        return json.loads(raw)

    def state(self):
        return dict((self.store.get_sync_cursor('youtube_push_relay', self.account_id) or {}).get('state') or {})

    def save(self, state):
        self.store.save_sync_cursor(SyncCursorInput(connector='youtube_push_relay', account_id=self.account_id, state=state))

    def reconcile(self, targets):
        owner, lease = uuid4().hex, self.account_id+':push-relay'
        if not self.store.youtube_tracking_lock(lease, owner, self.clock().timestamp(), duration=60):
            return {'requests':0}
        try:
            return self._reconcile(targets)
        except Exception as error:
            state = self.state()
            state['error'] = str(error) if isinstance(error,RelayDailyQuotaError) else 'Hosted channel registration is deferred; the previous channel list is retained.'
            self.save(state)
            raise RuntimeError('Hosted channel registration deferred.') from None
        finally:
            self.store.youtube_tracking_unlock(lease, owner)

    def _reconcile(self, targets):
        from agent.plugins.youtube_creator_tracking import _time
        config, now = self.service.tracking._config(), self.clock()
        if len(targets) > 1000:
            raise ValueError('The personal hosted receiver supports at most 1000 channels; none were truncated.')
        rows = self.store.youtube_push_subscriptions(config.account_id)
        for row in rows:
            desired = row['channel_id'] in targets
            if row.get('base') != self.service.callback_base:
                self.store.youtube_push_patch(row['token'], {'base':self.service.callback_base,
                    'desired':desired,'lease_expires':0,'renew_at':0,'status':'pending' if desired else 'unsubscribed','error':''})
            elif row.get('desired') != desired:
                self.store.youtube_push_patch(row['token'], {'desired':desired,'lease_expires':0,'renew_at':0})
        manifest = [{'channel_id':row['channel_id'],'token':row['token'],'secret':row['secret']}
                    for row in rows if row['channel_id'] in targets]
        digest = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        state = self.state()
        if state.get('base') != self.service.callback_base:
            state = {'base':self.service.callback_base, 'after':0}
        if state.get('manifest') != digest or (_time(state.get('manifest_next_at')) or now) <= now:
            receipt = self._request('PUT', '/v1/channels', payload={'contract_version':1,'channels':manifest})
            if receipt.get('contract_version') != 1 or receipt.get('desired_channels') != len(manifest):
                raise ValueError('Hosted receiver did not acknowledge the full channel list.')
            state.update(manifest=digest, remote_revision=receipt.get('revision',''), manifest_next_at=(now+timedelta(hours=6)).isoformat())
            self.save(state)
        status = HostedRelayStatus.model_validate(self._request('GET', '/v1/status'))
        if state.get('remote_revision') != status.revision:
            state['manifest_next_at'] = now.isoformat()
        desired = set(targets)
        remote = {row.channel_id:row.lease_expires for row in status.channels}
        for row in rows:
            if row['channel_id'] not in desired:
                continue
            expires = remote.get(row['channel_id'], 0)
            if expires != row.get('lease_expires', 0) or row.get('error') or row.get('base') != self.service.callback_base:
                self.store.youtube_push_patch(row['token'], {'lease_expires':expires,
                    'status':'active' if expires > now.timestamp() else 'pending','error':''})
        state.update(remote_status=status.model_dump(), error='', registered_at=now.isoformat())
        self.save(state)
        return {'requests':1,'desired_channels':len(manifest)}

    def pull(self):
        from agent.plugins.youtube_creator_tracking import _time
        config, now = self.service.tracking._config(), self.clock()
        state = self.state()
        if state.get('base') != self.service.callback_base or not state.get('manifest'):
            return
        if (_time(state.get('next_at')) or now) > now:
            return
        owner, lease = uuid4().hex, config.account_id+':push-relay'
        if not self.store.youtube_tracking_lock(lease, owner, now.timestamp(), duration=60):
            return
        try:
            # Registration and event sync share this lease and must reread state
            # inside it so a slow status response cannot rewind a checkpoint.
            state = self.state()
            after = int(state.get('after',0))
            page = HostedRelayEvents.model_validate(self._request('GET', '/v1/events?after='+str(after)))
            if state.get('epoch') and page.epoch != state['epoch']:
                # Database recreation has a new sequence. Persist reset before retry.
                state.update(epoch=page.epoch, after=0, next_at=now.isoformat(),
                    gap=True, error='Hosted event history was reset; RSS recovery remains bounded.')
                self.save(state)
                return
            ids = [event.id for event in page.events]
            if ids != sorted(set(ids)) or any(identity <= after for identity in ids) or page.next_after != (ids[-1] if ids else max(after,page.retention_floor)):
                raise ValueError('Hosted receiver returned an invalid checkpoint.')
            registrations = {row['channel_id']:row for row in self.store.youtube_push_subscriptions(config.account_id)}
            rejected = list(state.get('rejected_events') or [])
            for event in page.events:
                row = registrations.get(event.channel_id)
                if not row or not row.get('desired') or row.get('base') != self.service.callback_base:
                    continue
                try:
                    entries = self.service.parse(event.body.encode('utf-8'), event.channel_id)
                except (ValueError, ET.ParseError, UnicodeError):
                    rejected = [*rejected, event.id][-20:]
                    continue
                # Acknowledge the hosted page only after its events are durably local.
                self.store.youtube_push_enqueue(config.account_id, event.channel_id, entries, now.isoformat())
                for entry in entries:
                    published = _time(entry['published_at'])
                    if published and published < now-timedelta(hours=24):
                        self.store.youtube_push_promote(config.account_id, event.channel_id, entry['video_id'], 'baseline')
                self.store.youtube_push_patch(row['token'], {'last_received_at':datetime.fromtimestamp(event.received_at,UTC).isoformat()})
            state.update(after=page.next_after, epoch=page.epoch,
                gap=bool(state.get('gap') or page.gap), rejected_events=rejected,
                last_sync_at=now.isoformat(), error='',
                next_at=(now+timedelta(seconds=0 if page.has_more else 15)).isoformat())
            self.save(state)
            # The checkpoint above is durable before the receiver may rotate
            # anything. Rotation failure never rewinds ingestion or blocks pings.
            if page.next_after and (_time(state.get('ack_next_at')) or now) <= now:
                try:
                    receipt=HostedRelayAck.model_validate(self._request('POST','/v1/ack',payload={
                        'contract_version':1,'epoch':page.epoch,'after':page.next_after}))
                    if receipt.epoch != page.epoch or receipt.after != page.next_after:
                        raise ValueError('Receiver acknowledged a different checkpoint.')
                    state.update(rotation_warning='',ack_next_at=(now+timedelta(seconds=15 if receipt.pruned==500 else 300)).isoformat())
                except Exception:
                    state.update(rotation_warning='Hosted buffer rotation is deferred; saved local uploads are retained.',
                        ack_next_at=(now+timedelta(minutes=5)).isoformat())
                self.save(state)
        except Exception as error:
            state.update(error=str(error) if isinstance(error,RelayDailyQuotaError) else 'Hosted event sync is deferred; the local checkpoint was retained.',
                next_at=(now+timedelta(seconds=60)).isoformat())
            self.save(state)
            raise RuntimeError('Hosted event sync deferred.') from None
        finally:
            self.store.youtube_tracking_unlock(lease, owner)

    def decorate_status(self, result):
        config = self.service.tracking._config()
        if not config:
            return result
        state, now = self.state(), self.clock()
        remote = state.get('remote_status') or {}
        result.last_relay_sync_at = state.get('last_sync_at','')
        result.relay_retention_days = 7
        result.coverage = ('The hosted receiver collects public upload events while this PC is off. '
            'Seven-day catch-up storage; local backend required for duration checks and notifications. '
            'Events older than 24 hours are retained quietly. Private history stays local.')
        if not self.token:
            result.warnings.append('Configure the hosted receiver credential before activation.')
        if state.get('error'):
            result.warnings.append(state['error'])
        if state.get('rotation_warning'):
            result.warnings.append(state['rotation_warning'])
        if state.get('gap'):
            result.warnings.append('Hosted catch-up has a coverage gap; older events may be missing.')
        if state.get('rejected_events'):
            result.warnings.append('Malformed hosted events were skipped; valid uploads continue syncing.')
        if not remote.get('last_maintenance') or now.timestamp()-remote['last_maintenance']>600:
            result.warnings.append('Hosted subscription maintenance has not been confirmed in the last ten minutes.')
        # Host warnings are data; only known public messages cross the local API.
        if remote.get('warnings'):
            result.warnings.append('Some hosted channel registrations are pending or deferred.')
        if result.warnings:
            result.status = 'partial'
        return result
