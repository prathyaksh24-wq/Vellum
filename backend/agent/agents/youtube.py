from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import quote

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.contracts.youtube_requests import YoutubeReadRequest, clear_read_request
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
        r"\bwatch\s+history\b",
        r"\brefresh\s+(?:my\s+|youtube\s+)?history\b",
        r"\b(?:videos?|what|which)\b.*\b(?:i|we)\s+(?:have\s+)?(?:watched|seen)\b",
        r"\bwhat\s+(?:did|have)\s+(?:i|we)\s+(?:watch|watched|search|searched)(?:\s+(?:recently|lately|last))?\b",
        r"\b(?:my|our)\s+(?:recent\s+)?(?:watch|search|viewing)\s+history\b",
        r"\byoutube\s+takeout\b",
        r"\b(?:my|our)\s+youtube\s+(?:watch|search)\s+history\b",
        r"\bwhat\s+did\s+(?:i|we)\s+recently\s+watch\b",
    )
    _SUBSCRIPTION_FEED_PATTERNS = (
        r"\b(?:which|what)\s+(?:youtube\s+)?(?:creators?|channels?)\b.*\b(?:tracking|monitoring|following)\b",
        r"\b(?:my|our)\s+(?:youtube\s+)?creator\s+(?:tracking|uploads)\b",
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
        planner=None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.tool_registry = tool_registry
        self.synthesizer = synthesizer
        self.planner = planner
        self.youtube_service = youtube_service or (
            None if tool_registry is not None else YoutubeCapabilityService(vault_root=self.vault_root)
        )

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        if self._is_meta_feedback(lowered):
            return False
        return (
            self._is_intelligence_query(lowered)
            or self._is_subscription_feed_query(lowered)
            or clear_read_request(query) is not None
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
        if time.time() - float(context.get("at") or 0) > 1800:
            context = {}
        response = self.answer(query, context=context)
        return response.model_copy(update={"structured_payload":{**response.structured_payload,"youtube_query":query}})

    @staticmethod
    def thread_context(response: SpecialistResponse, previous: dict) -> dict:
        query = response.structured_payload.get("youtube_query")
        if not query:
            return previous
        account = response.structured_payload.get("youtube_account")
        if account is not None:
            return {"query":query, "at":time.time(), "account_request":account["request"],
                "account_items":account["items"]}
        return {"query":query, "at":time.time()}

    def answer(self, query: str, *, context: dict | None = None) -> SpecialistResponse:
        lowered = query.lower()
        if re.search(r"\b(?:my|our)\b.*\b(?:youtube music|music library|watch later|playlists)\b", lowered):
            return self._answer_takeout_library(lowered)
        if self._is_takeout_query(lowered):
            if not re.search(r"\b(?:takeout|imported|archive)\b|\bsearch history\b|\b(?:did|have)\s+(?:i|we)\s+(?:search|searched)\b", lowered):
                return self._answer_browser_history(query, context or {})
            return self._answer_takeout_history(lowered)
        if self._is_account_query(lowered):
            return self._answer_account()
        if self._is_intelligence_query(lowered):
            return self._answer_personal_context(query)
        if self._is_subscription_feed_query(lowered):
            return self._answer_subscription_feed()
        read_request = clear_read_request(query)
        if read_request is not None and read_request.source == "previous":
            return self._answer_read_request(read_request, context or {})
        if self.planner is not None:
            try:
                planned = self.planner(query, context or {})
                planned = planned if isinstance(planned, YoutubeReadRequest) else YoutubeReadRequest.model_validate(planned)
            except Exception as exc:
                return SpecialistResponse(agent=self.name, status="error",
                    summary="I couldn't reliably interpret this YouTube request. " +
                        ("Select a local model and try again." if isinstance(exc, ValueError) and "local model" in str(exc)
                         else "The local request interpreter timed out. Try again when the local model is ready." if isinstance(exc, TimeoutError)
                         else "The local request interpreter failed. Please rephrase or try again."),
                    analysis="YouTube request interpretation failed: " + type(exc).__name__, confidence=1.0)
            if planned.source == "public" and read_request is not None:
                planned = YoutubeReadRequest(source="clarify", view="clarify")
            if planned.source == "previous" and read_request is not None and read_request.source == "previous":
                planned = planned.model_copy(update={"reference_kind":read_request.reference_kind, "index":read_request.index})
            read_request = planned
        if read_request is not None and read_request.source != "public":
            return self._answer_read_request(read_request, context or {})
        if self._is_liked_query(lowered):
            return self._answer_liked_videos()
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

    def _liked_videos(self, limit: int = 20) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.liked_videos", {"max_results": limit}, agent_name=self.name)
        return self.youtube_service.liked_videos({"max_results": limit})

    def _answer_read_request(self, request: YoutubeReadRequest, context: dict) -> SpecialistResponse:
        def reply(summary, items=(), *, status="answered", analysis="Read verified YouTube account records."):
            return SpecialistResponse(agent=self.name, status=status, summary=summary, analysis=analysis, confidence=1.0,
                structured_payload={"youtube_account":{"request":request.model_dump(), "items":list(items)[:100]}})

        if request.source == "clarify" or request.view == "clarify":
            return reply("I couldn't determine a supported YouTube read for that request. "
                "Tell me whether you want videos, channel names, a count, or a link to an item I showed you.", status="needs_fetch")
        if request.source == "previous":
            items = list(context.get("account_items") or [])
            previous = context.get("account_request") or {}
            if not items:
                return reply("I don't have the displayed video or channel list in this chat. "
                    "Ask me to list it again, then I can link the item you choose.", status="needs_fetch")
            if request.index is None or request.index > len(items):
                return reply(f"The previous list has {len(items)} items, so I can't link item {request.index}. "
                    "Choose an item from that list.", items, status="needs_fetch")
            item = items[request.index - 1]
            if request.reference_kind == "video" and "video_id" not in item:
                return reply("The previous list contains channels. I need a displayed video list to link that video.",
                    items, status="needs_fetch")
            if request.reference_kind == "channel" and "video_id" in item:
                return reply("The previous list contains videos. Ask for channels from those videos first.",
                    items, status="needs_fetch")
            id_key = "video_id" if previous.get("view") == "videos" or "video_id" in item else "channel_id"
            if not item.get(id_key):
                return reply("That item has no verified YouTube link in the saved list.", items, status="needs_fetch")
            # Keep the complete displayed order for another ordinal follow-up.
            response = reply(self._account_item_label(item, id_key, "video" if id_key == "video_id" else "channel"), items)
            response.structured_payload["youtube_account"]["request"] = previous
            return response
        try:
            if request.source == 'history':
                payload = {'limit':100, 'channel':request.creator, 'day_label':request.day_label}
                result = self.tool_registry.invoke('youtube.watch_history', payload, agent_name=self.name) \
                    if self.tool_registry is not None else self.youtube_service.watch_history(payload)
            else:
                result = self._liked_videos(50 if request.view in {"channels", "count", "summary"} or request.creator else request.limit) \
                    if request.source == "liked" else self._subscriptions()
        except Exception as exc:
            if request.source == 'history':
                from agent.plugins.youtube_browser_history import HistoryReadError
                return SpecialistResponse(agent=self.name, status='needs_fetch', confidence=1,
                    summary=str(exc) if isinstance(exc, HistoryReadError) else
                        'I could not read watch history from Vellum’s Browser. Check the browser and try again.',
                    analysis='Browser history read failed: ' + type(exc).__name__)
            detail = str(exc).casefold()
            reason = ("YouTube's API quota is temporarily exhausted." if "quota" in detail else
                "YouTube authorization is invalid or lacks the required read permission." if any(
                    word in detail for word in ("auth", "permission", "token")) else
                "The YouTube API could not be reached." if any(word in detail for word in ("unreachable", "timeout", "network"))
                else "The YouTube account read failed.")
            return SpecialistResponse(agent=self.name, status="error",
                summary="I couldn't read your " + ("liked videos" if request.source == "liked" else "subscriptions") + ". " + reason,
                analysis="YouTube account read failed: " + type(exc).__name__, confidence=1.0)
        if not result.get("connected") and not result.get("available"):
            return reply("Vellum isn't connected to a YouTube account, so I can't read that list.", status="needs_fetch")
        items = list(result.get("items") or [])
        inspected = len(items)
        snapshot = result.get("provider") == "takeout"
        if request.creator:
            items = [item for item in items if request.creator.casefold() in str(
                item.get("channel") if request.source in {"liked", "history"} else item.get("title") or "").casefold()]
        if request.source in {"liked", "history"} and (request.view == "channels" or request.view == "count" and request.count_kind == "channels"):
            channels = {}
            for item in items:
                name = str(item.get("channel") or "").strip()
                identity = str(item.get("channel_id") or "").strip() or name.casefold()
                if name and identity not in channels:
                    channels[identity] = {"title":name, "channel_id":item.get("channel_id") or ""}
            items = list(channels.values())
        if request.view == "count":
            if request.source == "subscriptions":
                total = len(items) if request.creator else int(result.get("total", len(items)))
                return reply(f"Your imported YouTube snapshot lists {total:,} subscribed channels." if snapshot else
                    f"You're subscribed to {total:,} YouTube channels.")
            if request.count_kind == "channels":
                return reply(f"I found {len(items)} distinct channels in the {inspected} recent {'browser history entries' if request.source == 'history' else 'liked videos'} I read.")
            if request.source == 'history':
                return reply(f"I found {len(items)} entries in the recent browser history snapshot. This is not an all-time watch count.")
            return reply(f"I read {len(items)} recent liked videos. This is a bounded recent sample; "
                "the connector hasn't supplied your full liked-video total.")
        if request.view == "summary":
            names = list(dict.fromkeys(str(item.get("channel") or item.get("title") or "") for item in items))
            if request.source == 'history':
                return reply(f"The current browser snapshot contains {len(items)} recent watch-history entries. " +
                    ("Channels include " + ", ".join(names[:5]) + ". " if names else "") +
                    "This was refreshed just now; a recent page snapshot does not establish long-term viewing trends.")
            return reply(f"This {'imported snapshot' if snapshot else 'account read'} contains {len(items)} "
                f"{'recent liked videos' if request.source == 'liked' else 'subscribed channels'}. "
                + ("Channels include " + ", ".join(names[:5]) + "." if names else "No channel names were available."))
        visible = items[:request.limit]
        if request.source == 'history':
            suffix = '\n\nRefreshed from your browser just now. Coverage is the recent history page, not your full watch history.'
            if not visible:
                return reply(('No matching entries were visible in this browser history refresh.' if request.creator or request.day_label else
                    'The signed-in YouTube account has no visible watch-history entries in this refresh.') + suffix)
            label = 'channels' if request.view == 'channels' else 'entries'
            intro = f"Here are {len(visible)} recent {label} from the YouTube account signed into Vellum’s Browser:"
            lines = []
            for index, item in enumerate(visible, 1):
                key = 'channel_id' if request.view == 'channels' else 'video_id'
                title = self._markdown_label(str(item.get('title') or 'Unknown')) if request.names_only else \
                    self._account_item_label(item, key, 'channel' if key == 'channel_id' else 'video')
                if not request.names_only and item.get('day_label'):
                    title += ' (' + self._markdown_label(item['day_label']) + ')'
                lines.append(f'{index}. {title}')
            return reply(intro + '\n\n' + '\n'.join(lines) + suffix, visible,
                analysis='Used youtube.watch_history from the current browser account; saved locally in Knowledge Core.')
        if not visible:
            return reply("I found no " + ("matching " if request.creator else "accessible ") +
                ("channels" if request.view == "channels" else "liked videos") + " in this account read.")
        if request.source == "liked" and request.view == "channels":
            intro = f"Here are {len(visible)} channels from your {inspected} recent liked videos:"
            if len(visible) < request.limit:
                intro = f"I found only {len(visible)} distinct channels in your {inspected} recent liked videos:"
        elif request.source == "liked":
            intro = f"Here are your {len(visible)} most recent liked videos:"
        else:
            total = int(result.get("total", len(items)))
            intro = (f"Your imported YouTube snapshot lists {total:,} subscribed channels." if snapshot else
                f"You're subscribed to {total:,} YouTube channels.")
            if total > len(visible):
                intro += f" Showing the first {len(visible)}."
        id_key = "video_id" if request.view == "videos" else "channel_id"
        lines = []
        for index, item in enumerate(visible, 1):
            label = self._markdown_label(str(item.get("title") or item.get(id_key) or "Unknown")) \
                if request.names_only else self._account_item_label(item, id_key, "video" if id_key == "video_id" else "channel")
            if request.view == "videos" and not request.names_only and item.get("channel"):
                label += " — " + self._markdown_label(str(item["channel"]))
            lines.append(f"{index}. {label}")
        return reply(intro + "\n\n" + "\n".join(lines), visible,
            analysis="Used youtube." + ("liked_videos" if request.source == "liked" else "subscriptions") +
                (" from the imported Takeout snapshot." if snapshot else " through the official OAuth connector."))

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
        request = clear_read_request(query) or YoutubeReadRequest(source="subscriptions", view="channels", limit=50)
        return self._answer_read_request(request, {})

    def _answer_liked_videos(self) -> SpecialistResponse:
        return self._answer_read_request(YoutubeReadRequest(source="liked", view="videos"), {})

    def _answer_browser_history(self, query: str, context: dict) -> SpecialistResponse:
        request = clear_read_request(query) or YoutubeReadRequest(source="history")
        if self.planner is not None:
            try:
                request = self.planner(query, context)
                request = request if isinstance(request, YoutubeReadRequest) else YoutubeReadRequest.model_validate(request)
            except Exception as exc:
                return SpecialistResponse(agent=self.name, status="needs_fetch", confidence=1,
                    summary="The local request interpreter timed out before reading watch history. Try again when the local model is ready."
                        if isinstance(exc, TimeoutError) else "I couldn't reliably interpret this watch-history request with the local model. Please rephrase or try again.")
        if request.source not in {"history", "previous", "clarify"}:
            return SpecialistResponse(agent=self.name, status="needs_fetch", confidence=1,
                summary="I couldn't reliably interpret that as a browser watch-history read. Please rephrase.")
        return self._answer_read_request(request, context)

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
            elif item.get("history_day"):
                line += f" (listed in history for {item['history_day']}; exact time unavailable)"
            elif item.get("day_label"):
                line += f" (history page label: {item['day_label']}; date unverified)"
            lines.append(line)
        total = int(result.get('total') or 0)
        if result.get("browser_history"):
            freshness = result["browser_history"].get("freshness") or {}
            return SpecialistResponse(agent=self.name, status="answered",
                summary="Your locally saved YouTube history includes these recent entries:\n\n" + "\n".join(lines)
                    + "\n\nBrowser history has day-level or unknown dates; repeat plays and watch duration are unavailable."
                    + (" Last successful browser refresh: " + freshness["last_success_at"] if freshness.get("last_success_at") else "")
                    + (" Latest refresh status: " + freshness.get("message", "unavailable") if freshness.get("status") != "ready" else ""),
                analysis="Read local Takeout and browser history evidence with separate provenance.", confidence=1.0)
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
        result = self._subscription_feed()
        if result.get("available"):
            from agent.plugins.youtube_creator_tracking import _literal
            monitored = [creator for creator in result.get("creators", []) if creator["state"] == "monitoring"]
            lines = [f"- {creator['name']}: {creator['reason']}" for creator in monitored]
            uploads = result.get("uploads", [])[:10]
            if uploads:
                lines += ["\nSaved public uploads:"] + [f"- {_literal(item['creator'])}: {_literal(item['title'])}\n  {item['url']}" for item in uploads]
            return SpecialistResponse(agent=self.name, status="answered", confidence=1.0,
                summary=("Creator monitoring is enabled." if result.get("enabled") else "Creator monitoring is paused.") + "\n" + "\n".join(lines)
                    + "\n\n" + result["coverage"],
                analysis="Read the local creator assessment and saved Atom uploads; no live personal subscriptions-feed claim.",
                structured_payload={"creator_tracking": result})
        return SpecialistResponse(
            agent=self.name,
            status="needs_fetch",
            summary="Creator tracking has not been configured yet. Set creator relationships and history account scope in the YouTube creator settings, then enable the YouTube creator uploads automation.",
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
        browser_history = result.get("browser_history") or {}
        browser_summary = ""
        if browser_history.get("available"):
            browser_summary = "Recent browser history lists " + ", ".join(
                str(item.get("title") or item.get("video_id")) for item in browser_history.get("items", [])[:5])
            browser_summary += ". These are history-page entries; exact watch times, repeat plays, and watch duration are unavailable."
            freshness = browser_history.get("freshness") or {}
            if freshness.get("last_success_at"):
                browser_summary += " Last successful refresh: " + freshness["last_success_at"] + "."
            if freshness.get("status") != "ready":
                browser_summary += " " + freshness.get("message", "The latest refresh was unavailable.")
        if not lines and browser_summary:
            return SpecialistResponse(agent=self.name, status="answered", summary=browser_summary,
                analysis="Read local browser history evidence; no precise watch-event trend was inferred.", confidence=1.0)
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
            summary=summary + ("\n\n" + browser_summary if browser_summary else ""),
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
