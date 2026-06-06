from __future__ import annotations

from collections.abc import AsyncIterator
import importlib
import importlib.util

from agent.coding.adapters.base import CodingAdapterError
from agent.coding.models import AccessMode, CodingEvent, CodingSession, CodingSessionCreate, ProviderHealth, ProviderName, utc_now


def extract_claude_session_id(message: object) -> str | None:
    subtype = getattr(message, "subtype", None)
    data = getattr(message, "data", None)
    if subtype == "init" and isinstance(data, dict):
        value = data.get("session_id")
        return str(value) if value else None
    value = getattr(message, "session_id", None)
    if value:
        return str(value)
    return None


def message_result_text(message: object) -> str:
    result = getattr(message, "result", None)
    if result:
        return str(result)
    return message_content_text(message)


def message_content_text(message: object) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                parts.append(str(text))
        return "".join(parts)
    if content:
        return str(content)
    return ""


def claude_permission_mode(access_mode: AccessMode) -> str:
    return {
        AccessMode.read_only: "plan",
        AccessMode.workspace_write: "acceptEdits",
        AccessMode.full_access: "bypassPermissions",
        AccessMode.ask_every_time: "default",
    }[access_mode]


class ClaudeAdapter:
    provider = ProviderName.claude

    def health(self) -> ProviderHealth:
        available = importlib.util.find_spec("claude_agent_sdk") is not None
        return ProviderHealth(
            provider=self.provider,
            available=available,
            configured=available,
            message="Claude Agent SDK ready." if available else "Claude Agent SDK is not installed.",
        )

    async def start_session(self, request: CodingSessionCreate) -> str | None:
        return None

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        if importlib.util.find_spec("claude_agent_sdk") is None:
            raise CodingAdapterError("Claude Agent SDK is not installed.")
        module = importlib.import_module("claude_agent_sdk")
        query = getattr(module, "query")
        ClaudeAgentOptions = getattr(module, "ClaudeAgentOptions")
        options = ClaudeAgentOptions(
            cwd=session.cwd,
            permission_mode=claude_permission_mode(session.access_mode),
            resume=session.provider_session_id,
        )
        final_text = ""
        seen_session_ids: set[str] = set()
        async for message in query(prompt=prompt, options=options):
            session_id = extract_claude_session_id(message)
            if session_id and session_id not in seen_session_ids:
                seen_session_ids.add(session_id)
                yield CodingEvent(
                    id="",
                    session_id=session.id,
                    turn_id=turn_id,
                    provider=self.provider,
                    type="session.resumed",
                    message="Claude session initialized",
                    payload={"provider_session_id": session_id},
                    created_at=utc_now(),
                )
            result = getattr(message, "result", None)
            if result:
                final_text = str(result)
                yield CodingEvent(
                    id="",
                    session_id=session.id,
                    turn_id=turn_id,
                    provider=self.provider,
                    type="assistant.final",
                    message="Claude final response",
                    payload={"text": final_text},
                    created_at=utc_now(),
                )
                continue
            delta = message_content_text(message)
            if delta:
                yield CodingEvent(
                    id="",
                    session_id=session.id,
                    turn_id=turn_id,
                    provider=self.provider,
                    type="assistant.delta",
                    message="Claude assistant update",
                    payload={"text": delta},
                    created_at=utc_now(),
                )
        if not final_text:
            raise CodingAdapterError("Claude returned no response.")

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        return None
