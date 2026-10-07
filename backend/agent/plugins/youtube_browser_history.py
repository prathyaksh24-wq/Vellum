"""Account-scoped browser snapshots persisted by the existing Knowledge owner."""
import json
from datetime import UTC, datetime
from uuid import uuid4

from agent.contracts.youtube_history import BrowserHistorySnapshot
from agent.knowledge.ingestion import IngestionCoordinator, IngestionResult
from agent.knowledge.models import IngestionJobInput, SourceItemInput, Sensitivity, ExternalPolicy


class HistoryReadError(ValueError):
    pass


ERRORS = {
    'signed_out':'Sign into YouTube in Vellum’s Browser, then refresh history.',
    'account_unknown':'I could not verify which YouTube browser account is active. No history was imported.',
    'account_changed':'The YouTube account changed during the read. Refresh again after selecting your account.',
    'page_unreadable':'I could not recognize the YouTube history page. Open Watch history in Vellum’s Browser and try again.',
}


def current_browser_history():
    from agent.mcp.playwright_tools import browser_session
    try:
        return browser_session('youtube_history')
    except Exception as exc:
        reason = str(exc).casefold()
        if any(word in reason for word in ('paused', 'takeover', 'taken over', 'user has control')):
            raise HistoryReadError('Resume agent control in the Browser panel before refreshing history.') from None
        raise HistoryReadError('The browser history read failed. Check Vellum’s Browser and try again.') from None


class YouTubeBrowserHistoryService:
    def __init__(self, *, store=None, browser_reader=current_browser_history):
        self._store = store
        self.browser_reader = browser_reader

    @property
    def store(self):
        if self._store is None:
            from agent.knowledge.runtime import get_knowledge_core
            return get_knowledge_core().store
        return self._store

    def refresh(self):
        try:
            snapshot = BrowserHistorySnapshot.model_validate(self.browser_reader())
        except HistoryReadError:
            raise
        except Exception:
            raise HistoryReadError('The browser returned an invalid history response. No history was imported.') from None
        if snapshot.status not in {'ready', 'empty'}:
            raise HistoryReadError(ERRORS[snapshot.status])
        if not snapshot.account_id:
            raise HistoryReadError(ERRORS['account_unknown'])
        refreshed_at = datetime.now(UTC)
        items = [item.model_dump() for item in snapshot.items]
        # Canonical URLs are constructed from validated IDs, never trusted page URLs.
        for item in items:
            item['url'] = 'https://www.youtube.com/watch?v=' + item['video_id']
        source_id = ''
        def persist(_cursor):
            nonlocal source_id
            result = self.store.upsert_source(SourceItemInput(
                kind='youtube_browser_history', external_id='youtube:browser-history:' + snapshot.account_id,
                account_id=snapshot.account_id, title='YouTube browser watch-history snapshot',
                uri='https://www.youtube.com/feed/history', content=json.dumps(items, ensure_ascii=False),
                observed_at=refreshed_at, sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY, external_policy=ExternalPolicy.DENY_RAW,
                trust='authenticated_browser_dom', metadata={'connector':'youtube_browser', 'items':items,
                    'refreshed_at':refreshed_at.isoformat(), 'coverage':snapshot.coverage, 'truncated':snapshot.truncated}))
            source_id = result['source_id']
            return IngestionResult(stats={'history_entries':len(items)}, cursor=refreshed_at.isoformat(),
                cursor_state={'source_id':source_id, 'coverage':'recent_page'})
        IngestionCoordinator(self.store).run(IngestionJobInput(connector='youtube_browser',
            account_id=snapshot.account_id, job_type='history_snapshot', idempotency_key=uuid4().hex,
            requested_by='user'), operation=persist)
        return {'available':True, 'provider':'browser', 'local_only':True, 'freshness':'browser_refresh',
            'source_id':source_id, 'account_id':snapshot.account_id, 'refreshed_at':refreshed_at.isoformat(),
            'coverage':snapshot.coverage, 'truncated':snapshot.truncated, 'total':len(items), 'items':items}
