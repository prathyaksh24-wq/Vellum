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

from agent.contracts.youtube_tracking import CreatorTrackingConfig, CreatorTrackingSnapshot, CreatorTrackingRead, SavedCreatorUploads
from agent.knowledge.models import SyncCursorInput
from agent.knowledge.runtime import get_knowledge_core

CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
TOPICS = {
    "basketball": ("nba", "wnba", "basketball", "lakers", "warriors", "lebron", "curry", "celtics", "knicks", "dunk"),
    "american_football": ("nfl", "super bowl", "quarterback", "touchdown", "mahomes", "ravens", "chiefs", "cowboys"),
    "formula_one": ("f1", "formula 1", "formula one", "grand prix", "verstappen", "hamilton", "ferrari", "mclaren"),
    "chess": ("chess", "magnus", "carlsen", "checkmate", "gukesh", "praggnanandhaa", "gothamchess"),
    "clash_royale": ("clash royale", "clashroyale", "megaknight", "mega knight", "hog rider"),
    "technology": ("iphone", "smartphone", "pixel", "macbook", "samsung", "android", "apple", "tech review", "technology"),
    "ai": ("ai", "agentic", "llm", "ollama", "openai", "claude", "gpt", "artificial intelligence"),
}
TOPIC_PATTERNS = {topic: re.compile(r"\b(?:"+'|'.join(re.escape(term) for term in terms)+r")\b", re.I)
                  for topic,terms in TOPICS.items()}
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
    def __init__(self, *, store=None, reader=None, clock=None, metadata_provider=None, uploads_provider=None, duration_provider=None, conversation_provider=None, channel_profile_provider=None):
        self.store = store if store is not None else get_knowledge_core().store
        self.reader = reader or AtomFeedReader()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.metadata_provider = metadata_provider
        self.uploads_provider = uploads_provider
        self.duration_provider = duration_provider
        self.conversation_provider = conversation_provider
        self.channel_profile_provider = channel_profile_provider

    def _settings(self):
        return dict((self.store.get_sync_cursor("youtube_creator_tracking", "settings") or {}).get("state") or {})

    def _config(self):
        saved = self._settings()
        return CreatorTrackingConfig.model_validate(saved["config"]) if saved.get("config") else None

    def authorization_required(self, config):
        if not config.min_duration_seconds or self.duration_provider is not None:
            return False
        from agent.plugins.youtube_runtime import youtube_status
        return bool(youtube_status().get('authorization_required'))

    def resume_after_authorization(self, channel_id):
        """Release failed checks only for the verified, explicitly linked account."""
        config=self._config()
        if not config or (config.subscription_account_id or config.account_id)!=channel_id:
            return False
        now,owner=self.clock(),uuid4().hex
        self.store.save_sync_cursor(SyncCursorInput(connector='youtube_push_reauthorization',account_id=config.account_id,
            state={'channel_id':channel_id,'pending':True}))
        if not self.store.youtube_tracking_lock(config.account_id,owner,now.timestamp(),duration=60):
            return False
        try:
            state=dict((self.store.get_sync_cursor('youtube_upload_durations',config.account_id) or {}).get('state') or {})
            state.pop('provider_next_at',None)
            pending={row['video_id'] for row in self.store.youtube_tracking_uploads(config.account_id,pending=True,limit=10000)}
            for video,item in (state.get('videos') or {}).items():
                if video in pending and item.get('duration_seconds') is None:
                    item['next_at']=now.isoformat()
            self.store.save_sync_cursor(SyncCursorInput(connector='youtube_upload_durations',account_id=config.account_id,state=state))
            self.store.save_sync_cursor(SyncCursorInput(connector='youtube_push_subscription_sync',account_id=config.account_id,
                state={'status':'pending','next_at':now.isoformat(),'subscription_account_id':channel_id}))
            self.store.save_sync_cursor(SyncCursorInput(connector='youtube_push_reauthorization',account_id=config.account_id,
                state={'channel_id':channel_id,'pending':False}))
            return True
        finally:
            self.store.youtube_tracking_unlock(config.account_id,owner)

    def configure(self, arguments):
        config = CreatorTrackingConfig.model_validate(arguments)
        if set(config.topic_preferences)-set(TOPICS):
            raise ValueError("Choose a supported YouTube interest topic.")
        # Preserve explicit exclusions across updates unless the user explicitly
        # replaces that exact rule with another relationship.
        previous = self._config()
        if previous and previous.account_id == config.account_id:
            if 'subscription_account_id' not in arguments:
                config.subscription_account_id = previous.subscription_account_id
            keys = {rule.channel_id or _name(rule.name) for rule in config.rules}
            config.rules.extend(rule for rule in previous.rules if rule.relationship in {"excluded", "former"}
                                and (rule.channel_id or _name(rule.name)) not in keys)
        # Validate the merged rules before any writes: preserving corrections
        # must not let repeated configuration exceed the contract's bound.
        config = CreatorTrackingConfig.model_validate(config.model_dump())
        now = self.clock().isoformat()
        settings = self._settings()
        topic_seeds = dict(settings.get("topic_seeds") or {}) if previous and previous.account_id==config.account_id else {}
        topic_seeds = {topic: stamp for topic,stamp in topic_seeds.items() if config.topic_preferences.get(topic)=="current"}
        for topic,preference in config.topic_preferences.items():
            if preference=="current":
                topic_seeds.setdefault(topic,now)
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
            state={"config": config.model_dump(), "configured_at": now, "seeds": seeds, "topic_seeds":topic_seeds}))
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

    def snapshot(self, *, limit=20, apply_capacity=True):
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
        messages = self._conversation_messages(config)
        topic_profile = self._topic_profile(config, reference_day, messages=messages)
        active_interest_topics = topic_profile["active_topics"]
        blocked_topics={topic for topic,value in topic_profile['evidence'].items() if value.get('excluded')}
        related_candidates={topic:[] for topic in active_interest_topics}
        for channel,row in stats.items():
            rule=self._rule(channel,row['name'],config)
            recent_days=sum(0 <= (reference_day-date.fromisoformat(day)).days<=21 for day in row['days'])
            seeded=rule and rule.relationship=='current' and now-(_time(seeds.get(channel)) or now)<=timedelta(days=30)
            if recent_days>=3 or seeded or rule and rule.relationship in {'long_term','excluded','former'}:
                continue
            for topic in active_interest_topics:
                support=topic_profile['channels'].get(channel,{}).get(topic,0)
                if support>=3 and (not rule or not rule.topic_terms or any(TOPIC_PATTERNS[topic].search(term) for term in rule.topic_terms)):
                    related_candidates[topic].append((channel,support,row['last_day']))
        related_candidates={topic:{item[0] for item in sorted(items,key=lambda item:(-item[1],-date.fromisoformat(item[2]).toordinal(),item[0]))[:config.related_channels_per_topic]}
                            for topic,items in related_candidates.items()}
        for channel, row in stats.items():
            rule = self._rule(channel, row["name"], config)
            relationship = rule.relationship if rule else "auto"
            recent = {day: count for day, count in row["days"].items() if 0 <= (reference_day - date.fromisoformat(day)).days <= 21}
            days = len(recent)
            count = sum(recent.values())
            score = sum(min(count_, 3) * math.exp(-(reference_day - date.fromisoformat(day)).days / 14)
                        for day, count_ in recent.items())
            related = [topic for topic in active_interest_topics
                       if topic_profile["channels"].get(channel,{}).get(topic,0)>=3 and
                       (not rule or not rule.topic_terms or any(TOPIC_PATTERNS[topic].search(term) for term in rule.topic_terms))]
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
            affinity=topic_profile['channels'].get(channel,{})
            blocked_support=sum(count for topic,count in affinity.items() if topic in blocked_topics)
            if relationship not in {'excluded','former'} and blocked_support>=3 and blocked_support*2>=sum(affinity.values()):
                state,reason,score='inactive','Your explicit topic correction overrides earlier viewing.',0.0
            promoted=[topic for topic in related if channel in related_candidates[topic]]
            if config.related_discovery and promoted and relationship not in {"excluded","former"} and state in {"quiet","seasonal_quiet"}:
                state,reason = "monitoring", "Related to your current " + ', '.join(promoted) + " interest; supported by prior watches on at least three days."
                score += 1.5 + sum(min(topic_profile['channels'][channel][topic],12)/12 for topic in promoted)
            terms = rule.topic_terms if rule else []
            if config.related_discovery and related and not terms and (not rule or relationship=="seasonal"):
                # Broad related channels are limited to the activated topics.
                terms = list(dict.fromkeys(term for topic in related for term in TOPICS[topic]))
            creators.append({"channel_id": channel, "name": rule.name if rule else row["name"], "relationship": relationship,
                "state": state, "score": round(score, 3), "recent_video_days": count, "recent_days": days,
                "total_video_days": row["total"], "last_watched": row["last_day"], "reason": reason,
                "topic_terms": terms})
        frequencies = self._notification_preferences(config, creators, messages=messages)
        pacing=(self.store.get_sync_cursor('youtube_notification_frequency',config.account_id) or {}).get('state') or {}
        weekly_open=not _time(pacing.get('last_rediscovery_at')) or _time(pacing['last_rediscovery_at'])<=now-timedelta(days=7)
        for creator in creators:
            creator['notification_frequency'] = frequencies[creator['channel_id']]
            last_watch=date.fromisoformat(creator['last_watched']) if creator['last_watched'] else reference_day
            previous=_time((pacing.get('rediscovered') or {}).get(creator['channel_id']))
            creator['rediscovery']=bool(config.rediscovery_notifications and weekly_open and
                creator['state'] in {'quiet','seasonal_quiet'} and frequencies[creator['channel_id']]!='muted' and
                creator['total_video_days']>=10 and (reference_day-last_watch).days>=90 and
                (not previous or previous<=now-timedelta(days=90)))
        creators.sort(key=lambda item: (-int(item["state"] == "monitoring" and item["relationship"] != "auto"),
            -int(item["state"] == "monitoring"), -item["score"], item["channel_id"]))
        # Capacity is explicit and deterministic. Protected exclusions still
        # remain visible through the separate exclusions field.
        selected = 0
        for creator in creators:
            if creator["state"] == "monitoring":
                selected += 1
                if apply_capacity and selected > config.max_channels:
                    creator["state"] = "capacity_wait"
                    creator["reason"] = "Polling capacity is occupied by stronger current or explicit relationships."
        active_topics = {creator["channel_id"]: creator["topic_terms"] for creator in creators
                         if creator["state"] == "monitoring"}
        health = dict((self.store.get_sync_cursor("youtube_creator_health", config.account_id) or {}).get("state") or {})
        durations = self._verified_durations(config)
        uploads=self.store.youtube_tracking_uploads(config.account_id,limit=100,topic_filters=active_topics,
                    min_duration_seconds=config.min_duration_seconds,durations=durations)
        selected_creators={creator['channel_id']:creator for creator in creators if creator['state']=='monitoring'}
        def feed_rank(upload):
            age=max((now-(_time(upload['published_at']) or now)).total_seconds()/3600,0)
            return math.exp(-age/48)*(1+math.log1p(max(selected_creators[upload['channel_id']]['score'],0)))
        uploads.sort(key=lambda upload:(-feed_rank(upload),upload['video_id']))
        return CreatorTrackingSnapshot(configured=True, enabled=config.enabled, account_id=config.account_id,
            rediscovery_notifications=config.rediscovery_notifications,
            status=health.get("status", "awaiting_first_check") if config.enabled else "paused",
            last_checked_at=health.get("checked_at", ""), warnings=health.get("warnings", []),
            monitored_channels=health.get("monitored_channels", 0), baselined_channels=health.get("baselined_channels", 0),
            polling_limits={"max_channels": config.max_channels, "rss_requests_per_15_minutes": config.requests_per_run, "rss_requests_per_day": config.requests_per_day,
                            "duration_units_per_day": config.duration_units_per_day if config.min_duration_seconds else 0,
                            "discovery_units_per_day": config.discovery_units_per_day if config.related_discovery else 0,
                            "fallback_units_per_day": config.fallback_units_per_day if config.api_fallback else 0},
            min_duration_seconds=config.min_duration_seconds, pending_duration_checks=health.get("pending_duration_checks", 0),
            active_topics=active_interest_topics,topic_evidence=topic_profile["evidence"],
            creators=creators[:max(1, min(limit, 100 if apply_capacity else 10000))], excluded=list(dict.fromkeys(rule.name for rule in config.rules if rule.relationship == "excluded")),
            uploads=[{key: str(row[key]) for key in ("channel_id", "video_id", "title", "creator", "published_at", "status")}
                     | {"url": "https://www.youtube.com/watch?v=" + row["video_id"],
                        "reason":selected_creators[row['channel_id']]['reason'],
                        "duration_seconds":str(durations.get(row['video_id']+':'+row['channel_id'],'') )}
                     for row in uploads[:max(1,min(limit,100))]],
            pending_attribution=self.store.youtube_tracking_pending_count(config.account_id),
            unavailable_attribution=self.store.youtube_tracking_unavailable_count(config.account_id)).model_dump()

    def _topic_profile(self, config, reference_day, *, messages=None):
        cursor=(self.store.get_sync_cursor("youtube_creator_projection",config.account_id) or {}).get("cursor","")
        attribution=(self.store.get_sync_cursor("youtube_creator_attribution",config.account_id) or {}).get("state",{})
        public_profiles=(self.store.get_sync_cursor('youtube_creator_public_profiles',config.account_id) or {}).get('state') or {}
        searches=self.store.youtube_tracking_search_rows(config.history_accounts,since=(self.clock()-timedelta(days=22)).isoformat())
        signature=sha256(str((cursor,reference_day.isoformat(),attribution,config.history_accounts,config.timezone,public_profiles.get('revision',0),
                             [row['position'] for row in searches],[rule.model_dump() for rule in config.rules])).encode()).hexdigest()
        saved=(self.store.get_sync_cursor("youtube_creator_topics",config.account_id) or {}).get("state") or {}
        if saved.get("signature")!=signature:
            channels,watched,searched,days={},{topic:set() for topic in TOPICS},{topic:set() for topic in TOPICS},{}
            rows=self.store.youtube_tracking_topic_rows(config.account_id,since=(reference_day-timedelta(days=366)).isoformat(),before=reference_day.isoformat())
            for row in rows:
                rule=self._rule(row['channel_id'],row['name'],config)
                if rule and rule.relationship in {'excluded','former'}:
                    continue
                days.setdefault(row['channel_id'],set()).add(row['day'])
                for topic,pattern in TOPIC_PATTERNS.items():
                    if pattern.search(row['title']):
                        channels.setdefault(row['channel_id'],{}).setdefault(topic,set()).add(row['day'])
                        if (reference_day-date.fromisoformat(row['day'])).days<=21:
                            watched[topic].add(row['day'])
            for channel,profile in public_profiles.get('channels',{}).items():
                if len(days.get(channel,[]))<3 or (_time(profile.get('checked_at')) or self.clock()) < self.clock()-timedelta(days=30):
                    continue
                for topic in profile.get('topics',[]):
                    if topic in TOPICS:
                        channels.setdefault(channel,{}).setdefault(topic,set()).update(days[channel])
                        watched[topic].update(day for day in days[channel] if (reference_day-date.fromisoformat(day)).days<=21)
            for row in searches:
                when=_time(row['observed_at'])
                day=when.astimezone(ZoneInfo(config.timezone)).date() if when else None
                if day is not None and 0 <= (reference_day-day).days<=21:
                    for topic,pattern in TOPIC_PATTERNS.items():
                        if pattern.search(str(row['query'])):
                            searched[topic].add(day.isoformat())
            saved={'signature':signature,'channels':{channel:{topic:len(days) for topic,days in topics.items()} for channel,topics in channels.items()},
                   'evidence':{topic:{'watch_days':len(watched[topic]),'search_days':len(searched[topic])} for topic in TOPICS},
                   'truncated':len(rows)==50000}
            self.store.save_sync_cursor(SyncCursorInput(connector='youtube_creator_topics',account_id=config.account_id,state=saved))
        evidence={topic:dict(value) for topic,value in saved['evidence'].items()}
        seeds=self._settings().get('topic_seeds') or {}
        declarations=self._conversation_topics(config, messages=messages)
        active=[]
        for topic,counts in evidence.items():
            declared=config.topic_preferences.get(topic)=='current' and self.clock()-(_time(seeds.get(topic)) or self.clock())<=timedelta(days=30)
            preference=config.topic_preferences.get(topic)
            statement=declarations.get(topic)
            if statement and (topic not in config.topic_preferences or (_time(statement['at']) or self.clock()) > (_time(self._settings().get('configured_at')) or self.clock())):
                preference=statement['preference']
                declared=preference=='current'
                counts['conversation_preference']=preference
            counts['declared_current']=declared
            counts['excluded']=preference=='excluded'
            if preference!='excluded' and (declared or counts['watch_days']>=3 or counts['watch_days']>=2 and counts['search_days']>=2):
                active.append(topic)
        return {'channels':saved['channels'],'active_topics':active,'evidence':evidence,'truncated':saved.get('truncated',False)}

    def _upload_relevant(self, creator, title, blocked_topics):
        return bool(creator and (not creator['topic_terms'] or any(term.casefold() in title.casefold() for term in creator['topic_terms']))
                    and not any(TOPIC_PATTERNS[topic].search(title) for topic in blocked_topics))

    def _conversation_messages(self, config):
        """Only direct recent user declarations; no assistant text or quoted examples."""
        if not config.conversation_topics:
            return []
        if self.conversation_provider is not None:
            chats=self.conversation_provider()
        else:
            from agent.config import REPO_ROOT
            from agent.conversations.lifecycle import ConversationLifecycle
            from agent.memory.runtime import get_memory_orchestrator
            from agent.master.state import MasterThreadStateStore
            settings=get_memory_orchestrator().store.get_settings()
            if any(settings.get(key,True) is False for key in ('memory_enabled','reference_history_enabled','save_new_memories')):
                return []
            thread_states=MasterThreadStateStore()
            chats=sorted(ConversationLifecycle(path=REPO_ROOT/'data'/'ui'/'conversations.json').list(),
                         key=lambda row:row.get('updated_at',''),reverse=True)[:200]
            chats=[chat for chat in chats if not chat.get('archived') and
                   thread_states.get(chat.get('thread_id') or chat['id']).store_to_memory]
        messages=[]
        for chat in sorted(chats,key=lambda row:row.get('updated_at',''),reverse=True)[:200]:
            if (chat.get('archived') or chat.get('temporary') or chat.get('profile_eligible') is False
                    or chat.get('memory_enabled') is False or chat.get('memoryEnabled') is False):
                continue
            users=[message for message in chat.get('messages',[]) if message.get('role')=='user']
            for message in users[-20:]:
                at=_time(message.get('created_at') or message.get('timestamp'))
                # Without a message timestamp, only the latest user turn has a
                # conservative chat-update anchor; older statements stay unused.
                if at is None and message is users[-1]:
                    at=_time(chat.get('updated_at'))
                if not at or not self.clock()-timedelta(days=30)<=at<=self.clock():
                    continue
                text=str(message.get('text') or '')[:1000]
                if any(mark in text for mark in ('?', '"', '`', '>')) or re.search(r'\b(?:if|example|suppose|pretend|hypothetical|roleplay|demonstration|he said|she said)\b',text,re.I):
                    continue
                messages.append((at,text))
        return sorted(messages,key=lambda item:item[0])

    def _conversation_topics(self, config, *, messages=None):
        declarations={}
        for at,text in self._conversation_messages(config) if messages is None else messages:
            # Notification volume is a channel preference, not evidence that
            # an entire topic is unwanted (e.g. ChessBase India vs chess).
            if re.search(r'\b(?:notifications?|pings?|alerts?)\b',text,re.I):
                continue
            negative=re.search(r"\b(?:i (?:do not|don't|no longer) (?:watch|like|enjoy)|i (?:have )?lost interest in|stop (?:tracking|following))\b",text,re.I)
            positive=re.search(r"\bi(?: am|'m| have been)?(?: really| currently| now)? (?:like|love|enjoy|watch|watching|into|interested in)\b",text,re.I)
            if not negative and not positive:
                continue
            clause=text[(negative or positive).end():].split('.')[0]
            for topic,pattern in TOPIC_PATTERNS.items():
                if pattern.search(clause) and (topic not in declarations or at>_time(declarations[topic]['at'])):
                    declarations[topic]={'preference':'excluded' if negative else 'current','at':at.isoformat()}
        return declarations

    def _notification_preferences(self, config, creators, *, messages=None):
        frequencies={item['channel_id']:(self._rule(item['channel_id'],item['name'],config).notification_frequency
            if self._rule(item['channel_id'],item['name'],config) else 'adaptive') for item in creators}
        saved=dict((self.store.get_sync_cursor('youtube_notification_preferences',config.account_id) or {}).get('state') or {})
        preferences=dict(saved.get('channels') or {})
        previous=dict(preferences)
        configured_at=_time(self._settings().get('configured_at'))
        for channel,preference in preferences.items():
            if channel in frequencies and preference.get('frequency') in {'adaptive','reduced','muted'}:
                if frequencies[channel]=='adaptive' or not configured_at or (_time(preference.get('at')) or self.clock())>configured_at:
                    frequencies[channel]=preference['frequency']
        for at,text in self._conversation_messages(config) if messages is None else messages:
            if not re.search(r'\b(?:notifications?|pings?|alerts?)\b',text,re.I):
                continue
            if re.search(r"\b(?:don'?t|do not|never) (?:mute|stop|disable)\b|\bnot (?:fewer|less|more)\b",text,re.I):
                continue
            muted=re.search(r"\b(?:mute|silence|disable|stop|no more|don'?t send|do not send)\b",text,re.I)
            reduced=re.search(r"\b(?:fewer|less|reduce|lower|too many|overwhelming|don'?t like|do not like)\b",text,re.I)
            restore=re.search(r'\b(?:more|resume|unmute|restore|normal)\b',text,re.I)
            frequency='muted' if muted else 'reduced' if reduced else 'adaptive' if restore else None
            if frequency is None:
                continue
            normalized=' '+re.sub(r'[^\w]+',' ',text.casefold()).strip()+' '
            matched=[]
            for item in creators:
                rule=self._rule(item['channel_id'],item['name'],config)
                names=[item['name'],*(rule.aliases if rule else [])]
                aliases=[re.sub(r'[^\w]+',' ',name.casefold()).strip() for name in names]
                if any(alias and (' '+alias+' ' in normalized or ' '+alias.replace(' ','')+' ' in normalized) for alias in aliases):
                    matched.append(item['channel_id'])
            # Ambiguous names do not silently apply to multiple creators.
            if len(matched)==1:
                channel=matched[0]
                if at>=(_time((preferences.get(channel) or {}).get('at')) or datetime.min.replace(tzinfo=UTC)):
                    frequencies[channel]=frequency
                    preferences[channel]={'frequency':frequency,'at':at.isoformat()}
        if preferences!=previous:
            preferences=dict(sorted(preferences.items(),key=lambda item:item[1]['at'])[-1000:])
            self.store.save_sync_cursor(SyncCursorInput(connector='youtube_notification_preferences',account_id=config.account_id,
                state={'channels':preferences}))
        return frequencies

    def _discover_channel_profiles(self, config, budget):
        if not config.related_discovery or not config.discovery_units_per_day:
            return
        day=self.clock().astimezone(ZoneInfo(config.timezone)).date()
        topics=self._topic_profile(config,day)
        if not topics['active_topics']:
            return
        now=self.clock()
        state=dict((self.store.get_sync_cursor('youtube_creator_public_profiles',config.account_id) or {}).get('state') or {})
        if (_time(state.get('next_at')) or now)>now:
            return
        profiles=dict(state.get('channels') or {})
        candidates=[]
        for row in self.store.youtube_tracking_stats(config.account_id):
            rule=self._rule(row['channel_id'],row['name'],config)
            if rule and rule.relationship in {'excluded','former'}:
                continue
            support=sum(0 <= (day-date.fromisoformat(stamp)).days<=366 for stamp in row['days'])
            if support>=3 and (row['channel_id'] not in profiles or (_time(profiles[row['channel_id']].get('checked_at')) or now)<now-timedelta(days=30)):
                candidates.append(row['channel_id'])
        if budget.get('day')!=now.date().isoformat():
            budget.update(day=now.date().isoformat(),requests=0,fallback_units=0,duration_units=0,discovery_units=0)
        if not candidates or budget.get('discovery_units',0)>=config.discovery_units_per_day:
            return
        budget['discovery_units']=budget.get('discovery_units',0)+1
        self.store.save_sync_cursor(SyncCursorInput(connector='youtube_creator_feed',account_id=config.account_id+':budget',state=budget))
        state['next_at']=(now+timedelta(hours=1)).isoformat()
        self.store.save_sync_cursor(SyncCursorInput(connector='youtube_creator_public_profiles',account_id=config.account_id,state=state))
        batch=candidates[:50]
        try:
            if self.channel_profile_provider is None:
                from agent.plugins.youtube_runtime import youtube_client
                provider=youtube_client().channel_profiles
            else:
                provider=self.channel_profile_provider
            metadata=provider(batch)
            for channel in batch:
                item=metadata.get(channel) or {}
                text=(str(item.get('description',''))+' '+ ' '.join(item.get('categories',[]))).replace('_',' ')[:3500]
                profiles[channel]={'topics':[topic for topic,pattern in TOPIC_PATTERNS.items() if pattern.search(text)],'checked_at':now.isoformat()}
            state['channels']=dict(sorted(profiles.items(),key=lambda pair:pair[1]['checked_at'])[-1000:])
            state['revision']=int(state.get('revision',0))+1
            state['status']='ready'
        except Exception:
            state['status']='unavailable'  # Never persist provider bodies or tokens.
        state['next_at']=(now+timedelta(hours=1)).isoformat()
        self.store.save_sync_cursor(SyncCursorInput(connector='youtube_creator_public_profiles',account_id=config.account_id,state=state))

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

    def saved_uploads(self, *, creator, day_label="", limit=20):
        from agent.plugins.youtube_browser_history import history_day
        request = CreatorTrackingRead(creator=creator,day_label=day_label,limit=limit)
        config = self._config()
        if not config:
            return SavedCreatorUploads().model_dump()
        names={row["channel_id"]:row["name"] for row in self.store.youtube_tracking_stats(config.account_id)}
        names.update({rule.channel_id:rule.name for rule in config.rules if rule.channel_id})
        names.update({row['channel_id']:row.get('name', row['channel_id'])
                      for row in self.store.youtube_push_subscriptions(config.account_id)})
        def normalized(value):
            return ''.join(character for character in value.casefold() if character.isalnum())
        key=normalized(request.creator)
        matched=[channel for channel,name in names.items() if channel==request.creator or normalized(name)==key]
        if not matched and key:
            matched=[channel for channel,name in names.items() if normalized(name).startswith(key)]
        day=history_day(request.day_label,now=self.clock(),timezone=config.timezone) if request.day_label else ""
        if request.day_label and not day:
            raise ValueError("That upload date is unavailable.")
        start=end=""
        if day:
            boundary=datetime.combine(date.fromisoformat(day),datetime.min.time(),tzinfo=ZoneInfo(config.timezone))
            start,end=boundary.astimezone(UTC).isoformat(),(boundary+timedelta(days=1)).astimezone(UTC).isoformat()
        if len(matched)==1 and not self.store.youtube_tracking_saved_uploads(config.account_id,matched,start=start,end=end,limit=1):
            # Keep channel entities distinct. A clearly labelled saved raw/live
            # variant can answer when the exact name has no records for the day.
            variants=[channel for channel,name in names.items() if normalized(name) in
                      {key+suffix for suffix in ('raw','live','clips','highlights','vods')}]
            with_records=[channel for channel in variants if self.store.youtube_tracking_saved_uploads(config.account_id,[channel],start=start,end=end,limit=1)]
            if with_records:
                matched=with_records
        reply=SavedCreatorUploads(configured=True,matches=[names[channel] for channel in matched],
            ambiguous=len(matched)>1,date=day,timezone=config.timezone)
        if len(matched)!=1:
            return reply.model_dump()
        rows=self.store.youtube_tracking_saved_uploads(config.account_id,matched,start=start,end=end,limit=limit)
        reply.uploads=[{name:str(row[name]) for name in ("channel_id","video_id","title","creator","published_at","status")}
                       | {"url":"https://www.youtube.com/watch?v="+row["video_id"]} for row in rows]
        return reply.model_dump()

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

    def _verified_durations(self, config):
        if not config.min_duration_seconds:
            return {}
        state = (self.store.get_sync_cursor("youtube_upload_durations", config.account_id) or {}).get("state") or {}
        return {video+":"+item.get("channel_id", ""): item["duration_seconds"] for video, item in state.get("videos", {}).items()
                if VIDEO.fullmatch(video) and type(item.get("duration_seconds")) in (int, float)
                and CHANNEL.fullmatch(item.get("channel_id", "")) and 0 < item["duration_seconds"] <= 2678400
                and (_time(item.get("checked_at")) or datetime.min.replace(tzinfo=UTC)) >= self.clock()-timedelta(hours=6)}

    def _check_durations(self, config, active, budget, *, push=False):
        if not config.min_duration_seconds:
            return 0
        now = self.clock()
        topics = {channel: creator["topic_terms"] for channel, creator in active.items()}
        pending = [item for item in self.store.youtube_tracking_uploads(config.account_id, pending=True, topic_filters=topics, limit=10000)
                   if (_time(item["published_at"]) or now) >= now - timedelta(days=2)]
        candidates = {item["video_id"]: item for item in pending}
        # The fast push worker validates pending pings, not the quiet archive.
        # RSS can enrich recent baseline evidence within its slower cadence.
        if not push:
            for item in self.store.youtube_tracking_uploads(config.account_id, topic_filters=topics):
                if (_time(item['published_at']) or now) >= now-timedelta(days=2):
                    candidates.setdefault(item["video_id"], item)
        state = dict((self.store.get_sync_cursor("youtube_upload_durations", config.account_id) or {}).get("state") or {})
        cache = dict(state.get("videos") or {})
        due = [video for video in candidates if video not in cache or
               cache[video].get("channel_id")!=candidates[video]["channel_id"] or
               (cache[video].get('duration_seconds') is not None and
                (_time(cache[video].get("checked_at")) or now)<now-timedelta(hours=6)) or
               (cache[video].get("duration_seconds") is None and (_time(cache[video].get("next_at")) or now) <= now)]
        if budget.get("day") != now.date().isoformat():
            budget.update(day=now.date().isoformat(), requests=0, fallback_units=0, duration_units=0, discovery_units=0)
        times = [stamp for stamp in budget.get("duration_request_times", []) if _time(stamp) and _time(stamp) > now - timedelta(minutes=15)]
        budget["duration_request_times"] = times
        # Push events may validate promptly, coalesced to one batch per ten
        # seconds. Both transports reserve the same persisted daily quota.
        batch_ready = not times or push and all(_time(stamp) <= now-timedelta(seconds=10) for stamp in times)
        if due and batch_ready and not self.authorization_required(config) and budget.get("duration_units", 0) < config.duration_units_per_day and (_time(state.get("provider_next_at")) or now) <= now:
            videos = due[:50]
            # Reserve before I/O, including failed calls and restart retries.
            budget["duration_units"] = budget.get("duration_units", 0) + 1
            budget["duration_request_times"].append(now.isoformat())
            self.store.save_sync_cursor(SyncCursorInput(connector="youtube_creator_feed", account_id=config.account_id+":budget", state=budget))
            try:
                if self.duration_provider is None:
                    from agent.plugins.youtube_runtime import youtube_client
                    provider = youtube_client().video_durations
                else:
                    provider = self.duration_provider
                metadata = provider(videos)
                state.pop("provider_next_at", None)
            except Exception:
                metadata = {}
                state["provider_next_at"] = (now + (timedelta(minutes=5) if push else timedelta(hours=1))).isoformat()
            for video in videos:
                item = metadata.get(video) or {}
                seconds = item.get("duration_seconds")
                valid = (item.get("channel_id") == candidates[video]["channel_id"]
                         and type(seconds) in (int, float) and 0 < seconds <= 2678400)
                misses = 0 if valid else min(int((cache.get(video) or {}).get('misses',0))+1,8)
                retry_seconds = min((120 if push else 1800)*2**max(0,misses-1),3600)
                cache[video] = {"duration_seconds": seconds if valid else None,
                                "channel_id": candidates[video]["channel_id"],
                                "misses":misses,"checked_at": now.isoformat(),
                                "next_at": (now+timedelta(seconds=retry_seconds)).isoformat()}
            cache = {video: item for video, item in cache.items()
                     if (_time(item.get("checked_at")) or now) >= now - timedelta(days=90)}
            state["videos"] = dict(sorted(cache.items(), key=lambda pair: pair[1].get("checked_at", ""))[-1000:])
            self.store.save_sync_cursor(SyncCursorInput(connector="youtube_upload_durations", account_id=config.account_id, state=state))
        durations = self._verified_durations(config)
        # Suppress even manual-refresh results before they reach delivery.
        for item in pending:
            seconds = durations.get(item["video_id"]+":"+item["channel_id"])
            if seconds is not None and seconds <= config.min_duration_seconds:
                self.store.youtube_tracking_ack(config.account_id, item["channel_id"], item["video_id"], "suppressed")
        return sum(item["video_id"]+":"+item["channel_id"] not in durations for item in pending)

    def _deliver_pending(self, config, active, blocked_topics, deliver):
        """Shared push/RSS delivery identity, relevance and duration gate."""
        current = self._config()
        if not current or not current.enabled or current.account_id != config.account_id:
            return 0
        if current != config:
            # Recheck edits made while public metadata was being fetched.
            config = current
            profile = self.snapshot(limit=10000, apply_capacity=False)
            active = {item['channel_id']:item for item in profile['creators'] if item['state'] == 'monitoring' or item.get('rediscovery')}
            blocked_topics = {topic for topic,value in profile['topic_evidence'].items() if value.get('excluded')}
        now = self.clock()
        durations = self._verified_durations(config)
        pacing=dict((self.store.get_sync_cursor('youtube_notification_frequency',config.account_id) or {}).get('state') or {})
        last_ping=dict(pacing.get('channels') or {})
        delivered = 0
        if deliver is None:
            return delivered
        for item in self.store.youtube_tracking_uploads(config.account_id, pending=True, limit=10000):
            creator = active.get(item['channel_id'])
            if not self._upload_relevant(creator, item['title'], blocked_topics) or (_time(item['published_at']) or now) < now-timedelta(days=2):
                self.store.youtube_tracking_ack(config.account_id, item['channel_id'], item['video_id'], 'suppressed')
                continue
            frequency=creator.get('notification_frequency','adaptive')
            if creator.get('rediscovery') and (_time(pacing.get('last_rediscovery_at')) or datetime.min.replace(tzinfo=UTC))>now-timedelta(days=7):
                self.store.youtube_tracking_ack(config.account_id,item['channel_id'],item['video_id'],'baseline')
                continue
            if frequency=='muted' or frequency=='reduced' and (_time(last_ping.get(item['channel_id'])) or datetime.min.replace(tzinfo=UTC))>now-timedelta(hours=24):
                self.store.youtube_tracking_ack(config.account_id,item['channel_id'],item['video_id'],'baseline')
                continue
            if config.min_duration_seconds:
                duration = durations.get(item['video_id']+':'+item['channel_id'])
                if duration is None:
                    continue
                if duration <= config.min_duration_seconds:
                    self.store.youtube_tracking_ack(config.account_id, item['channel_id'], item['video_id'], 'suppressed')
                    continue
            delivery_id = 'youtube-upload-' + sha256((config.account_id+':'+item['channel_id']+':'+item['video_id']).encode()).hexdigest()[:24]
            url = 'https://www.youtube.com/watch?v=' + item['video_id']
            phrasing = ('{name} has a new upload: {title}\n{url}', 'New from {name}: {title}\n{url}', '{name} just uploaded {title}\n{url}')
            text = phrasing[int(sha256(item['video_id'].encode()).hexdigest()[:2], 16) % 3].format(name=_literal(creator['name']), title=_literal(item['title']), url=url)
            if creator.get('rediscovery'):
                text=f"Rediscover {_literal(creator['name'])}: {_literal(item['title'])}\nYou used to watch this creator; no saved watch in at least 90 days.\n{url}"
            deliver(delivery_id, text)
            last_ping[item['channel_id']]=now.isoformat()
            last_ping={channel:stamp for channel,stamp in last_ping.items() if (_time(stamp) or now)>now-timedelta(days=90)}
            pacing['channels']=last_ping
            if creator.get('rediscovery'):
                rediscovered={channel:stamp for channel,stamp in (pacing.get('rediscovered') or {}).items()
                    if (_time(stamp) or now)>now-timedelta(days=90)}
                rediscovered[item['channel_id']]=now.isoformat()
                pacing.update(last_rediscovery_at=now.isoformat(),rediscovered=rediscovered)
            self.store.save_sync_cursor(SyncCursorInput(connector='youtube_notification_frequency',account_id=config.account_id,state=pacing))
            self.store.youtube_tracking_ack(config.account_id, item['channel_id'], item['video_id'])
            delivered += 1
        return delivered

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
            budget_key = config.account_id + ":budget"
            budget = dict((self.store.get_sync_cursor("youtube_creator_feed", budget_key) or {}).get("state") or {})
            if budget.get("day") != now.date().isoformat():
                budget.update(day=now.date().isoformat(), requests=0, fallback_units=0, duration_units=0, discovery_units=0)
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
            self._discover_channel_profiles(config,budget)
            from agent.config import get_settings
            push_base = (get_settings().youtube_push_relay_base or get_settings().youtube_push_callback_base).strip().rstrip('/')
            push_channels = {row['channel_id']: row for row in self.store.youtube_push_subscriptions(config.account_id)
                             if push_base and row.get('desired') and row.get('base') == push_base}
            profile = self.snapshot(limit=10000 if push_channels else 100, apply_capacity=not bool(push_channels))
            creators = profile["creators"]
            blocked_topics={topic for topic,value in profile['topic_evidence'].items() if value.get('excluded')}
            active = {item["channel_id"]: item for item in creators if item["state"] == "monitoring" or item.get('rediscovery')}
            # Push subscriptions also participate in bounded reconciliation,
            # even when their uploads do not currently deserve a ping.
            collection = dict(active)
            for channel, row in push_channels.items():
                rule = self._rule(channel, row.get('name', ''), config)
                if not rule or rule.relationship not in {'excluded', 'former'}:
                    collection.setdefault(channel, {'name':row.get('name',channel), 'topic_terms':[]})
            states = {channel: dict((self.store.get_sync_cursor("youtube_creator_feed", config.account_id+":"+channel) or {}).get("state") or {}) for channel in collection}
            due = sorted(collection, key=lambda channel: states[channel].get("next_at", ""))
            requests_made = 0
            warnings = []
            fallback_checks = 0
            for channel in due:
                state = states[channel]
                request_now = self.clock()
                if budget.get("day") != request_now.date().isoformat():
                    budget.update(day=request_now.date().isoformat(), requests=0, fallback_units=0, duration_units=0, discovery_units=0)
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
                    warnings.append(collection[channel]["name"] + ": " + result["error"])
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
                    relevant = self._upload_relevant(active.get(channel),item['title'],blocked_topics)
                    eligible = published and now - timedelta(days=2) <= published <= now and relevant
                    entries.append(item | {"status": "baseline" if channel not in active or baseline and relevant else "pending" if not baseline and eligible else "suppressed"})
                state.update(initialized=True, failures=0, error="", last_success=now.isoformat(), next_at=(now+timedelta(minutes=30)).isoformat())
                for key in ("etag", "last_modified"):
                    if key in result:
                        state[key] = result[key]
                if result.get("uploads_playlist"):
                    state["uploads_playlist"] = result["uploads_playlist"]
                state["transport"] = result.get("transport", "youtube_atom")
                self.store.youtube_tracking_save_feed(config.account_id, channel, entries, state, now.isoformat())
            pending_duration = self._check_durations(config, active, budget)
            durations = self._verified_durations(config)
            if pending_duration:
                warnings.append(f"Duration is unverified for {pending_duration} recent uploads; notifications remain queued.")
            duration_state = (self.store.get_sync_cursor('youtube_upload_durations', config.account_id) or {}).get('state') or {}
            if config.min_duration_seconds and (_time(duration_state.get('provider_next_at')) or now) > now:
                warnings.append("Public upload duration metadata is unavailable; new notifications require verified video length.")
            discovery_state = (self.store.get_sync_cursor('youtube_creator_public_profiles', config.account_id) or {}).get('state') or {}
            if config.related_discovery and discovery_state.get('status') == 'unavailable':
                warnings.append("Public channel topic metadata is unavailable; related selection is limited to saved title evidence.")
            delivered = self._deliver_pending(config, active, blocked_topics, deliver)
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
                       "monitored_channels": len(active), "baselined_channels": baselined,
                       "pending_duration_checks": pending_duration}))
            return {"status": status, "requests": requests_made, "fallback_checks": fallback_checks, "delivered": delivered, "projection": projection}
        finally:
            self.store.youtube_tracking_unlock(config.account_id, owner)
