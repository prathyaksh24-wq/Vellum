"""Fresh account-scoped snapshots and configured history through Knowledge Core."""

from __future__ import annotations

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
    "ready": "Recent history was saved locally. Exact watch times and repeat plays are unavailable.",
    "empty": "YouTube shows an empty or paused history. Previously saved records remain available.",
    "browser_closed": "Sign into YouTube in Vellum's browser, then refresh history.",
    "browser_busy": "History refresh skipped while the browser is paused, under your control, or another refresh is running. Resume agent control to refresh.",
    "history_page_required": "The configured History page could not be read. Check the History URL.",
    "sign_in_required": "Sign into YouTube manually in Vellum's browser, then refresh.",
    "account_unavailable": "The reader could not identify the browser account. No history was imported.",
    "account_changed": "The YouTube account changed during the read. Refresh again after selecting your account.",
    "page_changed": "The History page layout was not recognized. No history was imported.",
    "history_empty_or_paused": "YouTube shows an empty or paused history. Previously saved records remain available.",
    "unavailable": "History refresh failed. Your previous successful import remains available.",
}
_STATUS_CODES = {"signed_out": "sign_in_required", "account_unknown": "account_unavailable",
                 "page_unreadable": "page_changed"}


class HistoryReadError(ValueError):
    """A bounded, safe reason a fresh browser read could not complete."""


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
    return ""  # A weekday or localized heading does not establish a date.


