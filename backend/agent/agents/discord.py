from __future__ import annotations

import re

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.discord_service import DiscordCapabilityService
from agent.tools.registry import ToolRegistry


class DiscordAgent:
    name = "DiscordAgent"

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
        if self._is_send_query(lowered):
            return self._prepare_or_send(clean)
        if any(term in lowered for term in ("recent", "messages", "conversation", "what did", "catch me up")):
            return self._answer_messages(clean)
        if any(term in lowered for term in ("servers", "guilds")):
            return self._answer_guilds()
        return self._answer_account()

    def execute_action_request(self, action_request: dict) -> SpecialistResponse:
        if str(action_request.get("action") or "") != "discord.send_message":
            return self._blocked("DiscordAgent cannot execute that pending Discord action.")
        payload = action_request.get("payload") if isinstance(action_request.get("payload"), dict) else {}
        return self._execute_send(payload, standing=False)

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
        channel_id = self._channel_id(query)
        if not channel_id:
            return self._blocked("DiscordAgent needs the Discord channel ID to read recent messages.")
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

    def _prepare_or_send(self, query: str) -> SpecialistResponse:
        channel_id = self._channel_id(query)
        content = self._quoted_text(query)
        if not channel_id:
            return self._blocked("DiscordAgent needs the target Discord channel ID.")
        if not content:
            return self._blocked("DiscordAgent needs the exact message text in quotes.")
        payload = {"channel_id": channel_id, "content": content}
        if self.discord_service.is_autonomous(channel_id):
            return self._execute_send(payload, standing=True)
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary=f'Confirm before I send this to Discord channel {channel_id}:\n\n"{content}"',
            analysis="Prepared discord.send_message and is waiting for explicit confirmation.",
            confidence=0.9,
            action_request={"action": "discord.send_message", "payload": payload, "preview": content},
        )

    def _execute_send(self, payload: dict, *, standing: bool) -> SpecialistResponse:
        channel_id = str(payload.get("channel_id") or "").strip()
        content = str(payload.get("content") or "").strip()
        if standing and not self.discord_service.is_autonomous(channel_id):
            return self._blocked("That Discord channel has no standing authorization.")
        try:
            result = self.tool_registry.invoke(
                "discord.send_message",
                {"channel_id": channel_id, "content": content, "confirm": True},
                agent_name=self.name,
            )
        except Exception as exc:
            return self._error("DiscordAgent could not send that Discord message.", exc)
        message = dict(result.get("message") or {})
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=f"Sent the message to Discord channel {channel_id}.",
            analysis=(
                "Used discord.send_message under standing channel authorization."
                if standing
                else "Used discord.send_message after explicit confirmation."
            ),
            confidence=1.0,
            structured_payload={"message": message, "authorization": "standing" if standing else "confirmed"},
        )

    @staticmethod
    def _is_send_query(lowered: str) -> bool:
        if "discord" not in lowered and "channel" not in lowered:
            return False
        return bool(re.search(r"\b(?:send|post|reply)\b", lowered))

    @staticmethod
    def _channel_id(query: str) -> str:
        match = re.search(r"\b(\d{15,22})\b", query)
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
