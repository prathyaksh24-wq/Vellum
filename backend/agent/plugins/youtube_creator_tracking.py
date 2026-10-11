"""Adaptive creator assessment and bounded public Atom polling.

Explicit corrections win over inferred activity. Search queries and homepage
exposure are never watch signals. A feed is a short upload window, not history.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from email.utils import parsedate_to_datetime
import math
import re
import time
from uuid import uuid4
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import httpx

from agent.contracts.youtube_tracking import CreatorTrackingConfig, CreatorTrackingSnapshot
from agent.knowledge.models import SyncCursorInput
from agent.knowledge.runtime import get_knowledge_core

CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _name(value):
    return " ".join(str(value).casefold().split())


def _literal(value):
    return re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", str(value))


class AtomFeedReader:
    """Fixed host, no redirects, bounded response and parsing; no credentials."""
    def fetch(self, channel_id, state):
        if not CHANNEL.fullmatch(channel_id):
            raise ValueError("Invalid YouTube channel ID.")
        headers = {"User-Agent": "Vellum/1.0 (creator upload monitor)"}
        for key, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
            if state.get(key):
                headers[header] = str(state[key])[:500]
        with httpx.stream("GET", "https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id},
                          headers=headers, timeout=httpx.Timeout(8, connect=3), follow_redirects=False) as response:
            if response.status_code == 304:
                return {"unchanged": True, "entries": []}
            if response.status_code != 200:
                # Never persist provider bodies, credentials, or raw requests.
                return {"error": "feed_http_" + str(response.status_code),
                        "retry_after": str(response.headers.get("Retry-After", ""))[:100]}
            raw = bytearray()
            deadline = time.monotonic() + 12
            for chunk in response.iter_bytes(16384):
                if time.monotonic() > deadline:
                    raise ValueError("YouTube feed response exceeded its read deadline.")
                raw.extend(chunk)
                if len(raw) > 262144:
                    raise ValueError("YouTube feed exceeds the 256 KiB response limit.")
            return {"entries": self.parse(bytes(raw), channel_id), "etag": response.headers.get("ETag", "")[:500],
                    "last_modified": response.headers.get("Last-Modified", "")[:500]}

    @staticmethod
    def parse(raw, channel_id):
        # Require UTF-8, as used by the official feed. This also prevents a
        # UTF-16/32 document from hiding entity declarations behind NUL bytes.
        if b"\x00" in raw or len(raw) > 262144 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("Unsupported YouTube feed XML.")
        root = ET.fromstring(raw)
        if root.tag != ATOM + "feed" or root.findtext(YT + "channelId") != channel_id:
            raise ValueError("YouTube feed channel identity does not match.")
        entries = []
        for node in root.findall(ATOM + "entry")[:50]:
            video = node.findtext(YT + "videoId", "")
            channel = node.findtext(YT + "channelId", "")
            published = _time(node.findtext(ATOM + "published", ""))
            if not VIDEO.fullmatch(video) or channel != channel_id or not published:
                continue
            title = node.findtext(ATOM + "title", "").strip()[:500]
            creator = node.findtext(ATOM + "author/" + ATOM + "name", "").strip()[:200]
            if title:
                entries.append({"video_id": video, "title": title, "creator": creator,
                                "published_at": published.isoformat()})
        return entries


class YouTubeCreatorTracking:
    def __init__(self, *, store=None, reader=None, clock=None, metadata_provider=None, uploads_provider=None):
        self.store = store if store is not None else get_knowledge_core().store
        self.reader = reader or AtomFeedReader()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.metadata_provider = metadata_provider
        self.uploads_provider = uploads_provider

    def _settings(self):
        return dict((self.store.get_sync_cursor("youtube_creator_tracking", "settings") or {}).get("state") or {})

    def _config(self):
        saved = self._settings()
        return CreatorTrackingConfig.model_validate(saved["config"]) if saved.get("config") else None

    def configure(self, arguments):
        config = CreatorTrackingConfig.model_validate(arguments)
        # Preserve explicit exclusions across updates unless the user explicitly
        # replaces that exact rule with another relationship.
        previous = self._config()
        if previous and previous.account_id == config.account_id:
            keys = {rule.channel_id or _name(rule.name) for rule in config.rules}
            config.rules.extend(rule for rule in previous.rules if rule.relationship in {"excluded", "former"}
                                and (rule.channel_id or _name(rule.name)) not in keys)
        # Validate the merged rules before any writes: preserving corrections
        # must not let repeated configuration exceed the contract's bound.
        config = CreatorTrackingConfig.model_validate(config.model_dump())
        now = self.clock().isoformat()
        settings = self._settings()
        seeds = dict(settings.get("seeds") or {}) if previous and previous.account_id == config.account_id else {}
        seeds = {channel: seeded_at for channel, seeded_at in seeds.items()
                 if any(rule.channel_id == channel and rule.relationship == "current" for rule in config.rules)}
        for rule in config.rules:
            if rule.relationship == "current":
                seeds.setdefault(rule.channel_id, now)
        def topic_filters(value):
            return {rule.channel_id or _name(rule.name): sorted(term.casefold() for term in rule.topic_terms)
                    for rule in value.rules if rule.topic_terms}
        if previous and previous.account_id == config.account_id and (
                set(previous.history_accounts) != set(config.history_accounts)
                or previous.timezone != config.timezone or topic_filters(previous) != topic_filters(config)):
            self.store.youtube_tracking_reset_projection(config.account_id)
        self.store.save_sync_cursor(SyncCursorInput(connector="youtube_creator_tracking", account_id="settings",
            state={"config": config.model_dump(), "configured_at": now, "seeds": seeds}))
        blocked = [rule for rule in config.rules if rule.relationship in {"excluded", "former"}]
        self.store.youtube_tracking_exclude_preferences({rule.channel_id for rule in blocked if rule.channel_id},
            {_name(name) for rule in blocked for name in [rule.name, *rule.aliases]})
        return self.snapshot()

    def project(self, *, max_pages=10):
        config = self._config()
        if not config:
            return {"scanned": 0, "ready": False}
        now = self.clock()
        reference_day = now.astimezone(ZoneInfo(config.timezone)).date()
        checkpoint = self.store.get_sync_cursor("youtube_creator_projection", config.account_id) or {}
        after = int(checkpoint.get("cursor") or 0)
        scanned = 0
        for _ in range(min(max_pages, 200)):
            page = self.store.youtube_tracking_page(config.history_accounts, after)
            if not page:
                return {"scanned": scanned, "ready": True}
            events = []
            for row in page:
                payload = row["payload"]
                video = str(payload.get("video_id") or "")
                occurred = _time(row["observed_at"])
                day = str(payload.get("history_day") or "") if row["action"] == "youtube.history_presence" else \
                    occurred.astimezone(ZoneInfo(config.timezone)).date().isoformat() if occurred else ""
                try:
                    valid_day = date.fromisoformat(day) <= reference_day
                except ValueError:
                    valid_day = False
                # Explicit ad markers, when supplied by a source, never count.
                if not VIDEO.fullmatch(video) or not valid_day or payload.get("is_ad") or payload.get("activity_type") in {"ad", "advertisement"}:
                    continue
                channel = str(payload.get("channel_id") or "")
                creator_rule = self._rule(channel, payload.get("channel_title", ""), config)
                title = str(payload.get("title") or "")[:500]
                relevant = not creator_rule or not creator_rule.topic_terms or any(term.casefold() in title.casefold() for term in creator_rule.topic_terms)
                events.append({"video_id": video, "day": day, "channel_id": channel if CHANNEL.fullmatch(channel) else "",
                    "name": str(payload.get("channel_title") or "")[:200], "id": row["id"], "title": title, "relevant": relevant})
            after = page[-1]["position"]
            self.store.youtube_tracking_ingest(config.account_id, events, after, now.isoformat())
            scanned += len(page)
        return {"scanned": scanned, "ready": len(page) < 500}

    def _rule(self, channel, name, config):
        aliases = _name(name)
        excluded = [rule for rule in config.rules if rule.relationship == "excluded"]
        for rule in excluded:
            if rule.channel_id == channel or aliases in {_name(rule.name), *map(_name, rule.aliases)}:
                return rule
        return next((rule for rule in config.rules if rule.channel_id == channel), None)

    def snapshot(self, *, limit=20):
        config = self._config()
        if not config:
            return CreatorTrackingSnapshot().model_dump()
        now = self.clock()
        reference_day = now.astimezone(ZoneInfo(config.timezone)).date()
        stats = {row["channel_id"]: row for row in self.store.youtube_tracking_stats(config.account_id)}
        for rule in config.rules:
            if rule.channel_id:
                stats.setdefault(rule.channel_id, {"channel_id": rule.channel_id, "name": rule.name, "days": {}, "total": 0, "last_day": ""})
        creators = []
        seeds = self._settings().get("seeds") or {}
        for channel, row in stats.items():
            rule = self._rule(channel, row["name"], config)
            relationship = rule.relationship if rule else "auto"
            recent = {day: count for day, count in row["days"].items() if 0 <= (reference_day - date.fromisoformat(day)).days <= 21}
            days = len(recent)
            count = sum(recent.values())
            score = sum(min(count_, 3) * math.exp(-(reference_day - date.fromisoformat(day)).days / 14)
                        for day, count_ in recent.items())
            if relationship in {"excluded", "former"}:
                state, reason, score = "excluded" if relationship == "excluded" else "inactive", "Your explicit correction overrides watch history and subscription age.", 0.0
            elif relationship == "long_term":
                state, reason, score = "monitoring", "You identified a long-term creator relationship.", score + 3
            elif relationship == "current" and now - (_time(seeds.get(channel)) or now) <= timedelta(days=30):
                state, reason, score = "monitoring", "Your current-interest seed lasts 30 days; later activity determines monitoring.", score + 2
            elif days >= 3 and count >= 3:
                state, reason = "monitoring", "Repeated watches on at least three days in the last 21 days."
            elif relationship == "seasonal":
                state, reason = "seasonal_quiet", "Seasonal relationship retained; waiting for renewed repeated viewing."
            else:
                state, reason = "quiet", "Insufficient recent saved activity; this does not establish dislike."
            creators.append({"channel_id": channel, "name": rule.name if rule else row["name"], "relationship": relationship,
                "state": state, "score": round(score, 3), "recent_video_days": count, "recent_days": days,
                "total_video_days": row["total"], "last_watched": row["last_day"], "reason": reason,
                "topic_terms": rule.topic_terms if rule else []})
        creators.sort(key=lambda item: (-int(item["state"] == "monitoring" and item["relationship"] != "auto"),
            -int(item["state"] == "monitoring"), -item["score"], item["channel_id"]))
        # Capacity is explicit and deterministic. Protected exclusions still
        # remain visible through the separate exclusions field.
        selected = 0
        for creator in creators:
            if creator["state"] == "monitoring":
                selected += 1
                if selected > config.max_channels:
                    creator["state"] = "capacity_wait"
                    creator["reason"] = "Polling capacity is occupied by stronger current or explicit relationships."
        active_topics = {creator["channel_id"]: creator["topic_terms"] for creator in creators
                         if creator["state"] == "monitoring"}
        health = dict((self.store.get_sync_cursor("youtube_creator_health", config.account_id) or {}).get("state") or {})
        return CreatorTrackingSnapshot(configured=True, enabled=config.enabled, account_id=config.account_id,
            status=health.get("status", "awaiting_first_check") if config.enabled else "paused",
            last_checked_at=health.get("checked_at", ""), warnings=health.get("warnings", []),
            monitored_channels=health.get("monitored_channels", 0), baselined_channels=health.get("baselined_channels", 0),
            polling_limits={"max_channels": config.max_channels, "rss_requests_per_15_minutes": config.requests_per_run, "rss_requests_per_day": config.requests_per_day,
                            "fallback_units_per_day": config.fallback_units_per_day if config.api_fallback else 0},
            creators=creators[:max(1, min(limit, 100))], excluded=list(dict.fromkeys(rule.name for rule in config.rules if rule.relationship == "excluded")),
            uploads=[{key: str(row[key]) for key in ("channel_id", "video_id", "title", "creator", "published_at", "status")}
                     | {"url": "https://www.youtube.com/watch?v=" + row["video_id"]}
                     for row in self.store.youtube_tracking_uploads(config.account_id, limit=limit, topic_filters=active_topics)],
            pending_attribution=self.store.youtube_tracking_pending_count(config.account_id),
            unavailable_attribution=self.store.youtube_tracking_unavailable_count(config.account_id)).model_dump()

    def _bind_exclusions(self, config):
        additions = []
        for row in self.store.youtube_tracking_stats(config.account_id):
            rule = self._rule(row["channel_id"], row["name"], config)
            if rule and rule.relationship == "excluded" and rule.channel_id != row["channel_id"]:
                additions.append(rule.model_copy(update={"channel_id": row["channel_id"]}))
        if additions:
            known = {rule.channel_id for rule in config.rules if rule.channel_id}
            config.rules.extend(rule for rule in additions if rule.channel_id not in known and len(config.rules) < 200)
            settings = self._settings()
            settings["config"] = config.model_dump()
            self.store.save_sync_cursor(SyncCursorInput(connector="youtube_creator_tracking", account_id="settings", state=settings))

    def _attribute(self, config, now):
        state = dict((self.store.get_sync_cursor("youtube_creator_attribution", config.account_id) or {}).get("state") or {})
        if (_time(state.get("next_at")) or now) > now:
            return
        videos = self.store.youtube_tracking_pending(config.account_id)
        if not videos:
            return
        try:
            if self.metadata_provider is None:
                from agent.plugins.youtube_runtime import youtube_client
                provider = youtube_client().video_channels
            else:
                provider = self.metadata_provider
            metadata = {video: item for video, item in provider(videos).items()
                        if video in videos and CHANNEL.fullmatch(str(item.get("channel_id", "")))}
            for item in metadata.values():
                creator_rule = self._rule(item["channel_id"], item["name"], config)
                item["topic_terms"] = creator_rule.topic_terms if creator_rule else []
            self.store.youtube_tracking_attribute(config.account_id, metadata)
            # Unavailable videos remain evidence without creator attribution;
            # do not let a permanently missing ID starve the queue.
            self.store.youtube_tracking_unavailable(config.account_id, set(videos) - set(metadata))
            state = {"next_at": (now + timedelta(minutes=15)).isoformat(), "status": "ready"}
        except Exception:
            state = {"next_at": (now + timedelta(hours=1)).isoformat(), "status": "metadata_unavailable"}
        self.store.save_sync_cursor(SyncCursorInput(connector="youtube_creator_attribution", account_id=config.account_id, state=state))

    def refresh(self, *, deliver=None):
        config = self._config()
        if not config or not config.enabled:
            return {"status": "paused", "requests": 0, "delivered": 0}
        now, owner = self.clock(), uuid4().hex
        if not self.store.youtube_tracking_lock(config.account_id, owner, now.timestamp(), duration=600):
            return {"status": "busy", "requests": 0, "delivered": 0}
        try:
            projection = self.project()
            self._attribute(config, now)
            self._bind_exclusions(config)
            creators = self.snapshot(limit=100)["creators"]
            active = {item["channel_id"]: item for item in creators if item["state"] == "monitoring"}
            budget_key = config.account_id + ":budget"
            budget = dict((self.store.get_sync_cursor("youtube_creator_feed", budget_key) or {}).get("state") or {})
            if budget.get("day") != now.date().isoformat():
                budget.update(day=now.date().isoformat(), requests=0, fallback_units=0)
            # Retain individual reservations, rather than a fixed-window
            # counter that permits two bursts around a window boundary.
            request_times = list(budget.get("request_times") or [])
            if "request_times" not in budget and _time(budget.get("window_start")):
                # Conservatively migrate earlier fixed-window reservations.
                request_times = [budget["window_start"]] * min(int(budget.get("window_requests", 0)), 10)
            budget["request_times"] = [stamp for stamp in request_times
                if _time(stamp) and _time(stamp) > now - timedelta(minutes=15)]
            budget.pop("window_start", None)
            budget.pop("window_requests", None)
            states = {channel: dict((self.store.get_sync_cursor("youtube_creator_feed", config.account_id+":"+channel) or {}).get("state") or {}) for channel in active}
            due = sorted(active, key=lambda channel: states[channel].get("next_at", ""))
            requests_made = 0
            warnings = []
            fallback_checks = 0
            for channel in due:
                state = states[channel]
                request_now = self.clock()
                if budget.get("day") != request_now.date().isoformat():
                    budget.update(day=request_now.date().isoformat(), requests=0, fallback_units=0)
                budget["request_times"] = [stamp for stamp in budget["request_times"]
                    if _time(stamp) > request_now - timedelta(minutes=15)]
                if (_time(state.get("next_at")) or request_now) > request_now:
                    continue
                if len(budget["request_times"]) >= config.requests_per_run or budget["requests"] >= config.requests_per_day or (_time(budget.get("provider_next_at")) or request_now) > request_now:
                    break
                # Reserve before I/O: crashes cannot bypass daily budgeting.
                budget["requests"] += 1
                budget["request_times"].append(request_now.isoformat())
                requests_made += 1
                self.store.save_sync_cursor(SyncCursorInput(connector="youtube_creator_feed", account_id=budget_key, state=budget))
                try:
                    result = self.reader.fetch(channel, state)
                except Exception:
                    result = {"error": "feed_unavailable"}
                if (result.get("error") in {"feed_http_404", "feed_http_500", "feed_http_502", "feed_http_503", "feed_http_504", "feed_unavailable"}
                        and config.api_fallback and budget.get("fallback_units", 0) + 2 <= config.fallback_units_per_day):
                    # Reserve the worst case (playlist discovery + list) before
                    # I/O; cached lookups use one call but never exceed budget.
                    budget["fallback_units"] = budget.get("fallback_units", 0) + 2
                    self.store.save_sync_cursor(SyncCursorInput(connector="youtube_creator_feed", account_id=budget_key, state=budget))
                    fallback_checks += 1
                    try:
                        if self.uploads_provider is None:
                            from agent.plugins.youtube_runtime import youtube_client
                            provider = youtube_client().channel_uploads
                        else:
                            provider = self.uploads_provider
                        result = provider(channel, playlist_id=str(state.get("uploads_playlist", "")))
                    except Exception:
                        result = {"error": "feed_and_uploads_unavailable"}
                if result.get("error"):
                    failures = min(int(state.get("failures", 0)) + 1, 8)
                    retry = _time(result.get("retry_after"))
                    if not retry and result.get("retry_after"):
                        try:
                            retry = parsedate_to_datetime(result["retry_after"]).astimezone(UTC)
                        except (ValueError, TypeError):
                            pass
                    try:
                        retry = now + timedelta(seconds=min(max(int(result.get("retry_after", "")), 0), 86400))
                    except ValueError:
                        pass
                    delay = now + timedelta(seconds=min(900 * 2**failures, 86400))
                    state.update(failures=failures, error=result["error"], next_at=max(delay, retry or now).isoformat())
                    warnings.append(active[channel]["name"] + ": " + result["error"])
                    self.store.youtube_tracking_save_feed(config.account_id, channel, [], state, now.isoformat())
                    if result["error"] == "feed_http_429":
                        budget["provider_next_at"] = state["next_at"]
                        self.store.save_sync_cursor(SyncCursorInput(connector="youtube_creator_feed", account_id=budget_key, state=budget))
                        break
                    continue
                baseline = not state.get("initialized")
                entries = []
                for item in result.get("entries", [])[:50]:
                    if not VIDEO.fullmatch(str(item.get("video_id", ""))):
                        continue
                    published = _time(item.get("published_at"))
                    relevant = not active[channel]["topic_terms"] or any(term.casefold() in item["title"].casefold() for term in active[channel]["topic_terms"])
                    eligible = published and now - timedelta(days=2) <= published <= now and relevant
                    entries.append(item | {"status": "baseline" if baseline and relevant else "pending" if not baseline and eligible else "suppressed"})
                state.update(initialized=True, failures=0, error="", last_success=now.isoformat(), next_at=(now+timedelta(minutes=30)).isoformat())
                for key in ("etag", "last_modified"):
                    if key in result:
                        state[key] = result[key]
                if result.get("uploads_playlist"):
                    state["uploads_playlist"] = result["uploads_playlist"]
                state["transport"] = result.get("transport", "youtube_atom")
                self.store.youtube_tracking_save_feed(config.account_id, channel, entries, state, now.isoformat())
            delivered = 0
            if deliver is not None:
                for item in self.store.youtube_tracking_uploads(config.account_id, pending=True):
                    creator = active.get(item["channel_id"])
                    relevant = creator and (not creator["topic_terms"] or any(term.casefold() in item["title"].casefold() for term in creator["topic_terms"]))
                    if not relevant or (_time(item["published_at"]) or now) < now - timedelta(days=2):
                        self.store.youtube_tracking_ack(config.account_id, item["channel_id"], item["video_id"], "suppressed")
                        continue
                    delivery_id = "youtube-upload-" + sha256((config.account_id+":"+item["channel_id"]+":"+item["video_id"]).encode()).hexdigest()[:24]
                    url = "https://www.youtube.com/watch?v=" + item["video_id"]
                    phrasing = ("{name} has a new upload: {title}\n{url}", "New from {name}: {title}\n{url}", "{name} just uploaded {title}\n{url}")
                    text = phrasing[int(sha256(item["video_id"].encode()).hexdigest()[:2], 16) % 3].format(name=_literal(creator["name"]), title=_literal(item["title"]), url=url)
                    deliver(delivery_id, text)
                    self.store.youtube_tracking_ack(config.account_id, item["channel_id"], item["video_id"])
                    delivered += 1
            self.store.youtube_tracking_prune(config.account_id, (now-timedelta(days=90)).isoformat())
            # Surface persisting backoff errors even on ticks that make no I/O.
            baselined = 0
            for channel in active:
                saved = dict((self.store.get_sync_cursor("youtube_creator_feed", config.account_id+":"+channel) or {}).get("state") or {})
                baselined += int(bool(saved.get("initialized")))
                warning = active[channel]["name"] + ": " + str(saved.get("error", ""))
                if saved.get("error") and warning not in warnings:
                    warnings.append(warning)
                last = _time(saved.get("last_success"))
                if last and now - last > timedelta(days=1):
                    warnings.append(active[channel]["name"] + ": feed coverage has a gap; uploads outside the short feed window may be missing.")
            metadata_state = (self.store.get_sync_cursor("youtube_creator_attribution", config.account_id) or {}).get("state") or {}
            if metadata_state.get("status") == "metadata_unavailable":
                warnings.append("Public video ownership metadata is unavailable; unattributed activity is not used to select creators.")
            status = "partial" if warnings or not projection["ready"] else "baselining" if baselined < len(active) else "ready"
            self.store.save_sync_cursor(SyncCursorInput(connector="youtube_creator_health", account_id=config.account_id,
                state={"status": status, "checked_at": now.isoformat(), "warnings": warnings,
                       "monitored_channels": len(active), "baselined_channels": baselined}))
            return {"status": status, "requests": requests_made, "fallback_checks": fallback_checks, "delivered": delivered, "projection": projection}
        finally:
            self.store.youtube_tracking_unlock(config.account_id, owner)
