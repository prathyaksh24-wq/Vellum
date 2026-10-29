"""Fixed DOM-only reader used inside the existing dedicated browser owner."""
import hashlib
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

HISTORY_URL = "https://www.youtube.com/feed/history"

# Select only identity and rendered history cards; never cookies or auth tokens.
HISTORY_DOM = r"""() => {
  const cfg = window.ytcfg;
  const signed = cfg?.get?.('LOGGED_IN') === true;
  const account = cfg?.get?.('DATASYNC_ID');
  const identity = signed && typeof account === 'string' ? account : '';
  const historyRoot = document.querySelector('ytd-browse[page-subtype="history"]');
  const roots = Array.from(historyRoot?.querySelectorAll('ytd-video-renderer, ytd-reel-item-renderer, yt-lockup-view-model') || []);
  const items = roots.map(root => {
    const title = root.querySelector('a#video-title, a#video-title-link, h3 a, a[href^="/shorts/"]');
    const href = title?.getAttribute('href') || '';
    const url = new URL(href || '/', location.origin);
    const id = url.searchParams.get('v') || (url.pathname.startsWith('/shorts/') ? url.pathname.split('/')[2] : '');
    const channel = root.querySelector('#channel-name a, ytd-channel-name a, a[href*="/channel/"], a[href*="/@"]') ||
      root.querySelector('.ytContentMetadataViewModelMetadataRow .ytContentMetadataViewModelMetadataText');
    const channelHref = channel?.getAttribute('href') || '';
    const section = root.closest('ytd-item-section-renderer');
    if (!section?.querySelector('#header, ytd-item-section-header-renderer')?.textContent.trim()) return null;
    return {video_id:id, title:(title?.textContent || title?.getAttribute('title') || '').trim().slice(0,500),
      channel_title:(channel?.textContent || '').trim().slice(0,200),
      channel_id:channelHref.startsWith('/channel/') ? channelHref.split('/')[2].slice(0,100) : '',
      day_label:(section?.querySelector('#header, ytd-item-section-header-renderer')?.textContent || '').trim().slice(0,100)};
  }).filter(x => x && /^[\w-]{11}$/.test(x.video_id) && x.title);
  const message = Array.from(historyRoot?.querySelectorAll('ytd-message-renderer, yt-formatted-string#message') || []).map(x=>x.textContent).join(' ');
  const empty = !!message && /no videos|history is empty|watch history.*paused|no watch history/i.test(message);
  return {signed_in:signed, identity, items, empty, timezone:Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'};
}"""


async def read_history_page(page, *, history_url=HISTORY_URL, scroll_limit=6, can_continue=lambda:True, day_label='', now=None):
    from agent.contracts.youtube_history import BrowserHistoryReadRequest, YouTubeHistoryConfig
    from agent.plugins.youtube_browser_history import history_day
    YouTubeHistoryConfig(url=history_url)
    BrowserHistoryReadRequest(day_label=day_label)
    def allowed():
        parsed = urlsplit(page.url)
        return (parsed.scheme == "https" and parsed.hostname in {"youtube.com", "www.youtube.com"}
                and page.url.rstrip('/') == history_url.rstrip('/'))
    if not allowed():
        return {"status":"page_unreadable"}
    deadline = time.monotonic() + 20
    first = None
    for _ in range(10):
        if not can_continue():
            raise ValueError('The browser was paused or taken over during the history read.')
        if not allowed():
            return {"status":"page_unreadable"}
        first = await page.evaluate(HISTORY_DOM)
        if first.get('signed_in') and (first.get('items') or first.get('empty')):
            break
        await page.wait_for_timeout(250)
    if not first.get('signed_in'):
        return {"status":"signed_out"}
    identity = first.get('identity')
    if not identity:
        return {"status":"account_unknown"}
    account_id = hashlib.sha256(identity.encode()).hexdigest()
    reference = now or datetime.now(UTC)
    timezone = first.get('timezone') or 'UTC'
    requested_day = history_day(day_label, now=reference, timezone=timezone) if day_label else ''
    if requested_day:
        scroll_limit = max(scroll_limit, 24)
    rows = {}
    seen = set()
    earliest = ''
    reached_older = False
    current = first
    stable = 0
    for step in range(scroll_limit + 1):
        if not can_continue():
            raise ValueError('The browser was paused or taken over during the history read.')
        if not current.get('signed_in') or current.get('identity') != identity:
            return {"status":"account_changed"}
        before = len(seen)
        for item in current.get('items') or []:
            if not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(item.get('video_id') or '')):
                continue
            key = (item['video_id'], item.get('day_label') or '')
            seen.add(key)
            day = history_day(item.get('day_label') or '', now=reference, timezone=timezone)
            if day:
                earliest = min(earliest or day, day)
                reached_older = reached_older or bool(requested_day and day < requested_day)
            if requested_day and day != requested_day:
                continue
            if key not in rows and len(rows) < 100:
                rows[key] = {**item, 'url':'https://www.youtube.com/watch?v=' + item['video_id']}
        stable = stable + 1 if len(seen) == before else 0
        if step == scroll_limit or len(rows) >= 100 or stable >= 2 or reached_older or time.monotonic() >= deadline:
            break
        await page.mouse.wheel(0, 1200)
        await page.wait_for_timeout(500)
        if not allowed():
            return {"status":"page_unreadable"}
        current = await page.evaluate(HISTORY_DOM)
    if not can_continue():
        raise ValueError('The browser was paused or taken over during the history read.')
    if not allowed():
        return {"status":"page_unreadable"}
    final = await page.evaluate(HISTORY_DOM)
    if not final.get('signed_in') or final.get('identity') != identity:
        return {"status":"account_changed"}
    if not rows and not final.get('empty') and not (requested_day and seen):
        return {"status":"page_unreadable"}
    return {'status':'ready' if rows else 'empty', 'account_id':account_id, 'items':list(rows.values()),
        'coverage':'recent_page', 'timezone':timezone, 'requested_day':requested_day, 'earliest_loaded_day':earliest,
        'truncated':len(rows) >= 100 or (stable < 2 and not reached_older and scroll_limit > 0)}