class YouTubeBrowserHistory:
    _lock = Lock()

    def __init__(self, *, store=None, browser=browser_session, clock=None):
        self.store = store if store is not None else get_knowledge_core().store
        self.browser = browser
        self.clock = clock or (lambda: datetime.now(UTC))

    def _state(self):
        return dict((self.store.get_sync_cursor(ORIGIN, "settings") or {}).get("state") or {})

    def _save(self, state):
        self.store.save_sync_cursor(SyncCursorInput(connector=ORIGIN, account_id="settings", state=state))

    def _source(self, account):
        if not account:
            return None
        cursor = self.store.get_sync_cursor(ORIGIN, account) or {}
        source = self.store.get_source(str((cursor.get("state") or {}).get("source_id") or ""))
        if source and source.get("account_id") == account:
            return source if source.get("status") == "active" else None
        # Older imports predate the cursor's source reference. Resolve their
        # canonical source without copying records or linking different accounts.
        offset = 0
        while True:
            rows = self.store.list_sources(kind=ORIGIN, limit=500, offset=offset)
            for row in rows:
                if row.get("account_id") == account and row.get("external_id") == account:
                    return self.store.get_source(row["id"]) if row.get("status") == "active" else None
            if len(rows) < 500:
                return None
            offset += len(rows)

    def status(self):
        state = self._state()
        source = self._source(state.get("account_fingerprint", ""))
        count = self.store.count_observations(origin=ORIGIN, action=ACTION, source_id=source["id"]) if source else 0
        return YouTubeHistoryStatus(config=state.get("config") or {},
            status=state.get("status", "not_refreshed"), last_success_at=state.get("last_success_at", ""),
            last_attempt_at=state.get("last_attempt_at", ""), message=state.get("message", MESSAGES["browser_closed"]),
            records=count, account_bound=bool(state.get("account_fingerprint"))).model_dump()

    def configure(self, arguments):
        config = YouTubeHistoryConfig.model_validate(arguments)
        with self._lock:
            state = self._state()
            state["config"] = config.model_dump()
            self._save(state)
        return self.status()

    def refresh(self, *, automatic=False):
        """Compatibility/status interface used by the existing automation."""
        return self._capture(automatic=automatic)[0]

    def refresh_snapshot(self, *, automatic=False):
        """Fresh read interface: never replace a failed read with old records."""
        status, snapshot = self._capture(automatic=automatic)
        if snapshot is None:
            raise HistoryReadError(status["message"])
        return snapshot

    def _capture(self, *, automatic):
        if not self._lock.acquire(blocking=False):
            return {"status": "browser_busy", "message": MESSAGES["browser_busy"]}, None
        try:
            state = self._state()
            config = YouTubeHistoryConfig.model_validate(state.get("config") or {})
            now = self.clock()
            state["last_attempt_at"] = now.isoformat()
            snapshot = None
            code = "unavailable"
            try:
                packet = self.browser("youtube_history", {"url": config.url, "automatic": automatic})
                # Backward compatibility for trusted legacy browser adapters.
                if "account_fingerprint" in packet:
                    account = packet["account_fingerprint"]
                    items = packet.get("entries") or []
                    code = packet["status"]
                    truncated = False
                elif packet.get("status") in MESSAGES and packet.get("status") not in {"ready", "empty"}:
                    code = packet["status"]
                    account, items, truncated = "", [], False
                else:
                    read = BrowserHistorySnapshot.model_validate(packet)
                    account, items, truncated = read.account_id, [
                        {**item.model_dump(), "url": "https://www.youtube.com/watch?v=" + item.video_id}
                        for item in read.items], read.truncated
                    code = _STATUS_CODES.get(read.status, read.status)
                    if "config" not in state:
                        config = YouTubeHistoryConfig(timezone=read.timezone)
                if code in {"ready", "empty"}:
                    if not account:
                        code = "account_unavailable"
                    else:
                        records = self._normalize(items, config=config, now=now)
                        if code == "ready" and not records:
                            code = "page_changed"
                        else:
                            job = IngestionCoordinator(self.store).run(IngestionJobInput(
                                connector=ORIGIN, account_id=account, job_type="recent_history",
                                idempotency_key=uuid4().hex, requested_by="scheduler" if automatic else "user"),
                                operation=lambda _cursor: self._import(records, account, now, truncated=truncated, history_url=config.url))
                            if job.get("status") != "completed":
                                raise ValueError("History ingestion did not complete")
                            source_id = self._source(account)["id"]
                            state.update(account_fingerprint=account, config=config.model_dump(),
                                last_success_at=now.isoformat())
                            # Fresh display retains YouTube's labels and order. The
                            # durable observations separately retain resolved days.
                            fresh = [{**item, "url": "https://www.youtube.com/watch?v=" + item["video_id"]}
                                     for item in records]
                            snapshot = {"available": True, "provider": "browser", "local_only": True,
                                "freshness": "browser_refresh", "source_id": source_id, "account_id": account,
                                "refreshed_at": now.isoformat(), "coverage": "recent_page", "truncated": truncated,
                                "total": len(fresh), "items": fresh}
            except Exception as exc:
                reason = str(exc).casefold()
                code = "browser_busy" if any(word in reason for word in ("paused", "takeover", "taken over", "user has control")) else "unavailable"
            state.update(status=code, message=MESSAGES.get(code, MESSAGES["unavailable"]))
            self._save(state)
            return self.status(), snapshot
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
            key = video_id + ":" + (day or label)
            records.setdefault(key, {"video_id": video_id, "url": "https://www.youtube.com/watch?v=" + video_id,
                "title": str(entry.get("title", ""))[:500], "channel_title": str(entry.get("channel_title", ""))[:200],
                "channel_id": str(entry.get("channel_id", ""))[:100],
                "history_day": day, "day_label": label, "occurred_at": "", "time_precision": "day" if day else "unknown",
                "captured_at": now.isoformat(), "provider": ORIGIN})
        return list(records.values())

    def _import(self, records, account, now, *, truncated=False, history_url="https://www.youtube.com/feed/history"):
        source = self.store.upsert_source(SourceItemInput(kind=ORIGIN, external_id=account,
            account_id=account, title="YouTube browser history", uri=history_url, observed_at=now,
            content=json.dumps([{key: value for key, value in item.items() if key != "captured_at"}
                for item in records], ensure_ascii=False, sort_keys=True),
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY, external_policy=ExternalPolicy.DENY_RAW,
            trust="authenticated_browser_dom", metadata={"coverage": "recent_loaded_history", "items": records,
                "refreshed_at": now.isoformat(), "truncated": truncated}))
        observations = []
        for item in records:
            if not item["history_day"]:
                continue
            key = sha256((account + ":" + item["video_id"] + ":" + item["history_day"]).encode()).hexdigest()
            observations.append(ObservationInput(origin=ORIGIN, action=ACTION, actor=ObservationActor.IMPORTED,
                trigger="youtube_history_page", source_id=source["source_id"], event_key=ORIGIN + ":" + key,
                payload=item, sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY, confidence=1.0, observed_at=now))
        inserted = self.store.record_observations(observations)
        return IngestionResult(stats={"records": len(records), **inserted}, cursor=now.isoformat(),
            cursor_state={"source_id": source["source_id"], "coverage": "recent_loaded_history"})

    def history(self, *, limit=20, channel=""):
        with self._lock:
            account = self._state().get("account_fingerprint", "")
            source = self._source(account)
            items = []
            if source:
                count = self.store.count_observations(origin=ORIGIN, action=ACTION, source_id=source["id"])
                for offset in range(0, count, 500):
                    rows = self.store.list_observation_details(origin=ORIGIN, action=ACTION, source_id=source["id"], limit=500, offset=offset)
                    items.extend(dict(row["payload"]) for row in rows)
                items.extend(item for item in source.get("metadata", {}).get("items", []) if not item.get("history_day"))
            if channel:
                from agent.plugins.youtube_takeout import filter_channel_history
                items = filter_channel_history(items, channel)
            items.sort(key=lambda item: (item["history_day"], item.get("captured_at", "")), reverse=True)
            return {"available": bool(items), "items": items[:max(1, min(int(limit), 500))], "total": len(items),
                "provider": ORIGIN, "freshness": self.status(), "coverage": "accumulated_recent_pages", "local_only": True,
                "timing_note": "Saved video/day entries are partial history; repeat plays, exact watch times and duration are unavailable."}


def current_browser_history():
    return browser_session("youtube_history")


class YouTubeBrowserHistoryService:
    """Fresh-read adapter over the same history ingestion and accumulation owner."""
    def __init__(self, *, store=None, browser_reader=None, clock=None):
        self._store = store
        self.browser_reader = browser_reader
        self.clock = clock

    @property
    def store(self):
        if self._store is None:
            return get_knowledge_core().store
        return self._store

    def refresh(self, *, automatic=False):
        return YouTubeBrowserHistory(store=self.store, clock=self.clock,
            browser=(browser_session if self.browser_reader is None else lambda *_args: self.browser_reader())).refresh_snapshot(automatic=automatic)
