"""Fixed read-only extraction; no cookies, arbitrary JS, or network interception."""
from hashlib import sha256
from urllib.parse import urlsplit

from agent.contracts.youtube_history import YouTubeHistoryConfig

# Scoped to the History renderer. Never interpret a Home/search page as history.
# Date headings are retained verbatim; normalization happens in the local adapter.
HISTORY_SCRIPT = r"""() => {
  const root = document.querySelector('ytd-browse[page-subtype="history"]');
  const config = window.ytcfg;
  const get = key => config && typeof config.get === 'function' ? config.get(key) : null;
  const loggedIn = get('LOGGED_IN') === true;
  const account = get('DATASYNC_ID');
  const entries = [];
  if (root) for (const section of root.querySelectorAll('ytd-item-section-renderer')) {
    const heading = section.querySelector('ytd-item-section-header-renderer #title, #header #title');
    const dayLabel = heading ? heading.textContent.trim() : '';
    for (const row of section.querySelectorAll('ytd-video-renderer')) {
      const link = row.querySelector('a#video-title[href]');
      const channel = row.querySelector('ytd-channel-name a[href]');
      if (link) entries.push({url:link.href, title:link.textContent.trim().slice(0,500),
        channel_url:channel ? channel.href : '', channel_title:channel ? channel.textContent.trim().slice(0,500) : '',
        day_label:dayLabel.slice(0,100)});
      if (entries.length >= 100) break;
    }
    if (entries.length >= 100) break;
  }
  const empty = root && root.querySelector('ytd-message-renderer');
  return {history_page:!!root, logged_in:loggedIn, account:typeof account === 'string' ? account : '',
    empty_message:empty ? empty.textContent.trim().slice(0,300) : '', entries};
}"""


async def read_history(browser, *, url: str, automatic: bool = False) -> dict:
    YouTubeHistoryConfig(url=url)
    if browser.context is None or browser.active_page is None:
        return {"status": "browser_closed"}
    if browser.control == "paused" or (automatic and browser.control != "agent"):
        return {"status": "browser_busy"}
    page = browser.active_page
    parsed = urlsplit(page.url)
    if parsed.hostname in {"accounts.google.com", "consent.youtube.com", "consent.google.com"}:
        return {"status": "sign_in_required"}
    if page.url.rstrip('/') != url.rstrip('/'):
        return {"status": "history_page_required"}
    # Manual refresh is direct user intent. Background refresh never changes tabs.
    await page.reload(wait_until="domcontentloaded")
    parsed = urlsplit(page.url)
    if parsed.hostname in {"accounts.google.com", "consent.youtube.com", "consent.google.com"}:
        return {"status": "sign_in_required"}
    if page.url.rstrip('/') != url.rstrip('/'):
        return {"status": "history_page_required"}
    try:
        await page.locator('ytd-browse[page-subtype="history"]').wait_for(timeout=8000)
        await page.locator('ytd-video-renderer, ytd-message-renderer').first.wait_for(timeout=5000)
    except Exception:
        pass  # Classify the loaded page rather than silently returning an empty feed.
    if page.url.rstrip('/') != url.rstrip('/'):
        return {"status": "history_page_required"}
    payload = await page.evaluate(HISTORY_SCRIPT)
    if not payload["logged_in"]:
        return {"status": "sign_in_required"}
    if not payload["history_page"]:
        return {"status": "page_changed"}
    if not payload["account"]:
        return {"status": "account_unavailable"}
    fingerprint = sha256(payload.pop("account").encode()).hexdigest()
    if not payload["entries"]:
        return {"status": "history_empty_or_paused" if payload["empty_message"] else "page_changed"}
    return {"status": "ready", "account_fingerprint": fingerprint, "entries": payload["entries"]}
