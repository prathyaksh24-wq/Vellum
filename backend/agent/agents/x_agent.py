from __future__ import annotations

from html import unescape

import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.registry import ToolRegistry


class XAgent:
    name = "XAgent"

    _KEYWORDS = (
        "twitter",
        "tweet",
        "tweets",
        "latest-50",
        "bookmark",
        "bookmarks",
        "timeline",
        "feed",
        "repost",
        "retweet",
        "unlike",
        "unretweet",
        "unrepost",
        "follow",
        "unfollow",
        "quote",
        "edit",
    )
    _X_CONTEXT_PATTERNS = (
        r"(?<!\w)post(?:s|ed|ing)?\s+on\s+x(?!\w)",
        r"(?<!\w)x\s+account(?:s)?(?!\w)",
        r"(?<!\w)x\s+feed(?:s)?(?!\w)",
        r"(?<!\w)x\s+post(?:s)?(?!\w)",
        r"(?<!\w)on\s+x(?!\w)",
        r"(?<!\w)(?:my\s+)?(?:latest|recent|last)?\s*(?:liked\s+posts?|x\s+likes?)(?!\w)",
        r"(?<!\w)(?:posts?|tweets?)\s+(?:did|have)\s+i\s+like(?:d)?\s+(?:on\s+)?x(?!\w)",
        r"^\s*(?:please\s+)?(?:post|publish|tweet)\s+(?:this\s+)?(?:to|on)\s+x(?!\w)",
        r"^\s*(?:search|find|look\s+up|look\s+for)\s+(?:on\s+)?x\b",
    )

    def __init__(
        self,
        vault_root: Path,
        x_service: XCapabilityService | None = None,
        tool_registry: ToolRegistry | None = None,
        post_summarizer: Callable[[str, list[dict[str, Any]]], str] | None = None,
        post_drafter: Callable[[str], str] | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.tool_registry = tool_registry
        self.x_service = x_service or (None if tool_registry is not None else XCapabilityService())
        self.post_summarizer = post_summarizer
        self.post_drafter = post_drafter

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS) or any(
            re.search(pattern, lowered) is not None for pattern in self._X_CONTEXT_PATTERNS
        )

    def answer_with_context(self, query: str, context: dict) -> SpecialistResponse:
        action = self._write_action_from_query(query.lower())
        read_replies = bool(re.search(r"\b(?:show|read|get|summari[sz]e|what)\b.*\breplies\b", query, re.I))
        read_post = bool(re.search(r"^\s*(?:please\s+)?(?:read|show|open|get|summari[sz]e)\s+(?:this|that|it|the\s+(?:first|second|third)\s+(?:post|tweet))\b", query, re.I))
        if (action or read_replies or read_post) and not self._extract_tweet_id(query) and re.search(r"\b(?:that|this|it|second|first|third)\b", query, re.I):
            posts = context.get("posts") or []
            ordinal = next((n for word,n in {"first":0,"second":1,"third":2}.items() if re.search(rf"\b{word}\b", query, re.I)), None)
            target = posts[ordinal] if ordinal is not None and ordinal < len(posts) else posts[0] if len(posts)==1 else None
            if not target or not target.get("tweet_id"):
                return SpecialistResponse(agent=self.name, status="blocked", summary="Which post do you mean? Choose a post number or give its X link.", confidence=1.0)
            query = query + " " + str(target.get("url") or f"https://x.com/i/status/{target['tweet_id']}")
        return self.answer(query)

    @staticmethod
    def thread_context(response: SpecialistResponse, previous: dict) -> dict:
        result = dict(previous)
        posts = []
        for source in response.sources[:20]:
            match = re.search(r"https?://(?:www\.)?(?:x|twitter)\.com/[^/]+/status/(\d+)", source.path_or_url)
            if match:
                posts.append({"tweet_id":match.group(1), "url":source.path_or_url, "text":source.snippet[:1200]})
        if posts:
            result["posts"] = posts
        return result

    def answer(self, query: str) -> SpecialistResponse:
        lowered = query.lower()
        if re.search(r"\b(?:show|read|get|summari[sz]e|what)\b.*\breplies\b", lowered) and self._extract_tweet_id(query):
            return self._answer_replies(query)
        if self._extract_tweet_id(query) and re.search(r"^\s*(?:please\s+)?(?:read|show|open|get|summari[sz]e)\b|\bwhat\s+(?:does|is)\s+(?:this|that)\s+(?:post|tweet)\b", lowered) and not self._is_write_action_query(lowered):
            return self._answer_read_post(query)
        if re.search(r"\b(?:my|own)\s+(?:recent\s+|latest\s+)?(?:tweets|posts)\b", lowered) and not self._is_post_query(lowered):
            return self._answer_own_posts(query)
        if self._is_status_query(lowered):
            return self._answer_status()
        if self._is_image_post_query(lowered):
            return self._answer_image_post(query)
        if self._is_post_query(lowered):
            return self._answer_post(query)
        if self._is_write_action_query(lowered):
            return self._answer_write_action(query, lowered)
        if self._is_topic_summary_query(lowered):
            return self._answer_topic_summary(query)
        if self._is_trending_query(lowered):
            return self._answer_trending()
        if self._is_bookmarks_query(lowered):
            return self._answer_bookmarks(query, grouped=self._is_bookmark_category_query(lowered))
        if self._is_timeline_query(lowered):
            return self._answer_timeline()
        if self._is_likes_query(lowered):
            return self._answer_likes(lowered)
        if self._is_latest_account_post_query(lowered):
            return self._answer_latest_account_post(query, lowered)
        if self._is_account_query(lowered):
            return self._answer_account()
        try:
            max_results = self._requested_result_limit(query)
            result = self._search_posts({"query": query, "max_results": max_results})
        except Exception as exc:
            detail = self._sanitize_error(exc)
            summary = "XAgent could not fetch X posts right now."
            if "404" in detail:
                summary += " Agent-Reach X search returned HTTP 404."
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary=summary,
                analysis=f"X search failed: {detail}",
                confidence=0.2,
            )
        items = result.get("items", [])
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="XAgent did not find matching X posts.",
                confidence=0.35,
            )
        provider = str(result.get("provider") or "").strip()
        activity_events = self._search_activity_events(provider) if provider else []
        analysis = (
            "Used Agent-Reach through the shared X capability service."
            if provider == "agent-reach"
            else "Used x.search_posts through the shared X capability service."
        )
        lines = []
        sources = []
        for item in items[:max_results]:
            text = self._display_text(item.get("text"))
            handle = str(item.get("handle") or "x").strip()
            url = str(item.get("url") or "").strip()
            lines.append(f"- @{handle}: {text}")
            if url:
                sources.append(
                    SpecialistSource(
                        kind="web",
                        title=f"@{handle} on X",
                        path_or_url=url,
                        snippet=text[:500],
                        captured_at=str(item.get("created_at") or ""),
                        freshness="live",
                    )
                )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis=analysis,
            sources=sources,
            confidence=0.75,
            activity_events=activity_events,
        )

    @staticmethod
    def _requested_result_limit(query: str) -> int:
        match = re.search(
            r"\b(?:(?:top|show|first|latest|last)\s+)?(\d{1,2})\s+(?:results?|posts?|tweets?)\b",
            query,
            flags=re.IGNORECASE,
        )
        if not match:
            return 5
        return max(1, min(int(match.group(1)), 20))

    def _search_posts(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.search_posts", payload, agent_name=self.name)
        return self.x_service.search_posts(payload)

    def _status(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.status", payload, agent_name=self.name)
        return self.x_service.status(payload)

    def _account(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.account", payload, agent_name=self.name)
        return self.x_service.account(payload)

    def _bookmarks(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.bookmarks", payload, agent_name=self.name)
        return self.x_service.bookmarks(payload)

    def _timeline(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.timeline", payload, agent_name=self.name)
        return self.x_service.timeline(payload)

    def _likes(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.likes", payload, agent_name=self.name)
        return self.x_service.likes(payload)

    def _user_posts(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.user_posts", payload, agent_name=self.name)
        return self.x_service.user_posts(payload)

    def _publish_post(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.publish_post", payload, agent_name=self.name)
        return self.x_service.publish_post(payload)

    def _publish_post_with_media(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.publish_post_with_media", payload, agent_name=self.name)
        return self.x_service.publish_post_with_media(payload)

    def _x_write_action(self, action: str, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke(action, payload, agent_name=self.name)
        method = action.split(".", 1)[-1]
        return getattr(self.x_service, method)(payload)

    def _answer_read_post(self, query: str) -> SpecialistResponse:
        target = self._extract_tweet_id(query)
        try:
            payload = {"tweet_id": target}
            result = (self.tool_registry.invoke("x.read_tweet", payload, agent_name=self.name)
                      if self.tool_registry is not None else self.x_service.read_tweet(payload))
        except Exception as exc:
            return self._error("I could not read that X post.", exc)
        item = result.get("tweet") or {}
        text = self._display_text(item.get("text"))
        if not text:
            return SpecialistResponse(agent=self.name, status="needs_fetch", summary="That post has no readable text or is unavailable.", confidence=0.4)
        handle = str(item.get("handle") or "x").lstrip("@")
        return SpecialistResponse(agent=self.name, status="answered", summary=f"@{handle}: {text}",
            analysis="Used x.read_tweet through Agent Reach.", sources=self._sources_for_posts([item]), confidence=0.9,
            activity_events=self._read_activity_events("read_tweet", str(result.get("provider") or "")))

    def _answer_status(self) -> SpecialistResponse:
        try:
            result = self._status({"probe_search": True})
        except Exception as exc:
            return self._error("XAgent could not check the X connector right now.", exc)
        connector = result.get("connector", {})
        capabilities = connector.get("capabilities", {})
        lines = [f"X connector: {connector.get('status', 'unknown')}."]
        for name in (
            "search",
            "timeline",
            "bookmarks",
            "likes",
            "post",
            "reply",
            "repost",
            "delete",
            "edit",
        ):
            capability = capabilities.get(name, {})
            if capability:
                lines.append(f"{name}: {capability.get('status', 'unknown')}")
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used x.status through the shared X capability service.",
            confidence=0.9,
        )

    def _answer_account(self) -> SpecialistResponse:
        try:
            result = self._account({})
        except Exception as exc:
            return self._error("XAgent could not read the X account right now.", exc)
        account = result.get("account", {})
        username = str(account.get("username") or account.get("name") or "").strip()
        summary = f"Authenticated X account: @{username}" if username else "Authenticated X account was found."
        return SpecialistResponse(agent=self.name, status="answered", summary=summary, analysis="Used x.account.", confidence=0.75)

    def _answer_bookmarks(self, query: str, *, grouped: bool = False) -> SpecialistResponse:
        ordinal = self._bookmark_ordinal(query)
        summarize = self._is_bookmark_summary_query(query.lower())
        max_results = ordinal or (20 if grouped or summarize else 5)
        try:
            result = self._bookmarks({"max_results": max_results})
        except Exception as exc:
            return self._error("XAgent could not read X bookmarks right now.", exc)
        items = result.get("items", [])
        if not items:
            return SpecialistResponse(agent=self.name, status="needs_fetch", summary="XAgent did not find X bookmarks.", confidence=0.35)
        if ordinal:
            if len(items) < ordinal:
                return SpecialistResponse(
                    agent=self.name,
                    status="needs_fetch",
                    summary=f"I found only {len(items)} recent X bookmarks, so there is no {self._ordinal_label(ordinal)} item.",
                    confidence=0.6,
                    activity_events=self._read_activity_events("bookmarks", str(result.get("provider") or "")),
                )
            item = items[ordinal - 1]
            text = self._display_text(item.get("text"))
            handle = str(item.get("handle") or "x").strip()
            return SpecialistResponse(
                agent=self.name,
                status="answered",
                summary=f"Your {self._ordinal_label(ordinal)} bookmark is from @{handle}:\n\n{text}",
                analysis="Used x.bookmarks and selected the requested saved-post position.",
                sources=self._sources_for_posts([item]),
                confidence=0.85,
                activity_events=self._read_activity_events("bookmarks", str(result.get("provider") or "")),
            )
        if summarize:
            return SpecialistResponse(
                agent=self.name,
                status="answered",
                summary=self._bookmark_summary(items),
                analysis="Summarized recent bookmarks returned by x.bookmarks.",
                sources=self._sources_for_posts(items[:5]),
                confidence=0.8,
                activity_events=self._read_activity_events("bookmarks", str(result.get("provider") or "")),
            )
        lines, sources = self._format_posts(items)
        if grouped:
            groups: dict[str, list[str]] = {}
            for item in items:
                intelligence = item.get("bookmark_intelligence")
                assignments = intelligence.get("assignments") if isinstance(intelligence, dict) else []
                primary = assignments[0] if isinstance(assignments, list) and assignments else {}
                category = str(primary.get("name") or "General") if isinstance(primary, dict) else "General"
                text = self._display_text(item.get("text"))
                handle = str(item.get("handle") or "x").strip()
                entry = f"@{handle}: {text}"
                groups.setdefault(category, []).append(entry)
            lines = []
            for category in sorted(groups):
                lines.append(f"{category}")
                lines.extend(f"- {entry}" for entry in groups[category])
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used x.bookmarks through the shared X capability service.",
            sources=sources,
            confidence=0.75,
            activity_events=self._read_activity_events("bookmarks", str(result.get("provider") or "")),
        )

    def _answer_trending(self) -> SpecialistResponse:
        try:
            result = self._timeline({"max_results": 20})
        except Exception as exc:
            return self._error(
                "XAgent needs an authenticated Agent Reach session to read what is happening on X.",
                exc,
            )
        items = result.get("items", [])
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="XAgent did not find current timeline posts.",
                confidence=0.35,
            )
        lines, sources = self._format_posts(items)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="Current posts from your X timeline:\n" + "\n".join(lines),
            analysis="Used the authenticated Agent Reach X timeline.",
            sources=sources,
            confidence=0.8,
            activity_events=self._read_activity_events("timeline", str(result.get("provider") or "")),
        )

    def _answer_topic_summary(self, query: str) -> SpecialistResponse:
        topic = self._topic_from_summary_query(query)
        try:
            if topic:
                result = self._search_posts({"query": topic, "max_results": 20})
                read_type = "search"
            else:
                result = self._timeline({"max_results": 20})
                read_type = "timeline"
        except Exception as exc:
            return self._error("XAgent could not gather live X posts for that summary.", exc)
        items = result.get("items", [])
        provider = str(result.get("provider") or "")
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="I did not find enough live X posts to summarize that topic.",
                confidence=0.35,
                activity_events=(
                    self._search_activity_events(provider)
                    if read_type == "search"
                    else self._read_activity_events("timeline", provider)
                ),
            )
        try:
            summary = self._synthesize_posts(query, items)
            analysis = "Synthesized live Agent Reach X evidence with the active Vellum model."
        except Exception:
            summary = self._compact_topic_digest(items)
            analysis = "Used a compact deterministic digest because model synthesis was unavailable."
        events = (
            self._search_activity_events(provider)
            if read_type == "search"
            else self._read_activity_events("timeline", provider)
        )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis=analysis,
            sources=self._sources_for_posts(items[:8]),
            confidence=0.8,
            activity_events=events,
        )

    def _synthesize_posts(self, query: str, items: list[dict[str, Any]]) -> str:
        summarizer = self.post_summarizer
        if summarizer is None:
            from agent.agents.x_synthesis import RoutedXPostSynthesizer

            summarizer = RoutedXPostSynthesizer()
        summary = str(summarizer(query, items) or "").strip()
        summary = re.sub(r"(?m)^#{1,6}\s*", "", summary)
        summary = re.sub(r"(?m)^\s*[-*]\s+", "", summary)
        return summary

    @classmethod
    def _compact_topic_digest(cls, items: list[dict[str, Any]]) -> str:
        highlights = []
        for item in items[:3]:
            text = cls._display_text(item.get("text"))
            if len(text) > 180:
                text = text[:177].rstrip() + "…"
            handle = str(item.get("handle") or "x").strip().lstrip("@")
            if text:
                highlights.append(f"@{handle} says {text}")
        if not highlights:
            return "I found live X posts, but they did not contain enough text to summarize."
        return f"Across {len(items)} relevant X posts, " + " ".join(highlights)

    def _answer_timeline(self) -> SpecialistResponse:
        try:
            result = self._timeline({"max_results": 5})
        except Exception as exc:
            return self._error("XAgent could not read the X timeline right now.", exc)
        items = result.get("items", [])
        if not items:
            return SpecialistResponse(agent=self.name, status="needs_fetch", summary="XAgent did not find X timeline posts.", confidence=0.35)
        lines, sources = self._format_posts(items)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used x.timeline through the shared X capability service.",
            sources=sources,
            confidence=0.75,
            activity_events=self._read_activity_events("timeline", str(result.get("provider") or "")),
        )

    def _answer_likes(self, lowered_query: str) -> SpecialistResponse:
        latest_only = bool(re.search(r"(?<!\w)(?:latest|newest|last|most\s+recent)\b", lowered_query))
        try:
            result = self._likes({"handle": "me", "max_results": 1 if latest_only else 5})
        except Exception as exc:
            return self._error("XAgent could not read X likes right now.", exc)
        items = result.get("items", [])
        provider = str(result.get("provider") or "")
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="XAgent did not find X likes.",
                confidence=0.35,
                activity_events=self._read_activity_events("likes", provider),
            )
        if latest_only:
            item = items[0]
            text = self._display_text(item.get("text"))
            handle = str(item.get("handle") or "x").strip()
            return SpecialistResponse(
                agent=self.name,
                status="answered",
                summary=f"Your latest liked post is from @{handle}:\n\n{text}",
                analysis="Used x.likes and returned only the newest liked post.",
                sources=self._sources_for_posts([item]),
                confidence=0.85,
                activity_events=self._read_activity_events("likes", provider),
            )
        lines, sources = self._format_posts(items)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used x.likes through the shared X capability service.",
            sources=sources,
            confidence=0.75,
            activity_events=self._read_activity_events("likes", provider),
        )

    def _answer_own_posts(self, query: str) -> SpecialistResponse:
        try:
            account = self._account({}).get("account") or {}
            handle = str(account.get("username") or account.get("screenName") or account.get("screen_name") or "").lstrip("@")
            if not handle:
                raise ValueError("The X session did not identify your account")
            result = self._user_posts({"handle":handle, "max_results":20})
            items = [p for p in result.get("items",[]) if str(p.get("handle") or "").lstrip("@").casefold() == handle.casefold()]
            count = self._requested_result_limit(query)
            items = sorted(items, key=lambda p:int(str(p.get("id") or "0")) if str(p.get("id") or "0").isdigit() else 0, reverse=True)[:count]
            lines, sources = self._format_posts(items)
            return SpecialistResponse(agent=self.name, status="answered" if items else "needs_fetch",
                summary="Your recent posts:\n"+"\n".join(lines) if items else "No recent posts from your account were returned.",
                sources=sources, analysis="Used Agent-Reach authenticated account and user posts.", confidence=.9)
        except Exception as exc:
            return self._error("I could not read your own X posts.", exc)

    def _answer_replies(self, query: str) -> SpecialistResponse:
        payload = {"tweet_id":self._extract_tweet_id(query), "max_results":5}
        try:
            result = self.tool_registry.invoke("x.replies", payload, agent_name=self.name) if self.tool_registry else self.x_service.replies(payload)
            items = result.get("items", [])
            lines,sources = self._format_posts(items)
            return SpecialistResponse(agent=self.name, status="answered", summary="\n".join(lines) if lines else "No visible replies were returned for that post.",
                sources=sources, analysis="Used Agent-Reach post conversation; only visible replies in this sample.", confidence=.9)
        except Exception as exc:
            return self._error("I could not read those X replies.", exc)

    def _answer_latest_account_post(self, query: str, lowered_query: str) -> SpecialistResponse:
        handle = self._latest_account_handle(query)
        own_account = self._is_self_account_reference(lowered_query)
        if own_account:
            try:
                account_result = self._account({})
            except Exception as exc:
                return self._error("XAgent could not identify your X account right now.", exc)
            account = account_result.get("account", {})
            handle = str(
                account.get("username")
                or account.get("screenName")
                or account.get("screen_name")
                or ""
            ).strip().lstrip("@")
        if not handle:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="Tell me the X @handle whose latest post you want.",
                confidence=0.5,
            )
        try:
            result = self._user_posts({"handle": handle, "max_results": 20})
        except Exception as exc:
            return self._error(f"XAgent could not read the latest post from @{handle}.", exc)
        items = result.get("items", [])
        if own_account:
            # X's user-posts timeline includes reposts authored by other accounts.
            items = [item for item in items if str(item.get("handle") or "").lstrip("@").casefold() == handle.casefold()]
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary=f"I did not find a recent post from @{handle}.",
                confidence=0.4,
                activity_events=self._read_activity_events("user_posts", str(result.get("provider") or "")),
            )
        items = sorted(items, key=lambda p:int(str(p.get("id") or "0")) if str(p.get("id") or "0").isdigit() else 0, reverse=True)
        item = items[0]
        text = self._display_text(item.get("text"))
        returned_handle = str(item.get("handle") or handle).strip().lstrip("@")
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=f"Latest post from @{returned_handle}:\n\n{text}",
            analysis="Used x.user_posts and returned one newest account post.",
            sources=self._sources_for_posts([item]),
            confidence=0.85,
            activity_events=self._read_activity_events("user_posts", str(result.get("provider") or "")),
        )

    def _answer_post(self, query: str) -> SpecialistResponse:
        text = self._extract_exact_post_envelope(query)
        if not text:
            text = self._extract_quoted_text(query)
        if not text:
            instruction = self._extract_unquoted_post_instruction(query)
            if instruction and self._should_draft_post(instruction):
                try:
                    text = self._draft_post(query)
                except Exception:
                    return SpecialistResponse(
                        agent=self.name,
                        status="blocked",
                        summary="I could not draft the X post right now. Tell me the tone or topic and I’ll try again.",
                        confidence=0.35,
                    )
            elif instruction:
                text = instruction
        if not text:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs the exact post text before publishing.",
                confidence=0.4,
            )
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary=f'Confirm before I post this to X:\n\n"{text}"',
            analysis="Prepared x.publish_post and is waiting for explicit confirmation.",
            confidence=0.65,
            action_request={
                "action": "x.publish_post",
                "payload": {"text": text},
                "preview": text,
            },
            activity_events=[
                {"type": "tool_call_started", "label": "Preparing post...", "name": "agent_reach_x_prepare_post"},
            ],
        )

    def _draft_post(self, request: str) -> str:
        drafter = self.post_drafter
        if drafter is None:
            from agent.agents.x_synthesis import RoutedXPostDrafter

            drafter = RoutedXPostDrafter()
        return str(drafter(request) or "").strip()

    def execute_action_request(self, action_request: dict) -> SpecialistResponse:
        action = str(action_request.get("action") or "")
        payload = action_request.get("payload") if isinstance(action_request.get("payload"), dict) else {}
        if action == "x.publish_post":
            return self._execute_publish_post(payload)
        if action == "x.publish_post_with_media":
            return self._execute_publish_post_with_media(payload)
        if action in {
            "x.reply", "x.like", "x.unlike", "x.repost", "x.unrepost",
            "x.bookmark", "x.unbookmark", "x.quote", "x.follow", "x.unfollow", "x.delete",
        }:
            return self._execute_write_action(action, payload)
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary="XAgent cannot execute that pending X action.",
            confidence=0.3,
        )

    def _execute_publish_post(self, payload: dict) -> SpecialistResponse:
        text = str(payload.get("text") or "").strip()
        if not text:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs the exact post text before publishing.",
                confidence=0.4,
            )
        try:
            result = self._publish_post({"text": text, "confirm": True})
        except Exception as exc:
            return self._error("XAgent could not publish to X right now.", exc)
        tweet = result.get("tweet", {})
        tweet_id = str(tweet.get("id") or "").strip()
        summary = f"Posted to X: {tweet_id}" if tweet_id else "Posted to X."
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Used x.publish_post.",
            confidence=0.8,
            activity_events=[
                {
                    "type": "tool_call_started",
                    "label": "Posting to X...",
                    "name": "agent_reach_x_post",
                    "metadata": {"suppress_generic_tool": True},
                },
                {
                    "type": "tool_call_completed",
                    "label": "X action completed",
                    "name": "agent_reach_x_completed",
                    "status": "completed",
                    "metadata": {"suppress_generic_tool": True},
                },
            ],
        )

    def _execute_publish_post_with_media(self, payload: dict) -> SpecialistResponse:
        text = str(payload.get("text") or "").strip()
        image_prompt = str(payload.get("image_prompt") or "").strip()
        image_path = str(payload.get("image_path") or "").strip()
        if not text:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs the exact post text before publishing an image post.",
                confidence=0.4,
            )
        if not image_prompt and not image_path:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs an image prompt or image path before publishing an X image post.",
                confidence=0.4,
            )
        confirmed_payload = {"text": text, "confirm": True}
        if image_path:
            confirmed_payload["image_path"] = image_path
        else:
            confirmed_payload["image_prompt"] = image_prompt
        try:
            result = self._publish_post_with_media(confirmed_payload)
        except Exception as exc:
            return self._error("XAgent could not publish the image post to X right now.", exc)
        tweet = result.get("tweet", {})
        tweet_id = str(tweet.get("id") or "").strip()
        summary = f"Posted image to X: {tweet_id}" if tweet_id else "Posted image to X."
        return SpecialistResponse(
            agent=self.name, status="answered", summary=summary,
            analysis="Used x.publish_post_with_media.", confidence=0.8,
        )

    def _answer_write_action(self, query: str, lowered_query: str) -> SpecialistResponse:
        action = self._write_action_from_query(lowered_query)
        if action == "x.edit":
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent does not support editing published X posts.",
                analysis="The active connector has no edit operation.",
                confidence=0.9,
            )
        follows_account = action in {"x.follow", "x.unfollow"}
        target = self._extract_handle(query) if follows_account else self._extract_tweet_id(query)
        if not target and not follows_account and self._is_latest_account_post_query(lowered_query):
            read = self._answer_latest_account_post(query, lowered_query)
            if read.status != "answered":
                return read
            if len(read.sources) == 1:
                target = read.sources[0].path_or_url
        if not target:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary=(
                    "XAgent needs an @handle before taking that X action."
                    if follows_account
                    else "XAgent needs the post URL or post ID before taking that X action."
                ),
                confidence=0.4,
            )
        text = self._extract_quoted_text(query) if action in {"x.reply", "x.quote"} else ""
        if action in {"x.reply", "x.quote"} and not text:
            instruction = re.sub(r"https?://\S+", "", query).strip()
            try:
                text = self._draft_post(instruction)
            except Exception as exc:
                return self._error("I could not draft that X reply right now.", exc)
        verb = action.split(".")[-1]
        payload = {"handle": target} if follows_account else {"tweet_id": target}
        if text:
            payload["text"] = text
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary=f"Confirm before I {self._write_action_label(verb)} this X target:\n\n{target}" + (f"\n\n{text}" if text else ""),
            analysis=f"Prepared {action} and is waiting for explicit confirmation.",
            confidence=0.65,
            action_request={"action": action, "payload": payload, "preview": target + (f"\n{text}" if text else "")},
            activity_events=[
                {
                    "type": "tool_call_started",
                    "label": f"Preparing X {verb}...",
                    "name": f"agent_reach_x_prepare_{verb}",
                    "metadata": {"suppress_generic_tool": True},
                },
            ],
        )

    def _execute_write_action(self, action: str, payload: dict) -> SpecialistResponse:
        normalized_payload = dict(payload)
        if "tweet_id" in normalized_payload or "url" in normalized_payload or "tweet_url" in normalized_payload:
            normalized_payload["tweet_id"] = self._normalize_tweet_id_or_url(
                str(normalized_payload.get("tweet_id") or normalized_payload.get("url") or normalized_payload.get("tweet_url") or "")
            )
            normalized_payload.pop("url", None)
            normalized_payload.pop("tweet_url", None)
        try:
            result = self._x_write_action(action, {**normalized_payload, "confirm": True})
        except Exception as exc:
            return self._error(f"XAgent could not complete {action}.", exc)
        verb = action.split(".")[-1]
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=f"X {verb} completed.",
            analysis=f"Used {action}.",
            confidence=0.8,
            activity_events=[
                {
                    "type": "tool_call_started",
                    "label": self._write_action_activity_label(verb),
                    "name": f"agent_reach_x_{verb}",
                    "metadata": {"suppress_generic_tool": True},
                },
                {
                    "type": "tool_call_completed",
                    "label": "X action completed",
                    "name": "agent_reach_x_completed",
                    "status": "completed",
                    "metadata": {"suppress_generic_tool": True},
                },
            ],
        )

    def _answer_image_post(self, query: str) -> SpecialistResponse:
        text = self._extract_quoted_text(query)
        image_prompt = self._extract_image_prompt(query)
        if not text:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs the exact post text before publishing an image post.",
                confidence=0.4,
            )
        if not image_prompt:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs an image prompt before generating an X image post.",
                confidence=0.4,
            )
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary=f'Confirm before I generate an image and post this to X:\n\n"{text}"',
            analysis="Prepared x.publish_post_with_media and is waiting for explicit confirmation.",
            confidence=0.65,
            action_request={
                "action": "x.publish_post_with_media",
                "payload": {"text": text, "image_prompt": image_prompt},
                "preview": text,
            },
            activity_events=[
                {
                    "type": "tool_call_started",
                    "label": "Preparing image post...",
                    "name": "agent_reach_x_prepare_image_post",
                },
            ],
        )

    def _format_posts(self, items: list[dict]) -> tuple[list[str], list[SpecialistSource]]:
        lines = []
        sources = self._sources_for_posts(items[:5])
        for item in items[:5]:
            text = self._display_text(item.get("text"))
            handle = str(item.get("handle") or "x").strip()
            line = f"- @{handle}: {text}" if handle else f"- {text}"
            lines.append(line)
        return lines, sources

    def _sources_for_posts(self, items: list[dict]) -> list[SpecialistSource]:
        sources = []
        for item in items:
            text = str(item.get("text") or "").strip()
            handle = str(item.get("handle") or "x").strip().lstrip("@")
            url = str(item.get("url") or "").strip()
            if url:
                sources.append(
                    SpecialistSource(
                        kind="web",
                        title=f"@{handle} on X",
                        path_or_url=url,
                        snippet=text[:500],
                        captured_at=str(item.get("created_at") or ""),
                        freshness="live",
                    )
                )
        return sources

    def _bookmark_summary(self, items: list[dict]) -> str:
        category_counts: Counter[str] = Counter()
        for item in items:
            intelligence = item.get("bookmark_intelligence")
            assignments = intelligence.get("assignments") if isinstance(intelligence, dict) else []
            primary = assignments[0] if isinstance(assignments, list) and assignments else {}
            category = str(primary.get("name") or "General") if isinstance(primary, dict) else "General"
            category_counts[category] += 1
        ranked = category_counts.most_common(4)
        topic_text = self._human_join([f"{name} ({count})" for name, count in ranked])
        highlights = []
        for item in items[:3]:
            text = self._display_text(item.get("text"))
            if len(text) > 150:
                text = text[:147].rstrip() + "…"
            handle = str(item.get("handle") or "x").strip().lstrip("@")
            if text:
                highlights.append(f"@{handle}: {text}")
        summary = f"You have {len(items)} recent bookmarks."
        if topic_text:
            summary += f" Main topics: {topic_text}."
        if highlights:
            summary += "\n\nHighlights: " + " ".join(highlights)
        return summary

    @staticmethod
    def _display_text(value: Any) -> str:
        text = re.sub(r"https?://\S+", "", unescape(str(value or "")), flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    def _search_activity_events(self, provider: str) -> list[dict]:
        if provider == "agent-reach":
            metadata = {"suppress_generic_tool": True}
            return [
                {
                    "type": "tool_call_started",
                    "label": "Searching X with Agent-Reach...",
                    "name": "agent_reach_x_search",
                    "metadata": metadata,
                },
                {
                    "type": "source_reading",
                    "label": "Reading X results...",
                    "name": "agent_reach_x_reading",
                    "metadata": metadata,
                },
                {
                    "type": "tool_call_completed",
                    "label": "X action completed",
                    "name": "agent_reach_x_completed",
                    "status": "completed",
                    "metadata": metadata,
                },
            ]
        if provider == "xai":
            return [
                {"type": "tool_call_started", "label": "Searching X with xAI...", "name": "xai_x_search"},
                {"type": "tool_call_completed", "label": "X search completed", "name": "xai_x_search", "status": "completed"},
            ]
        return []

    def _read_activity_events(self, read_type: str, provider: str) -> list[dict]:
        if provider != "agent-reach":
            return []
        metadata = {"suppress_generic_tool": True}
        label = {
            "bookmarks": "Fetching X bookmarks with Agent-Reach...",
            "timeline": "Fetching X timeline with Agent-Reach...",
            "likes": "Fetching X likes with Agent-Reach...",
            "user_posts": "Fetching latest X account post with Agent-Reach...",
        }.get(read_type, "Reading X with Agent-Reach...")
        return [
            {"type": "tool_call_started", "label": label, "name": f"agent_reach_x_{read_type}", "metadata": metadata},
            {
                "type": "tool_call_completed",
                "label": "X action completed",
                "name": "agent_reach_x_completed",
                "status": "completed",
                "metadata": metadata,
            },
        ]

    def _error(self, summary: str, exc: Exception) -> SpecialistResponse:
        detail = self._sanitize_error(exc)
        if "daily limit" in str(exc).casefold():
            return SpecialistResponse(agent=self.name, status="error", summary="X refused this action because your account has reached its daily posting limit. Try again after X resets the limit.", analysis=detail, confidence=1.0)
        return SpecialistResponse(
            agent=self.name,
            status="error",
            summary=summary + (" " + detail[:240] if detail else ""),
            analysis=detail,
            confidence=0.2,
        )

    def _is_bookmarks_query(self, lowered_query: str) -> bool:
        return "bookmark" in lowered_query or "saved posts" in lowered_query

    def _is_bookmark_category_query(self, lowered_query: str) -> bool:
        return self._is_bookmarks_query(lowered_query) and bool(
            re.search(r"(?<!\w)(?:categor(?:y|ies|ize|ise)|organize|organise|group|sort|topics?)\b", lowered_query)
        )

    def _is_bookmark_summary_query(self, lowered_query: str) -> bool:
        return self._is_bookmarks_query(lowered_query) and bool(
            re.search(r"(?<!\w)(?:summari[sz]e|summary|overview|recap|digest)\b", lowered_query)
        )

    @staticmethod
    def _bookmark_ordinal(query: str) -> int | None:
        word_ordinals = {
            "first": 1,
            "second": 2,
            "third": 3,
            "fourth": 4,
            "fifth": 5,
            "sixth": 6,
            "seventh": 7,
            "eighth": 8,
            "ninth": 9,
            "tenth": 10,
        }
        match = re.search(
            r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d{1,2}(?:st|nd|rd|th))\b",
            query,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        token = match.group(1).casefold()
        if token in word_ordinals:
            return word_ordinals[token]
        return max(1, min(int(re.match(r"\d+", token).group(0)), 20))

    @staticmethod
    def _ordinal_label(value: int) -> str:
        if 10 <= value % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
        return f"{value}{suffix}"

    def _is_trending_query(self, lowered_query: str) -> bool:
        return bool(
            re.search(
                r"(?<!\w)(?:what(?:'s|\s+is)\s+happening|what(?:'s|\s+is)\s+go(?:ing|ign)\s+on|trending|trends?|current\s+conversation)\b.*\b(?:on\s+)?(?:x|twitter)(?!\w)",
                lowered_query,
            )
            or re.search(
                r"(?<!\w)(?:x|twitter)\b.*\b(?:what(?:'s|\s+is)\s+happening|trending|trends?)(?!\w)",
                lowered_query,
            )
        )

    @staticmethod
    def _is_topic_summary_query(lowered_query: str) -> bool:
        asks_for_synthesis = bool(
            re.search(
                r"(?<!\w)(?:summari[sz]e|summary|overview|recap|catch\s+me\s+up|latest\s+news|what(?:'s|\s+is)\s+(?:go(?:ing|ign)\s+on|happening)|trending|trends?|current\s+conversation)\b",
                lowered_query,
            )
        )
        return asks_for_synthesis and bool(
            re.search(r"(?<!\w)(?:x|twitter)\b", lowered_query)
            or re.search(r"(?<!\w)(?:about|regarding)\s+\S+", lowered_query)
        )

    @staticmethod
    def _topic_from_summary_query(query: str) -> str:
        match = re.search(
            r"\b(?:about|regarding)\s+(.+?)(?:\s+on\s+(?:x|twitter)\b|[?.!,]|$)",
            query,
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        return match.group(1).strip()

    def _is_timeline_query(self, lowered_query: str) -> bool:
        return bool(re.search(r"(?<!\w)(timeline|feed|home feed|following feed)\b", lowered_query))

    def _is_likes_query(self, lowered_query: str) -> bool:
        return bool(
            re.search(
                r"(?<!\w)(?:my\s+)?(?:latest|recent|last)?\s*(?:liked\s+posts?|likes?|x\s+likes?)\b",
                lowered_query,
            )
            or re.search(
                r"(?<!\w)(?:posts?|tweets?)\s+(?:did|have)\s+i\s+like(?:d)?\s+(?:on\s+)?x(?!\w)", lowered_query
            )
            or re.search(
                r"(?<!\w)(?:latest|newest|last|most\s+recent)?\s*(?:post|tweet)\s+i\s+(?:liked|favorited)\b",
                lowered_query,
            )
        ) and not re.search(r"(?<!\w)(?:like|favorite)\s+(?:this|that|the)\b", lowered_query)

    def _is_write_action_query(self, lowered_query: str) -> bool:
        return self._write_action_from_query(lowered_query) != ""

    def _write_action_from_query(self, lowered_query: str) -> str:
        if re.search(r"(?<!\w)edit\b", lowered_query):
            return "x.edit"
        if re.search(r"(?<!\w)unbookmark\b|remove\s+(?:this\s+)?bookmark", lowered_query):
            return "x.unbookmark"
        if re.search(r"(?<!\w)bookmark\s+(?:this|that|the|https?://)", lowered_query):
            return "x.bookmark"
        if re.search(r"(?<!\w)unlike\b|remove\s+(?:my\s+)?like", lowered_query):
            return "x.unlike"
        if re.search(r"(?<!\w)(?:unretweet|unrepost)\b|undo\s+(?:my\s+)?(?:retweet|repost)", lowered_query):
            return "x.unrepost"
        if re.search(r"(?<!\w)quote(?:\s+tweet)?\b", lowered_query):
            return "x.quote"
        if re.search(r"(?<!\w)unfollow\b", lowered_query):
            return "x.unfollow"
        if re.search(r"(?<!\w)follow\b", lowered_query):
            return "x.follow"
        if re.search(r"(?<!\w)(delete|remove)\b", lowered_query):
            return "x.delete"
        if re.search(r"(?<!\w)(repost|retweet)\b", lowered_query):
            return "x.repost"
        if re.search(r"(?<!\w)(?:like|favorite)\s+(?:this|that|the|https?://)", lowered_query):
            return "x.like"
        if re.search(r"(?<!\w)reply\b", lowered_query):
            return "x.reply"
        return ""

    def _is_status_query(self, lowered_query: str) -> bool:
        text = re.sub(r"https?://\S+", "", lowered_query)
        asks_status = re.search(r"(?<!\w)(?:status|connected|working|capabilities|available)\b", text)
        x_context = re.search(r"(?<!\w)(?:x|twitter|x\s+agent|connector)\b", text)
        return bool(asks_status and x_context)

    def _is_account_query(self, lowered_query: str) -> bool:
        return bool(re.search(r"(?<!\w)(me|account|profile)\s+(?:on\s+)?x(?!\w)", lowered_query))

    def _is_post_query(self, lowered_query: str) -> bool:
        return bool(
            re.search(
                r"^\s*(?:please\s+)?(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:post|publish|tweet)\b",
                lowered_query,
            )
            or re.search(
                r"^\s*(?:please\s+)?(?:using\s+(?:the\s+)?x\s+agent\s+)?(?:post|publish|tweet)\b",
                lowered_query,
            )
            or re.search(
                r"^\s*(?:please\s+)?(?:using\s+(?:the\s+)?x\s+agent\s+)?create\s+(?:a\s+)?(?:post|tweet)\b",
                lowered_query,
            )
            or re.search(r"\bnot\s+(?:find|search)\b.*\bcreate\s+(?:a\s+)?(?:post|tweet)\b", lowered_query)
        )

    def _is_latest_account_post_query(self, lowered_query: str) -> bool:
        return bool(
            re.search(r"(?<!\w)(?:latest|newest|last|most\s+recent)\b", lowered_query)
            and re.search(r"(?<!\w)(?:post|tweet)\b", lowered_query)
            and (re.search(r"(?<!\w)(?:from|by|of)\b", lowered_query)
                 or self._is_self_account_reference(lowered_query))
        )

    @staticmethod
    def _is_self_account_reference(lowered_query: str) -> bool:
        return bool(
            re.search(r"\bmy\s+(?:(?:latest|newest|last|most\s+recent|x|twitter)\s+)*(?:post|tweet)\b", lowered_query)
            or
            re.search(
                r"\b(?:from|by|of)\s+(?:my(?:\s+x)?\s+account|myself|me)\b",
                lowered_query,
            )
        )

    def _latest_account_handle(self, query: str) -> str:
        handle = self._extract_handle(query)
        if handle:
            return handle
        match = re.search(
            r"\b(?:from|by|of)\s+(.+?)(?:\s+on\s+(?:x|twitter)\b|[?.!,]|$)",
            query,
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        candidate = match.group(1).strip()
        if re.fullmatch(r"(?:my(?:\s+x)?\s+account|myself|me)", candidate, flags=re.IGNORECASE):
            return ""
        words = re.findall(r"[A-Za-z0-9_]+", candidate)
        if not words:
            return ""
        if len(words) == 1:
            return words[0]
        return "".join(word[:1].upper() + word[1:] for word in words)

    def _is_image_post_query(self, lowered_query: str) -> bool:
        if self._is_post_query(lowered_query) and any(word in lowered_query for word in ("image", "photo", "picture", "generate")):
            return True
        return bool(
            re.search(
                r"^\s*(?:please\s+)?generate\s+an?\s+image\b.*\b(?:post|publish|tweet)\s+(?:it\s+)?(?:to|on)\s+x(?!\w)",
                lowered_query,
            )
        )

    def _extract_quoted_text(self, query: str) -> str:
        match = re.search(r'"([^"]+)"', query)
        if match:
            return match.group(1).strip()
        match = re.search(r"'([^']+)'", query)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_exact_post_envelope(query: str) -> str:
        match = re.search(
            r"\[X post text\]\s*(.*?)\s*\[/X post text\]",
            query,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_unquoted_post_instruction(query: str) -> str:
        match = re.search(
            r"^\s*(?:(?:please|plese)\s+)?(?:(?:can|could|would|will)\s+you\s+)?"
            r"(?:using\s+(?:the\s+)?x\s+agent\s+)?(?:post|publish|tweet)\b\s*(.*)$",
            query,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        instruction = match.group(1).strip(" :.-")
        instruction = re.sub(r"^(?:a\s+)?tweet\b\s*", "", instruction, flags=re.IGNORECASE)
        return instruction.strip()

    @staticmethod
    def _should_draft_post(instruction: str) -> bool:
        lowered = " ".join(instruction.casefold().split())
        return bool(
            re.search(r"\b(?:something|anything|random|funny|joke|witty|clever|interesting)\b", lowered)
            or re.search(r"^(?:about|on)\s+\S+", lowered)
        )

    def _extract_tweet_id(self, query: str) -> str:
        url_match = re.search(r"https?://(?:www\.)?(?:x|twitter)\.com/[^\s]+/status/\d+", query)
        if url_match:
            return url_match.group(0)
        id_match = re.search(r"\b\d{8,}\b", query)
        return id_match.group(0) if id_match else ""

    def _extract_handle(self, query: str) -> str:
        match = re.search(r"(?<![\w/])@([A-Za-z0-9_]{1,15})\b", query)
        return match.group(1) if match else ""

    def _normalize_tweet_id_or_url(self, value: str) -> str:
        match = re.search(r"(?:/status/|^)(\d{8,})(?:\D|$)", value.strip())
        return match.group(1) if match else value.strip()

    def _write_action_label(self, verb: str) -> str:
        return {
            "delete": "delete",
            "repost": "repost",
            "unrepost": "remove the repost of",
            "like": "like",
            "unlike": "unlike",
            "reply": "reply to",
            "quote": "quote",
            "bookmark": "bookmark",
            "unbookmark": "remove the bookmark from",
            "follow": "follow",
            "unfollow": "unfollow",
        }.get(verb, verb)

    def _write_action_activity_label(self, verb: str) -> str:
        return {
            "delete": "Deleting X post...",
            "repost": "Reposting on X...",
            "unrepost": "Removing X repost...",
            "like": "Liking X post...",
            "unlike": "Removing X like...",
            "reply": "Replying on X...",
            "quote": "Quoting X post...",
            "bookmark": "Bookmarking X post...",
            "unbookmark": "Removing X bookmark...",
            "follow": "Following X account...",
            "unfollow": "Unfollowing X account...",
        }.get(verb, "Running X action...")

    @staticmethod
    def _human_join(values: list[str]) -> str:
        cleaned = [value for value in values if value]
        if len(cleaned) < 2:
            return cleaned[0] if cleaned else ""
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"

    def _extract_image_prompt(self, query: str) -> str:
        patterns = (
            r"generate\s+an?\s+image\s+of\s+(.+?)\s+and\s+(?:post|publish|tweet)",
            r"image\s+of\s+(.+?)\s+and\s+(?:post|publish|tweet)",
            r"photo\s+of\s+(.+?)\s+and\s+(?:post|publish|tweet)",
        )
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _sanitize_error(self, exc: Exception) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ").strip()
        message = re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|authorization|bearer|client[_-]?secret|password)\s*[:=]\s*\S+",
            r"\1=[redacted]",
            message,
        )
        message = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[redacted]", message)
        if not message:
            message = exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"[:160]
