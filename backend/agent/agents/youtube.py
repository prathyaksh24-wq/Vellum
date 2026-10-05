from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import quote

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from agent.tools.registry import ToolRegistry


class YoutubeAgent:
    name = "YoutubeAgent"

    _INTENT_PATTERNS = (
        re.compile(r"(?<!\w)(?:youtube|yt)(?!\w)", re.I),
        re.compile(r"\bwhat\s+did\s+.+\s+upload(?:ed)?\b", re.I),
        re.compile(r"\b(?:latest|new|recent)\s+.+\s+video\b", re.I),
        re.compile(r"\b(?:video|upload|uploaded|transcript)\s+(?:from|by|of)\s+.+", re.I),
    )
    _VIDEO_INTENT_PATTERNS = (
        r"(?<!\w)what\s+did\s+.+\s+upload(?:ed)?(?!\w)",
        r"(?<!\w).+\s+latest\s+upload(?:s)?(?!\w)",
        r"(?<!\w).+\s+latest\s+video(?:s)?(?!\w)",
        r"(?<!\w).+\s+new\s+video(?:s)?(?!\w)",
    )
    _META_FEEDBACK_PATTERNS = (
        r"\b(previous|last|earlier)\s+(response|answer|reply)\b",
        r"\b(i\s+don'?t\s+need|don'?t\s+add|stop\s+adding|remove|hide)\s+.+\b(evidence|source|sources|format|section)\b",
        r"\b(i\s+don'?t\s+like|i\s+like|prefer|feedback)\b.+\b(answer|response|format|evidence|source|sources)\b",
    )
    _SUBSCRIPTION_PATTERNS = (
        r"\b(?:my|our)\s+(?:youtube\s+)?subscriptions?\b",
        r"\b(?:how\s+many|number\s+of|count)\b.*\b(?:channels?|subscriptions?|subscribes?)\b.*\b(?:i|we|my|our)\b",
        r"\bchannels?\s+(?:i|we)\s+(?:have\s+|am\s+|are\s+)?subscribed\s+to\b",
        r"\b(?:which|what|who)\s+.+\bsubscribed\s+to\b",
        r"\bchannels?\s+(?:am|are)\s+.+\bsubscribed\s+to\b",
        r"\bsubscriptions?\s+(?:on|from)\s+youtube\b",
    )
    _ACCOUNT_PATTERNS = (
        r"\b(?:do|does)\s+(?:you|vellum)\s+have\s+access\s+to\s+(?:my|our)\s+youtube\s+(?:data|account|history)\b",
        r"\b(?:can|could)\s+(?:you|vellum)\s+(?:read|access|see)\s+(?:my|our)\s+youtube\s+data\b",
        r"\b(?:are|is)\s+(?:you|vellum)\s+connected\s+to\s+youtube\b",
        r"\byoutube\s+(?:connection|account|oauth)\s+(?:status|connected)\b",
        r"\b(?:my|our)\s+youtube\s+(?:account|channel)\b",
        r"\bcan\s+you\s+see\s+(?:my|our)\s+(?:youtube\s+)?channel\b",
    )
    _LIKED_PATTERNS = (
        r"\b(?:my|our)\s+(?:(?:latest|recent|recently|youtube|yt)\s+){0,3}liked\s+(?:(?:youtube|yt)\s+)?(?:videos?|vidoes?)\b",
        r"\b(?:videos?|vidoes?)\s+(?:that\s+)?(?:i|we)\s+(?:have\s+)?liked\b",
        r"\b(?:videos?|vidoes?)\s+(?:have|did)\s+(?:i|we)\s+(?:like|liked)\b",
    )
    _TAKEOUT_PATTERNS = (
        r"\b(?:videos?|what|which)\b.*\b(?:i|we)\s+(?:have\s+)?(?:watched|seen)\b",
        r"\bwhat\s+(?:did|have)\s+(?:i|we)\s+(?:watch|watched|search|searched)(?:\s+(?:recently|lately|last))?\b",
        r"\b(?:my|our)\s+(?:recent\s+)?(?:watch|search|viewing)\s+history\b",
        r"\byoutube\s+takeout\b",
        r"\b(?:my|our)\s+youtube\s+(?:watch|search)\s+history\b",
        r"\bwhat\s+did\s+(?:i|we)\s+recently\s+watch\b",
    )
    _SUBSCRIPTION_FEED_PATTERNS = (
        r"\b(?:latest|new|recent)\s+videos?\s+from\s+channels?\s+(?:i|we)\s+(?:am\s+|are\s+)?subscrib(?:e|ed)\s+to\b",
        r"\b(?:my|our)\s+youtube\s+subscriptions?\s+feed\b",
        r"\bwhat(?:'s|\s+is)\s+new\s+in\s+(?:my|our)\s+youtube\s+subscriptions?\b",
    )
    _INTELLIGENCE_PATTERNS = (
        r"\b(?:my|our)\s+(?:youtube|yt)\s+(?:data|activity|profile)\b",
        r"\bwhat\s+(?:have\s+)?(?:you|u|vellum)\s+(?:learned|learnt|know)\b.*\b(?:my|our)\s+(?:youtube|yt)\b",
        r"\b(?:my|our)\s+(?:youtube\s+)?(?:interests?|taste|habits|patterns)\b",
        r"\binterest\s+in\s+.+\s+(?:changed|change|declining|falling|waning|rising)\b",
        r"\bwhich\s+(?:youtube\s+)?channels?\s+.+\b(?:losing|gaining)\s+interest\b",
        r"\bwhat\s+.+\brepeatedly\s+search\b",
    )

    def __init__(
        self,
        vault_root: Path,
        youtube_service: YoutubeCapabilityService | None = None,
        tool_registry: ToolRegistry | None = None,
        synthesizer=None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.tool_registry = tool_registry
        self.synthesizer = synthesizer
        self.youtube_service = youtube_service or (
            None if tool_registry is not None else YoutubeCapabilityService(vault_root=self.vault_root)
        )

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        if self._is_meta_feedback(lowered):
            return False
        return (
            self._is_intelligence_query(lowered)
            or self._is_account_query(lowered)
            or self._is_liked_query(lowered)
            or self._is_subscriptions_query(lowered)
            or self._is_takeout_query(lowered)
            or any(pattern.search(query) for pattern in self._INTENT_PATTERNS)
            or any(re.search(pattern, lowered) is not None for pattern in self._VIDEO_INTENT_PATTERNS)
        )

    def answer_with_context(self, query: str, context: dict) -> SpecialistResponse:
        previous = str(context.get("query") or "")
        if time.time() - float(context.get("at") or 0) <= 1800:
            if re.fullmatch(r"(?:please\s+)?(?:give me a summary|summari[sz]e(?:\s+(?:it|that|my data))?|explain (?:it|that))\??", query.strip(), re.I) and self._is_intelligence_query(previous.lower()):
                query = previous
            elif re.search(r"\b(?:watched|seen)\b.*\b(?:him|her|them)\b", query, re.I):
                creator = re.search(r"\b(?:from|by)\s+(.+?)(?:[?.!]|$)", previous, re.I)
                if creator:
                    query = "what videos have I watched from " + creator[1]
        response = self.answer(query)
        return response.model_copy(update={"structured_payload":{**response.structured_payload,"youtube_query":query}})

    @staticmethod
    def thread_context(response: SpecialistResponse, previous: dict) -> dict:
        query = response.structured_payload.get("youtube_query")
        return {"query":query, "at":time.time()} if query else previous

    def answer(self, query: str) -> SpecialistResponse:
        lowered = query.lower()
        if re.search(r"\b(?:my|our)\b.*\b(?:youtube music|music library|watch later|playlists)\b", lowered):
            return self._answer_takeout_library(lowered)
        if self._is_account_query(lowered):
            return self._answer_account()
        if self._is_intelligence_query(lowered):
            return self._answer_personal_context(query)
        if self._is_liked_query(lowered):
            return self._answer_liked_videos()
        if self._is_takeout_query(lowered):
            return self._answer_takeout_history(lowered)
        if self._is_subscription_feed_query(lowered):
            return self._answer_subscription_feed()
        if self._is_subscriptions_query(lowered):
            return self._answer_subscriptions(lowered)
        if self._is_account_query(lowered):
            return self._answer_account()
        try:
            result = self._search_videos({"query": query, "max_results": 5})
        except Exception as exc:
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary="YoutubeAgent could not fetch YouTube results right now.",
                analysis=f"YouTube search failed: {self._sanitize_error(exc)}",
                confidence=0.2,
            )
        items = result.get("items") or []
        providers = {str(provider).strip().lower() for provider in (result.get("providers") or []) if str(provider).strip()}
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="YoutubeAgent did not find matching YouTube videos.",
                analysis="Used youtube.search_videos through YoutubeCapabilityService; no videos matched the query.",
                confidence=0.35,
            )

        lines = [f"YoutubeAgent found {min(len(items), 5)} relevant YouTube result(s):"]
        sources: list[SpecialistSource] = []
        used_transcript = False
        for index, item in enumerate(items[:5], start=1):
            title = str(item.get("title") or "Untitled YouTube video").strip()
            channel = str(item.get("channel") or "").strip()
            description = str(item.get("description") or "").strip()
            transcript = str(item.get("transcript") or "").strip()
            detail = transcript or description
            used_transcript = used_transcript or bool(transcript)
            label = f"[{index}] {title}"
            if channel:
                label += f" by {channel}"
            if detail:
                label += f": {detail[:240]}"
            lines.append(label)
            url = str(item.get("url") or "").strip()
            if url and self._is_youtube_url(url):
                sources.append(
                    SpecialistSource(
                        kind="web",
                        title=title,
                        path_or_url=url,
                        snippet=detail[:500],
                        captured_at=str(item.get("published_at") or ""),
                        freshness="recent",
                    )
                )

        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis=(
                "Used youtube.search_videos through YoutubeCapabilityService"
                + (" via SerpAPI" if "serpapi" in providers else "")
                + (" with transcript snippets." if used_transcript else ".")
            ),
            sources=sources,
            confidence=0.72 if sources else 0.55,
        )

    def _search_videos(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.search_videos", payload, agent_name=self.name)
        return self.youtube_service.search_videos(payload)

    def _account(self) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.account", {}, agent_name=self.name)
        return self.youtube_service.account({})

    def _subscriptions(self) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.subscriptions", {}, agent_name=self.name)
        return self.youtube_service.subscriptions({})

    def _liked_videos(self) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.liked_videos", {"max_results": 20}, agent_name=self.name)
        return self.youtube_service.liked_videos({"max_results": 20})

    def _takeout_history(self, kind: str, channel: str = "") -> dict:
        payload = {"kind": kind, "limit": 20}
        if channel:
            payload["channel"] = channel
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.takeout_history", payload, agent_name=self.name)
        return self.youtube_service.takeout_history(payload)

    def _subscription_feed(self) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.subscription_feed", {}, agent_name=self.name)
        return self.youtube_service.subscription_feed({})

    def _personal_context(self, query: str) -> dict:
        payload = {"query": query, "limit": 50}
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.personal_context", payload, agent_name=self.name)
        return self.youtube_service.personal_context(payload)

    def _answer_account(self) -> SpecialistResponse:
        try:
            result = self._account()
        except Exception as exc:
            return self._official_error("YoutubeAgent could not read the connected YouTube account.", exc)
        account = result.get("account") or {}
        if not account.get("configured"):
            summary = "YouTube OAuth is not configured in Vellum."
            status = "needs_fetch"
            confidence = 0.95
        elif not account.get("connected"):
            summary = "Vellum is not connected to a YouTube account."
            status = "needs_fetch"
            confidence = 0.95
        else:
            channel = str(account.get("channel_title") or "").strip()
            summary = f"Vellum is connected to YouTube as {channel}." if channel else "Vellum is connected to YouTube."
            status = "answered"
            confidence = 1.0
        if account.get("takeout_available"):
            summary = f"I can read your imported YouTube history locally ({int(account.get('takeout_watch_count') or 0):,} watch records). " + (
                "Live YouTube OAuth is connected." if account.get("connected") else "Live YouTube OAuth is not connected; the import is a snapshot.")
            status = "answered"
        return SpecialistResponse(
            agent=self.name,
            status=status,
            summary=summary,
            analysis="Used youtube.account through the official OAuth connector.",
            confidence=confidence,
        )

    def _answer_subscriptions(self, query: str = "") -> SpecialistResponse:
        try:
            result = self._subscriptions()
        except Exception as exc:
            return self._official_error("YoutubeAgent could not read YouTube subscriptions.", exc)
        if not result.get("connected") and not result.get("available"):
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="Vellum is not connected to a YouTube account.",
                analysis="Used youtube.subscriptions through the official OAuth connector.",
                confidence=0.95,
            )
        items = list(result.get("items") or [])
        total = int(result.get("total", len(items)))
        snapshot = result.get("provider") == "takeout"
        intro = (f"Your imported YouTube snapshot lists {total:,} subscribed channels."
            if snapshot else f"You're subscribed to {total:,} YouTube channels.")
        if re.search(r"\b(?:how\s+many|number\s+of|count)\b", query):
            summary = intro
        elif not items:
            summary = intro
        else:
            visible = items[:50]
            lines = [f"{index}. {self._account_item_label(item, 'channel_id', 'channel')}"
                for index, item in enumerate(visible, start=1)]
            if total > len(visible):
                intro += f" Showing the first {len(visible)}."
            summary = intro + "\n\n" + "\n".join(lines)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis=("Used youtube.subscriptions from the imported Takeout snapshot." if snapshot
                else "Used youtube.subscriptions through the official OAuth connector."),
            confidence=1.0,
        )

    def _answer_liked_videos(self) -> SpecialistResponse:
        try:
            result = self._liked_videos()
        except Exception as exc:
            return self._official_error("YoutubeAgent could not read liked YouTube videos.", exc)
        if not result.get("connected"):
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="Vellum is not connected to a YouTube account.",
                analysis="Used youtube.liked_videos through the official OAuth connector.",
                confidence=0.95,
            )
        items = list(result.get("items") or [])
        if not items:
            summary = "The connected YouTube account has no accessible liked videos."
        else:
            lines = []
            for index, item in enumerate(items, start=1):
                title = self._account_item_label(item, "video_id", "video")
                channel = self._markdown_label(str(item.get("channel") or ""))
                lines.append(f"{index}. {title}" + (f" — {channel}" if channel else ""))
            summary = f"Here are your {len(items)} most recent liked videos:\n\n" + "\n".join(lines)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Used youtube.liked_videos through the official OAuth connector.",
            confidence=1.0,
        )

    def _answer_takeout_history(self, lowered_query: str) -> SpecialistResponse:
        kind = "search" if "search" in lowered_query else "watch"
        match = re.search(r"\b(?:from|by)\s+(.+?)(?:[?.!]|$)", lowered_query)
        requested_channel = match[1].strip() if match else ""
        try:
            result = self._takeout_history(kind, requested_channel)
        except Exception as exc:
            return self._official_error("YoutubeAgent could not read local YouTube Takeout history.", exc)
        if not result.get("available"):
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="No imported YouTube Takeout history is available yet.",
                analysis="Used youtube.takeout_history from the local Knowledge Core.",
                confidence=1.0,
            )
        items = list(result.get("items") or [])
        label = "searches" if kind == "search" else "watched videos"
        lines = []
        for index, item in enumerate(items[:5], start=1):
            title = str(item.get("query") or item.get("title") or item.get("video_id") or "Unknown item")
            channel = str(item.get("channel_title") or "")
            occurred_at = str(item.get("occurred_at") or "")
            url = str(item.get("url") or item.get("video_url") or "")
            if not url and item.get("video_id"):
                url = f"https://www.youtube.com/watch?v={item['video_id']}"
            line = "- " + (f"[{title}]({url})" if self._is_youtube_url(url) else title) + (f" — {channel}" if channel else "")
            if occurred_at:
                line += f" (watched {occurred_at[:10]})"
            lines.append(line)
        total = int(result.get('total') or 0)
        summary = (f"Your imported history contains {total:,} recorded {'watches from ' + requested_channel if requested_channel else label}. Here are the most recent:\n\n" + "\n".join(lines)) if lines else f"I found no recorded watches{' from ' + requested_channel if requested_channel else ''} in your imported history. This snapshot may not include newer activity."
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Used youtube.takeout_history from the local Knowledge Core.",
            confidence=1.0,
        )

    def _answer_takeout_library(self, query: str) -> SpecialistResponse:
        kind = "music" if "music" in query else "watch_later" if "watch later" in query else "playlists"
        payload = {"kind": kind, "limit": 10}
        try:
            result = (self.tool_registry.invoke("youtube.takeout_library", payload, agent_name=self.name)
                if self.tool_registry is not None else self.youtube_service.takeout_library(payload))
        except Exception as exc:
            return self._official_error("I could not read your imported YouTube library.", exc)
        lines = []
        for item in result.get("items", []):
            artists = ", ".join(item.get("artists") or [])
            lines.append("- " + str(item.get("title") or item.get("video_id") or "Unknown item") + (f" — {artists}" if artists else ""))
        summary = (f"Your Takeout snapshot contains {result.get('total', 0)} {kind.replace('_', ' ')} items.\n" + "\n".join(lines)
            if result.get("available") else "There are no imported items for that YouTube library yet.")
        return SpecialistResponse(agent=self.name, status="answered" if result.get("available") else "needs_fetch", summary=summary,
            analysis="Used local YouTube Takeout library metadata; no live account access or public search.", confidence=1.0)

    def _answer_subscription_feed(self) -> SpecialistResponse:
        self._subscription_feed()
        return SpecialistResponse(
            agent=self.name,
            status="needs_fetch",
            summary=(
                "The official YouTube API does not expose the personalized subscriptions feed. "
                "Vellum can retrieve a specific subscribed channel's latest public videos, but a complete personal feed "
                "requires scheduled per-channel upload polling."
            ),
            analysis="Used youtube.subscription_feed; no public-search substitute was used.",
            confidence=1.0,
        )

    def _answer_personal_context(self, query: str) -> SpecialistResponse:
        try:
            result = self._personal_context(query)
        except Exception as exc:
            return self._official_error("YoutubeAgent could not read local YouTube interests.", exc)
        if not result.get("local_only"):
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="YouTube personal context was withheld.",
                analysis="youtube.personal_context did not return a local-only result.",
                confidence=1.0,
            )

        channels = list(result.get("channels") or [])
        themes = list(result.get("search_themes") or [])

        if (channels or themes) and re.search(r"\b(?:discover|recommend|suggest)\b", query, re.I):
            ideas = []
            for item in channels[:3]:
                ideas.append(f"- Explore more from {item.get('label') or 'a recently watched channel'} — {int(item.get('evidence_count') or 0)} recorded watches.")
            for item in themes:
                if len(ideas) >= 3:
                    break
                ideas.append(f"- Explore {item.get('label') or 'a repeated search topic'} — {int(item.get('evidence_count') or 0)} recorded searches.")
            return SpecialistResponse(agent=self.name, status="answered", summary="From your imported YouTube snapshot, here are three starting points:\n" + "\n".join(ideas) + "\n\nThese suggestions reflect your recorded viewing and search history.", analysis="Used local YouTube interest evidence for discovery directions; no live recommendation feed was queried.", confidence=0.8)
        lines = []
        frequent = sorted(channels, key=lambda c:int(c.get('evidence_count') or 0), reverse=True)[:5]
        if frequent:
            lines.append("Among the channels in this snapshot, you return most often to " + ", ".join(
                f"{c.get('label') or 'an unnamed channel'} ({int(c.get('evidence_count') or 0):,} recorded watches)" for c in frequent) + ".")
        rising = [str(c.get('label')) for c in channels if c.get('trend') == 'rising' and float(c.get('confidence') or 0) >= .5][:3]
        falling = [str(c.get('label')) for c in channels if c.get('trend') == 'falling' and float(c.get('confidence') or 0) >= .5][:3]
        if rising:
            lines.append("Your recorded viewing has increased for " + ", ".join(rising) + ".")
        if falling:
            lines.append("You have watched less from " + ", ".join(falling) + " recently compared with the earlier part of the import.")
        if themes:
            lines.append("Repeated searches include " + ", ".join(str(t.get('label') or '') for t in themes[:3]) + ".")
        if lines:
            dates = [str(c.get('latest_observation_at') or '')[:10] for c in channels if c.get('latest_observation_at')]
            lines.append("This describes recorded activity" + (" through " + max(dates) if dates else " in your import") + "; it does not prove your motivations or show live activity.")
        if not lines:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="No matching YouTube interest evidence is available yet.",
                analysis="Used youtube.personal_context from the local Knowledge Core.",
                confidence=1.0,
            )
        confidence = max(
            [float(item.get("confidence") or 0) for item in channels[:20] + themes[:20]],
            default=0.0,
        )
        summary = "From your imported YouTube snapshot:\n\n" + "\n\n".join(lines)
        if self.synthesizer is not None:
            try:
                natural = str(self.synthesizer(query, result)).strip()
                if natural:
                    summary = natural + "\n\nThis reflects your imported watch and search history" + (" through " + max(dates) if dates else "") + "."
            except Exception:
                # Retain readable grounded facts when inference is unavailable.
                pass
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Used youtube.personal_context from the local Knowledge Core.",
            confidence=confidence,
        )

    def _is_subscriptions_query(self, lowered_query: str) -> bool:
        lowered_query = re.sub(r"\bsubscried\b", "subscribed", lowered_query)
        return any(re.search(pattern, lowered_query) is not None for pattern in self._SUBSCRIPTION_PATTERNS)

    @staticmethod
    def _markdown_label(value: str) -> str:
        return re.sub(r"([\\\[\]*_`])", r"\\\1", " ".join(value.split()))

    @classmethod
    def _account_item_label(cls, item: dict, id_key: str, kind: str) -> str:
        identifier = str(item.get(id_key) or "")
        title = cls._markdown_label(str(item.get("title") or identifier or f"Unknown {kind}"))
        if not identifier:
            return title
        target = ("https://www.youtube.com/watch?v=" if kind == "video"
            else "https://www.youtube.com/channel/") + quote(identifier, safe="")
        return f"[{title}]({target})"

    def _is_account_query(self, lowered_query: str) -> bool:
        return any(re.search(pattern, lowered_query) is not None for pattern in self._ACCOUNT_PATTERNS)

    def _is_liked_query(self, lowered_query: str) -> bool:
        return any(re.search(pattern, lowered_query) is not None for pattern in self._LIKED_PATTERNS)

    def _is_takeout_query(self, lowered_query: str) -> bool:
        return any(re.search(pattern, lowered_query) is not None for pattern in self._TAKEOUT_PATTERNS)

    def _is_intelligence_query(self, lowered_query: str) -> bool:
        return any(re.search(pattern, lowered_query) is not None for pattern in self._INTELLIGENCE_PATTERNS)

    def _is_subscription_feed_query(self, lowered_query: str) -> bool:
        return any(re.search(pattern, lowered_query) is not None for pattern in self._SUBSCRIPTION_FEED_PATTERNS)

    def _official_error(self, summary: str, exc: Exception) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="error",
            summary=summary,
            analysis=f"Official YouTube connector failed: {self._sanitize_error(exc)}",
            confidence=0.2,
        )

    def _is_youtube_url(self, url: str) -> bool:
        return "youtube.com/watch" in url or "youtu.be/" in url

    def _is_meta_feedback(self, lowered_query: str) -> bool:
        return any(re.search(pattern, lowered_query) is not None for pattern in self._META_FEEDBACK_PATTERNS)

    def _sanitize_error(self, exc: Exception) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ").strip()
        if not message:
            message = exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"[:160]
