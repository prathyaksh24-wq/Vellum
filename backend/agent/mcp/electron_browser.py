"""Private transport to Vellum-owned Electron tabs; never discover a daily browser."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx

from agent.config import _resolve_against_repo


class ElectronBridge:
    def __init__(self, endpoint: str, token: str):
        self.endpoint, self.token = endpoint, token

    @classmethod
    def discover(cls, descriptor_path=None):
        try:
            path = descriptor_path or _resolve_against_repo(Path('.desktop-runtime/browser-bridge.json'))
            data = json.loads(path.read_text(encoding='utf-8'))
            url = urlsplit(data['endpoint'])
            if (data.get('version') != 1 or url.scheme != 'http' or url.hostname != '127.0.0.1'
                    or not url.port or url.path not in {'', '/'} or url.username or url.password
                    or url.query or url.fragment or not re.fullmatch(r'[a-f0-9]{64}', data['token'])):
                return None
            return cls(data['endpoint'].rstrip('/'), data['token'])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    async def call(self, operation: str, **arguments):
        async with httpx.AsyncClient(trust_env=False, timeout=8) as client:
            try:
                response = await client.post(self.endpoint + '/browser', json={'operation':operation, **arguments},
                    headers={'Authorization':'Bearer ' + self.token})
                response.raise_for_status()
                result = response.json()
            except (httpx.HTTPError, ValueError):
                raise ValueError('The embedded browser disconnected. Reopen Vellum desktop.') from None
        if result.get('error'):
            raise ValueError(result['error'])
        return result


class ElectronContext:
    """Present only registered guest pages through the existing browser owner interface."""
    def __init__(self, owner, bridge, browser):
        self.owner, self.bridge, self.browser = owner, bridge, browser
        self.targets = {}
        self.profile_id = owner._browser_preferences().active_profile_id

    @property
    def pages(self):
        return [page for page in self.targets.values() if not page.is_closed()]

    async def page_for_target(self, target_id):
        if target_id in self.targets and not self.targets[target_id].is_closed():
            return self.targets[target_id]
        for _ in range(40):
            for context in self.browser.contexts:
                for page in context.pages:
                    if page.is_closed() or page in self.targets.values():
                        continue
                    session = None
                    try:
                        session = await context.new_cdp_session(page)
                        info = await session.send('Target.getTargetInfo')
                        if info['targetInfo']['targetId'] == target_id:
                            if self.owner._profile().site_defaults.third_party_cookies == 'block':
                                await session.send('Network.setCookieControls', {
                                    'enableThirdPartyCookieRestriction': True,
                                    'disableThirdPartyCookieMetadata': True,
                                    'disableThirdPartyCookieHeuristics': True,
                                })
                            self.targets[target_id] = page
                            return page
                    except Exception:
                        continue
                    finally:
                        if session is not None:
                            await session.detach()
            await asyncio.sleep(.025)
        raise ValueError('The embedded tab did not become ready.')

    async def new_page(self):
        result = await self.bridge.call('create', background=self.owner._opening_background)
        page = await self.page_for_target(result['target_id'])
        self.owner._add_page(page)
        return page

    async def synchronize(self):
        result = await self.bridge.call('status')
        if result.get('human_input') and self.owner.control == 'agent':
            self.owner.control = 'user'
            self.owner._invalidate(view_changed=False)
        for item in result['tabs']:
            if not item.get('background'):
                page = await self.page_for_target(item['target_id'])
                self.owner._add_page(page)
        viewport = result.get('viewport')
        if viewport and viewport != self.owner._viewport:
            self.owner._viewport = viewport
            self.owner._invalidate()
        # Downloads use Electron's session event rather than a second CDP owner.
        for item in result.get('downloads', []):
            if item['id'] not in self.owner._native_download_ids:
                self.owner._native_download_ids.add(item['id'])
                page = self.targets.get(item['target_id'])
                if page is not None:
                    self.owner._download(ElectronDownload(self.bridge, item, page))

    def target_for_page(self, page):
        return next((target for target, value in self.targets.items() if value is page), '')

    async def new_cdp_session(self, page):
        if page not in self.pages:
            raise ValueError('This page does not belong to Vellum browser.')
        return await page.context.new_cdp_session(page)

    async def close(self):
        await self.bridge.call('close')
        self.targets.clear()


class ElectronDownload:
    def __init__(self, bridge, item, page):
        self.bridge, self.identity, self.page = bridge, item['id'], page
        self.suggested_filename = item['name']

    async def cancel(self):
        await self.bridge.call('download_cancel', download_id=self.identity)

    async def save_as(self, destination):
        await self.bridge.call('download_resume', download_id=self.identity)
        for _ in range(3600):
            result = await self.bridge.call('download_status', download_id=self.identity)
            if result['state'] == 'completed':
                import shutil
                await asyncio.to_thread(shutil.copyfile, result['path'], destination)
                return
            if result['state'] in {'cancelled', 'interrupted'}:
                raise ValueError('The embedded browser download failed.')
            await asyncio.sleep(.5)
        raise ValueError('The download did not finish within 30 minutes.')
