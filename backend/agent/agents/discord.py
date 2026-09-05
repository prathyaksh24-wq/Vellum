from __future__ import annotations

import re

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.discord_service import DiscordCapabilityService
from agent.tools.registry import ToolRegistry


class DiscordAgent:
    name = "DiscordAgent"
    WRITE_ACTIONS = frozenset({
        "discord.send_message",
        "discord.reply_message",
        "discord.edit_own_message",
        "discord.delete_own_message",
        "discord.add_reaction",
        "discord.create_thread",
        "discord.send_thread_message",
        "discord.send_attachment",
    })

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        discord_service: DiscordCapabilityService,
    ) -> None:
        self.tool_registry = tool_registry
        self.discord_service = discord_service

    def can_handle(self, query: str) -> bool:
        lowered = query.casefold()
        return "discord" in lowered or bool(re.search(r"(?<!\w)(?:guild|server)\s+\d{15,22}\b", lowered))

    def answer(self, query: str) -> SpecialistResponse:
        clean = str(query or "").strip()
        lowered = clean.casefold()
        action = self._mutation_action(lowered)
        if action:
            return self._prepare_mutation(clean, action)
        if any(term in lowered for term in ("recent", "messages", "conversation", "what did", "catch me up")):
            return self._answer_messages(clean)
        if "channel" in lowered:
            return self._answer_channels(clean)
        if any(term in lowered for term in ("servers", "guilds")):
            return self._answer_guilds()
        return self._answer_account()

    def execute_action_request(self, action_request: dict) -> SpecialistResponse:
        action = str(action_request.get("action") or "")
        if action not in self.WRITE_ACTIONS:
            return self._blocked("DiscordAgent cannot execute that pending Discord action.")
        payload = action_request.get("payload") if isinstance(action_request.get("payload"), dict) else {}
        return self._execute_mutation(action, payload)

    def _answer_account(self) -> SpecialistResponse:
        try:
            result = self.tool_registry.invoke("discord.account", {}, agent_name=self.name)
        except Exception as exc:
            return self._error("DiscordAgent could not check the Discord bot.", exc)
        account = result.get("account") or {}
        if not result.get("connected"):
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="Vellum is not connected to Discord.",
                analysis="Used discord.account.",
                confidence=0.95,
            )
        label = str(account.get("global_name") or account.get("username") or "Vellum bot")
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=f"Vellum is connected to Discord as {label}.",
            analysis="Used discord.account.",
            confidence=1.0,
        )

    def _answer_guilds(self) -> SpecialistResponse:
        try:
            result = self.tool_registry.invoke("discord.guilds", {}, agent_name=self.name)
        except Exception as exc:
            return self._error("DiscordAgent could not read Discord servers.", exc)
        items = list(result.get("items") or [])
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="The Vellum bot is not installed in any visible Discord servers.",
                analysis="Used discord.guilds.",
                confidence=0.9,
            )
        lines = [
            f"[{index}] {item.get('name') or item.get('id')} ({'allowed' if item.get('allowed') else 'not allowlisted'})"
            for index, item in enumerate(items, start=1)
        ]
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="Discord servers visible to Vellum:\n" + "\n".join(lines),
            analysis="Used discord.guilds.",
            confidence=1.0,
        )

    def _answer_messages(self, query: str) -> SpecialistResponse:
        channel_id, channel_error = self._resolve_channel_id(query)
        if not channel_id:
            return self._blocked(channel_error or "DiscordAgent needs the Discord channel ID or #channel name.")
        try:
            result = self.tool_registry.invoke(
                "discord.messages",
                {"channel_id": channel_id, "limit": 20},
                agent_name=self.name,
            )
        except Exception as exc:
            return self._error("DiscordAgent could not read that Discord channel.", exc)
        items = list(result.get("items") or [])
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="No accessible recent messages were found in that Discord channel.",
                analysis="Used discord.messages.",
                confidence=0.9,
            )
        lines: list[str] = []
        sources: list[SpecialistSource] = []
        for index, item in enumerate(items, start=1):
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            username = str(author.get("username") or "Unknown")
            content = str(item.get("content") or "").strip() or "[attachment or embed]"
            lines.append(f"[{index}] {username}: {content}")
            message_id = str(item.get("id") or "")
            sources.append(
                SpecialistSource(
                    kind="api",
                    title=f"Discord message from {username}",
                    path_or_url=f"discord://channels/{channel_id}/messages/{message_id}",
                    snippet=content[:500],
                    captured_at=str(item.get("timestamp") or ""),
                    freshness="recent",
                )
            )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used discord.messages through the scoped Discord bot connector.",
            sources=sources,
            confidence=1.0,
        )

    def _answer_channels(self, query: str) -> SpecialistResponse:
        guild_id = self._labeled_id(query, "server") or self._labeled_id(query, "guild") or self._channel_id(query)
        if not guild_id:
            return self._blocked("DiscordAgent needs the Discord server ID to list channels.")
        try:
            result = self.tool_registry.invoke(
                "discord.channels",
                {"guild_id": guild_id},
                agent_name=self.name,
            )
        except Exception as exc:
            return self._error("DiscordAgent could not read channels for that Discord server.", exc)
        items = list(result.get("items") or [])
        lines = [
            f"[{index}] #{item.get('name') or item.get('id')} ({item.get('id')})"
            f" - {'allowed' if item.get('allowed') else 'not allowlisted'}"
            for index, item in enumerate(items, start=1)
        ]
        return SpecialistResponse(
            agent=self.name,
            status="answered" if lines else "needs_fetch",
            summary="Discord channels:\n" + "\n".join(lines) if lines else "No visible Discord channels were found.",
            analysis="Used discord.channels.",
            confidence=1.0 if lines else 0.8,
        )

    def _prepare_or_send(self, query: str) -> SpecialistResponse:
        return self._prepare_mutation(query, "discord.send_message")

    def _prepare_mutation(self, query: str, action: str) -> SpecialistResponse:
        payload, error = self._mutation_payload(query, action)
        if error:
            return self._blocked(error)
        channel_id = str(payload.get("channel_id") or "")
        preview = str(payload.get("content") or payload.get("name") or payload.get("emoji") or payload.get("message_id") or "")
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary=f"Confirm {action} in Discord channel {channel_id}:\n\n{preview}",
            analysis=f"Prepared {action} and is waiting for explicit confirmation.",
            confidence=0.9,
            action_request={"action": action, "payload": payload, "preview": preview},
        )

    def _execute_send(self, payload: dict, *, standing: bool = False) -> SpecialistResponse:
        return self._execute_mutation("discord.send_message", payload)

    def _execute_mutation(self, action: str, payload: dict) -> SpecialistResponse:
        channel_id = str(payload.get("channel_id") or "").strip()
        try:
            result = self.tool_registry.invoke(
                action,
                {**payload, "confirm": True},
                agent_name=self.name,
            )
        except Exception as exc:
            return self._error("DiscordAgent could not complete that Discord action.", exc)
        message = dict(result.get("message") or {})
        structured = dict(result)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=self._completion_summary(action, channel_id),
            analysis=f"Used {action} after explicit confirmation.",
            confidence=1.0,
            structured_payload={**structured, "message": message, "authorization": "confirmed"},
        )

    @staticmethod
    def _is_send_query(lowered: str) -> bool:
        if "discord" not in lowered and "channel" not in lowered:
            return False
        return bool(re.search(r"\b(?:send|post|reply)\b", lowered))

    @classmethod
    def _mutation_action(cls, lowered: str) -> str:
        if "discord" not in lowered and "channel" not in lowered and "thread" not in lowered:
            return ""
        if re.search(r"\b(?:delete|remove)\b", lowered) and "message" in lowered:
            return "discord.delete_own_message"
        if re.search(r"\b(?:edit|update)\b", lowered) and "message" in lowered:
            return "discord.edit_own_message"
        if re.search(r"\breact(?:ion)?\b", lowered):
            return "discord.add_reaction"
        if re.search(r"\b(?:create|start|open)\b", lowered) and "thread" in lowered:
            return "discord.create_thread"
        if re.search(r"\b(?:send|post)\b", lowered) and "thread" in lowered:
            return "discord.send_thread_message"
        if "reply" in lowered:
            return "discord.reply_message"
        if cls._is_send_query(lowered):
            return "discord.send_message"
        return ""

    def _mutation_payload(self, query: str, action: str) -> tuple[dict, str]:
        channel_id, channel_error = self._resolve_channel_id(query)
        if not channel_id:
            return {}, channel_error or "DiscordAgent needs the target Discord channel ID or #channel name."
        payload: dict[str, str] = {"channel_id": channel_id}
        if action in {"discord.reply_message", "discord.edit_own_message", "discord.delete_own_message", "discord.add_reaction", "discord.create_thread"}:
            message_id = self._labeled_id(query, "message")
            if not message_id:
                return {}, "DiscordAgent needs the target Discord message ID."
            payload["message_id"] = message_id
        if action == "discord.send_thread_message":
            thread_id = self._labeled_id(query, "thread")
            if not thread_id:
                return {}, "DiscordAgent needs the target Discord thread ID."
            payload["thread_id"] = thread_id
        quoted = self._quoted_text(query)
        if action in {"discord.send_message", "discord.reply_message", "discord.edit_own_message", "discord.send_thread_message"}:
            if not quoted:
                return {}, "DiscordAgent needs the exact message text in quotes."
            payload["content"] = quoted
        elif action == "discord.add_reaction":
            if not quoted:
                return {}, "DiscordAgent needs the exact reaction emoji in quotes."
            payload["emoji"] = quoted
        elif action == "discord.create_thread":
            if not quoted:
                return {}, "DiscordAgent needs the exact thread name in quotes."
            payload["name"] = quoted
        return payload, ""

    def _resolve_channel_id(self, query: str) -> tuple[str, str]:
        explicit = self._labeled_id(query, "channel") or self._channel_id(query)
        if explicit:
            return explicit, ""
        match = re.search(r"(?<!\w)#([A-Za-z0-9_-]{1,100})\b", query)
        requested_name = match.group(1).casefold() if match else ""
        matches: list[dict] = []
        try:
            guilds = self.tool_registry.invoke("discord.guilds", {}, agent_name=self.name).get("items") or []
            for guild in guilds:
                if not guild.get("allowed"):
                    continue
                channels = self.tool_registry.invoke(
                    "discord.channels",
                    {"guild_id": str(guild.get("id") or "")},
                    agent_name=self.name,
                ).get("items") or []
                matches.extend(
                    channel for channel in channels
                    if channel.get("allowed") and (not requested_name or str(channel.get("name") or "").casefold() == requested_name)
                )
        except Exception as exc:
            return "", f"DiscordAgent could not resolve the target channel: {type(exc).__name__}."
        if len(matches) == 1:
            return str(matches[0].get("id") or ""), ""
        if not matches:
            return "", "DiscordAgent could not find that channel in the allowlisted Discord servers."
        choices = ", ".join(f"#{item.get('name')} ({item.get('id')})" for item in matches[:5])
        return "", f"DiscordAgent found multiple matching channels. Choose one by ID: {choices}."

    @staticmethod
    def _completion_summary(action: str, channel_id: str) -> str:
        labels = {
            "discord.send_message": "Sent the message",
            "discord.reply_message": "Replied to the message",
            "discord.edit_own_message": "Edited Vellum's message",
            "discord.delete_own_message": "Deleted Vellum's message",
            "discord.add_reaction": "Added the reaction",
            "discord.create_thread": "Created the thread",
            "discord.send_thread_message": "Sent the thread message",
            "discord.send_attachment": "Sent the attachment",
        }
        return f"{labels.get(action, 'Completed the Discord action')} in Discord channel {channel_id}."

    @staticmethod
    def _channel_id(query: str) -> str:
        match = re.search(r"\b(\d{15,22})\b", query)
        return match.group(1) if match else ""

    @staticmethod
    def _labeled_id(query: str, label: str) -> str:
        match = re.search(rf"\b{re.escape(label)}(?:\s+id)?\s*[:#]?\s*(\d{{15,22}})\b", query, flags=re.I)
        return match.group(1) if match else ""

    @staticmethod
    def _quoted_text(query: str) -> str:
        match = re.search(r'["“](.+?)["”]', query, flags=re.S)
        return match.group(1).strip() if match else ""

    def _blocked(self, summary: str) -> SpecialistResponse:
        return SpecialistResponse(agent=self.name, status="blocked", summary=summary, confidence=0.8)

    def _error(self, summary: str, exc: Exception) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="error",
            summary=summary,
            analysis=f"Discord connector failed: {exc.__class__.__name__}",
            confidence=0.2,
        )
