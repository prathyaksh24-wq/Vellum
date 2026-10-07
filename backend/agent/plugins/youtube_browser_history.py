"""Browser history adapter over the existing browser worker and Knowledge Core."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
from threading import Lock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.contracts.youtube_history import BrowserHistorySnapshot, YouTubeHistoryConfig, YouTubeHistoryStatus
from agent.knowledge.ingestion import IngestionCoordinator, IngestionResult
from agent.knowledge.models import (ExternalPolicy, IngestionJobInput, ObservationActor,
    ObservationInput, Sensitivity, SourceItemInput, SyncCursorInput)
from agent.knowledge.runtime import get_knowledge_core
from agent.mcp.playwright_tools import browser_session

ORIGIN = "youtube_browser_history"
ACTION = "youtube.history_presence"
MESSAGES = {
    "ready": "Recent loaded history was saved locally. Exact watch times and repeat plays are unavailable.",
    "browser_closed": "Open History in Vellum's browser first.",
    "browser_busy": "Refresh skipped while the browser is paused or under your control. Resume agent control for background updates.",
    "history_page_required": "Keep the configured History page active in Vellum's browser for refresh.",
    "sign_in_required": "Sign into YouTube manually in Vellum's browser, then refresh.",
    "account_unavailable": "The reader could not identify the browser account. No history was imported.",
    "account_changed": "The browser account changed. Return to the account used for the first refresh.",
    "page_changed": "The History page layout was not recognized. No history was imported.",
    "history_empty_or_paused": "YouTube shows an empty or paused history. Previously imported records remain available.",
    "unavailable": "History refresh failed. Your previous successful import remains available.",
}


def history_day(label: str, *, now: datetime, timezone: str) -> str:
    reference = now.astimezone(ZoneInfo(timezone)).date()
    normalized = label.strip().casefold()
    if normalized in {"today", "yesterday"}:
        return (reference - timedelta(days=normalized == "yesterday")).isoformat()
    for pattern in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(label.strip(), pattern).date().isoformat()
        except ValueError:
            pass
    # Weekday/relative/localized labels do not establish an unambiguous date.
    return ""


class YouTubeBrowserHistory:
    _lock = Lock()

    def __init__(self, *, store=None, browser=browser_session, clock=None):
        self.store = store or get_knowledge_core().store
        self.browser = browser
        self.clock = clock or (lambda: datetime.now(UTC))

    def _state(self):
        return dict((self.store.get_sync_cursor(ORIGIN, "settings") or {}).get("state") or {})

    def _save(self, state):
        self.store.save_sync_cursor(SyncCursorInput(connector=ORIGIN, account_id="settings", state=state))

    def status(self):
        state = self._state()
        return YouTubeHistoryStatus(config=state.get("config") or {},
            status=state.get("status", "not_refreshed"), last_success_at=state.get("last_success_at", ""),
            last_attempt_at=state.get("last_attempt_at", ""), message=state.get("message", MESSAGES["browser_closed"]),
            records=self.store.count_observations(origin=ORIGIN, action=ACTION),
            account_bound=bool(state.get("account_fingerprint"))).model_dump()

    def configure(self, arguments):
        config = YouTubeHistoryConfig.model_validate(arguments)
        with self._lock:
            state = self._state()
            state["config"] = config.model_dump()
            self._save(state)
        return self.status()

    def refresh(self, *, automatic=False):
        if not self._lock.acquire(blocking=False):
            return {"status": "browser_busy", "message": "A history refresh is already running."}
        try:
            state = self._state()
            config = YouTubeHistoryConfig.model_validate(state.get("config") or {})
            now = self.clock()
            state["last_attempt_at"] = now.isoformat()
            try:
                result = self.browser("youtube_history", {"url": config.url, "automatic": automatic})
                code = result["status"]
                if code == "ready":
                    fingerprint = result["account_fingerprint"]
                    if state.get("account_fingerprint") not in {None, "", fingerprint}:
                        code = "account_changed"
                    else:
                        records = self._normalize(result["entries"], config=config, now=now)
                        if not records:
                            code = "page_changed"
                        else:
                            job = IngestionCoordinator(self.store).run(IngestionJobInput(
                                connector=ORIGIN, account_id=fingerprint, job_type="recent_history",
                                idempotency_key=uuid4().hex, requested_by="scheduler" if automatic else "user"),
                                operation=lambda _cursor: self._import(records, fingerprint, now))
                            if job.get("status") != "completed":
                                raise ValueError("History ingestion did not complete")
                            state["account_fingerprint"] = fingerprint
                            state["last_success_at"] = now.isoformat()
            except Exception:
                code = "unavailable"
            state["status"] = code
            state["message"] = MESSAGES.get(code, MESSAGES["unavailable"])
            self._save(state)
            return self.status()
        finally:
            self._lock.release()

    @staticmethod
    def _normalize(entries, *, config, now):
        records = {}
        for entry in entries[:100]:
            parsed = urlsplit(str(entry.get("url", "")))
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if parsed.hostname not in {"www.youtube.com", "youtube.com"} or parsed.path != "/watch" or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            label = str(entry.get("day_label", ""))[:100]
            day = history_day(label, now=now, timezone=config.timezone)
            # Unknown relative dates cannot form durable event identities. Keep them
            # in the current source snapshot only, not as new daily observations.
            key = video_id + ":" + day
            records[key] = {"video_id": video_id, "url": "https://www.youtube.com/watch?v=" + video_id,
                "title": str(entry.get("title", ""))[:500], "channel_title": str(entry.get("channel_title", ""))[:500],
                "history_day": day, "day_label": label, "occurred_at": "", "time_precision": "day" if day else "unknown",
                "captured_at": now.isoformat(), "provider": ORIGIN}
        return list(records.values())

    def _import(self, records, account, now):
        source = self.store.upsert_source(SourceItemInput(kind=ORIGIN, external_id=account,
            account_id=account, title="YouTube browser history", observed_at=now,
            content=json.dumps([{key: value for key, value in item.items() if key != "captured_at"}
                for item in records], ensure_ascii=False, sort_keys=True),
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY, external_policy=ExternalPolicy.DENY_RAW,
            trust="browser_page", metadata={"coverage": "recent_loaded_history", "items": records}))
        observations = []
        for item in records:
            if not item["history_day"]:
                continue
            key = sha256((account + ":" + item["video_id"] + ":" + item["history_day"]).encode()).hexdigest()
            observations.append(ObservationInput(origin=ORIGIN, action=ACTION, actor=ObservationActor.IMPORTED,
                trigger="youtube_history_page", source_id=source["source_id"], event_key=ORIGIN + ":" + key,
                payload=item, sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY, confidence=1.0, observed_at=now))
        inserted = self.store.record_observations(observations)
        return IngestionResult(stats={"records": len(records), **inserted}, cursor=now.isoformat(), cursor_state={"source_id": source["source_id"]})

    def history(self, *, limit=20, channel=""):
        rows = self.store.list_observation_details(origin=ORIGIN, action=ACTION, limit=500)
        items = [dict(row["payload"]) for row in rows]
        # Entries with unrecognized dates remain useful evidence in the latest
        # snapshot, without fabricated watch timestamps or accumulating duplicates.
        account = self._state().get("account_fingerprint", "")
        if account:
            for source in self.store.list_sources(kind=ORIGIN, limit=100):
                if source.get("account_id") == account:
                    detail = self.store.get_source(source["id"]) or {}
                    items.extend(item for item in detail.get("metadata", {}).get("items", []) if not item.get("history_day"))
        if channel:
            from agent.plugins.youtube_takeout import filter_channel_history
            items = filter_channel_history(items, channel)
        items.sort(key=lambda item: item["history_day"], reverse=True)
        return {"available": bool(items), "items": items[:limit], "total": len(items),
            "provider": ORIGIN, "freshness": self.status(), "coverage": "recent_loaded_history",
            "local_only": True,
            "timing_note": "Dates have day precision; repeat plays and watch duration are unavailable."}


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
        # The settings, current snapshot and daily evidence share one ingestion owner.
        owner = YouTubeBrowserHistory(store=self.store)
        config = YouTubeHistoryConfig.model_validate(owner._state().get('config') or {})
        records = owner._normalize(items, config=config, now=refreshed_at)
        source_id = ''
        def persist(_cursor):
            nonlocal source_id
            result = owner._import(records, snapshot.account_id, refreshed_at)
            source_id = result.cursor_state['source_id']
            return result
        job = IngestionCoordinator(self.store).run(IngestionJobInput(connector=ORIGIN,
            account_id=snapshot.account_id, job_type='recent_history', idempotency_key=uuid4().hex,
            requested_by='user'), operation=persist)
        if job.get('status') != 'completed':
            raise HistoryReadError('History could not be saved locally. No successful refresh was recorded.')
        with owner._lock:
            state = owner._state()
            state.update(account_fingerprint=snapshot.account_id, status='ready',
                last_attempt_at=refreshed_at.isoformat(), last_success_at=refreshed_at.isoformat(),
                message=MESSAGES['ready'])
            owner._save(state)
        return {'available':True, 'provider':'browser', 'local_only':True, 'freshness':'browser_refresh',
            'source_id':source_id, 'account_id':snapshot.account_id, 'refreshed_at':refreshed_at.isoformat(),
            'coverage':snapshot.coverage, 'truncated':snapshot.truncated, 'total':len(items), 'items':items}
