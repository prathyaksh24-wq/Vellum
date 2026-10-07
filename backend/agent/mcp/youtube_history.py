"""Fixed DOM-only reader used inside the existing dedicated browser owner."""
import hashlib
import re
import time
from urllib.parse import urlsplit

HISTORY_URL = "https://www.youtube.com/feed/history"

# Select only identity and rendered history cards; never cookies or auth tokens.
HISTORY_DOM = r"""() => {
  const cfg = window.ytcfg;
  const signed = !!cfg?.get('LOGGED_IN');
  const identity = signed ? String(cfg?.get('DATASYNC_ID') || '') : '';
  const roots = Array.from(document.querySelectorAll('ytd-video-renderer, ytd-reel-item-renderer, yt-lockup-view-model'));
  const items = roots.map(root => {
    const title = root.querySelector('a#video-title, a#video-title-link, h3 a, a[href^="/shorts/"]');
    const href = title?.getAttribute('href') || '';
    const url = new URL(href || '/', location.origin);
    const id = url.searchParams.get('v') || (url.pathname.startsWith('/shorts/') ? url.pathname.split('/')[2] : '');
    const channel = root.querySelector('#channel-name a, ytd-channel-name a, a[href*="/channel/"], a[href*="/@"]') ||
      root.querySelector('.ytContentMetadataViewModelMetadataRow .ytContentMetadataViewModelMetadataText');
    const channelHref = channel?.getAttribute('href') || '';
    const section = root.closest('ytd-item-section-renderer');
    if (!section?.querySelector('#header')?.textContent.trim()) return null;
    return {video_id:id, title:(title?.textContent || title?.getAttribute('title') || '').trim().slice(0,500),
      channel_title:(channel?.textContent || '').trim().slice(0,200),
      channel_id:channelHref.startsWith('/channel/') ? channelHref.split('/')[2].slice(0,100) : '',
      day_label:(section?.querySelector('#header')?.textContent || '').trim().slice(0,100)};
  }).filter(x => x && /^[\w-]{11}$/.test(x.video_id) && x.title);
  const message = Array.from(document.querySelectorAll('ytd-message-renderer, yt-formatted-string#message')).map(x=>x.textContent).join(' ');
  const empty = !!message && /no videos|history is empty|watch history.*paused|no watch history/i.test(message);
  return {signed_in:signed, identity, items, empty};
}"""


async def read_history_page(page, *, scroll_limit=6, can_continue=lambda:True):
    parsed = urlsplit(page.url)
    if parsed.hostname not in {"youtube.com", "www.youtube.com"} or parsed.path.rstrip('/') != '/feed/history':
        return {"status":"page_unreadable"}
    deadline = time.monotonic() + 20
    first = None
    for _ in range(10):
        first = await page.evaluate(HISTORY_DOM)
        if first.get('signed_in') and (first.get('items') or first.get('empty')):
            break
        await page.wait_for_timeout(250)
    if not first.get('signed_in'):
        return {"status":"signed_out"}
    identity = first.get('identity')
    if not identity:
        return {"status":"account_unknown"}
    account_id = hashlib.sha256(('vellum-youtube-browser:' + identity).encode()).hexdigest()
    rows = {}
    current = first
    stable = 0
    for step in range(scroll_limit + 1):
        if not can_continue():
            raise ValueError('The browser was paused or taken over during the history read.')
        if not current.get('signed_in') or current.get('identity') != identity:
            return {"status":"account_changed"}
        before = len(rows)
        for item in current.get('items') or []:
            if not re.fullmatch(r'[\w-]{11}', str(item.get('video_id') or '')):
                continue
            key = (item['video_id'], item.get('day_label') or '')
            if key not in rows and len(rows) < 100:
                rows[key] = {**item, 'url':'https://www.youtube.com/watch?v=' + item['video_id']}
        stable = stable + 1 if len(rows) == before else 0
        if step == scroll_limit or len(rows) >= 100 or stable >= 2 or time.monotonic() >= deadline:
            break
        await page.mouse.wheel(0, 1200)
        await page.wait_for_timeout(500)
        current = await page.evaluate(HISTORY_DOM)
    final = await page.evaluate(HISTORY_DOM)
    if not final.get('signed_in') or final.get('identity') != identity:
        return {"status":"account_changed"}
    if not rows and not final.get('empty'):
        return {"status":"page_unreadable"}
    return {'status':'ready' if rows else 'empty', 'account_id':account_id, 'items':list(rows.values()),
        'coverage':'recent_page', 'truncated':len(rows) >= 100 or stable < 2 and scroll_limit > 0}
