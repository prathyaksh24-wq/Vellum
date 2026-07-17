from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import asdict, dataclass, is_dataclass
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any

from dotenv import dotenv_values

from agent.coding.adapters.base import CodingAdapterError
from agent.coding.models import (
    AccessMode,
    CodingEvent,
    CodingSession,
    CodingSessionCreate,
    ProviderCapabilities,
    ProviderHealth,
    ProviderName,
    utc_now,
)


_CLAUDE_PROVIDER_ENV_FLAGS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
_CLAUDE_AUTH_CACHE_TTL_SECONDS = 30.0
_CLAUDE_AUTH_CACHE_LOCK = threading.Lock()
_CLAUDE_AUTH_CACHE: tuple[float, bool] = (0.0, False)


def _repo_env_value(name: str) -> str:
    env_path = Path(__file__).resolve().parents[4] / ".env"
    if not env_path.exists():
        return ""
    value = dotenv_values(env_path).get(name)
    return str(value or "").strip()


def _env_or_repo_env_present(name: str) -> bool:
    return bool(os.environ.get(name) or _repo_env_value(name))


def _claude_cli_auth_configured() -> bool:
    global _CLAUDE_AUTH_CACHE

    now = time.monotonic()
    with _CLAUDE_AUTH_CACHE_LOCK:
        cached_at, cached_value = _CLAUDE_AUTH_CACHE
        if now - cached_at < _CLAUDE_AUTH_CACHE_TTL_SECONDS:
            return cached_value

    executable = shutil.which("claude")
    configured = False
    if executable:
        try:
            completed = subprocess.run(
                [executable, "auth", "status"],
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if completed.returncode == 0:
                status = json.loads(completed.stdout or "{}")
                configured = status.get("loggedIn") is True
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            configured = False

    with _CLAUDE_AUTH_CACHE_LOCK:
        _CLAUDE_AUTH_CACHE = (now, configured)
    return configured


def claude_auth_configured() -> bool:
    if _env_or_repo_env_present("ANTHROPIC_API_KEY"):
        return True
    if any(_env_or_repo_env_present(name) for name in _CLAUDE_PROVIDER_ENV_FLAGS):
        return True
    return _claude_cli_auth_configured()


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


def _stream_event_text(message: object) -> str:
    event = getattr(message, "event", None)
    if not isinstance(event, dict) or event.get("type") != "content_block_delta":
        return ""
    delta = event.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return ""
    return str(delta.get("text") or "")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value):
        return _jsonable(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", by_alias=True)
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return _jsonable(enum_value)
    return str(value)


@dataclass
class _ActiveClaudeTurn:
    client: Any
    task: asyncio.Task[Any] | None
    connected: bool = False


class ClaudeAdapter:
    provider = ProviderName.claude
    sdk_module_name = "claude_agent_sdk"

    def __init__(self) -> None:
        self._active_turns: dict[str, _ActiveClaudeTurn] = {}

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            access_modes=(
                AccessMode.read_only,
                AccessMode.workspace_write,
                AccessMode.full_access,
                AccessMode.ask_every_time,
            ),
            session_resume=True,
            cancellation=True,
            structured_tool_events=True,
            usage_events=True,
            file_change_events=False,
            native_approval_events=False,
        )

    def health(self) -> ProviderHealth:
        available = importlib.util.find_spec(self.sdk_module_name) is not None
        configured = available and claude_auth_configured()
        return ProviderHealth(
            provider=self.provider,
            available=available,
            configured=configured,
            message=(
                "Claude Agent SDK and credentials detected."
                if configured
                else "Claude Agent SDK is installed, but no API, cloud-provider, or local Claude login was found."
                if available
                else "Claude Agent SDK is not installed."
            ),
            capabilities=self.capabilities(),
        )

    async def start_session(self, request: CodingSessionCreate) -> str | None:
        if importlib.util.find_spec(self.sdk_module_name) is None:
            raise CodingAdapterError("Claude Agent SDK is not installed.")
        if not claude_auth_configured():
            raise CodingAdapterError("Claude auth is not configured.")
        return None

    async def run_turn(
        self,
        session: CodingSession,
        prompt: str,
        turn_id: str,
    ) -> AsyncIterator[CodingEvent]:
        if importlib.util.find_spec(self.sdk_module_name) is None:
            raise CodingAdapterError("Claude Agent SDK is not installed.")
        module = importlib.import_module(self.sdk_module_name)
        ClaudeSDKClient = getattr(module, "ClaudeSDKClient")
        ClaudeAgentOptions = getattr(module, "ClaudeAgentOptions")
        options = ClaudeAgentOptions(
            cwd=session.cwd,
            permission_mode=claude_permission_mode(session.access_mode),
            resume=session.provider_session_id,
            include_partial_messages=True,
        )
        client = ClaudeSDKClient(options=options)
        active = _ActiveClaudeTurn(client=client, task=asyncio.current_task())
        self._active_turns[turn_id] = active

        final_text = ""
        assistant_text = ""
        partial_text = ""
        final_emitted = False
        seen_session_ids = {session.provider_session_id} if session.provider_session_id else set()
        try:
            await client.connect()
            active.connected = True
            await client.query(prompt)
            async for message in client.receive_response():
                provider_session_id = extract_claude_session_id(message)
                if provider_session_id and provider_session_id not in seen_session_ids:
                    seen_session_ids.add(provider_session_id)
                    yield self._event(
                        session,
                        turn_id,
                        "session.resumed",
                        "Claude session initialized",
                        {"provider_session_id": provider_session_id},
                    )

                delta = _stream_event_text(message)
                if delta:
                    partial_text += delta
                    yield self._event(
                        session,
                        turn_id,
                        "assistant.delta",
                        "Claude assistant update",
                        {"text": delta},
                    )

                content = getattr(message, "content", None)
                message_text = message_content_text(message)
                if message_text:
                    assistant_text += message_text
                    if not partial_text:
                        yield self._event(
                            session,
                            turn_id,
                            "assistant.delta",
                            "Claude assistant update",
                            {"text": message_text},
                        )
                if isinstance(content, list):
                    for block in content:
                        block_name = block.__class__.__name__
                        if block_name == "ToolUseBlock":
                            yield self._event(
                                session,
                                turn_id,
                                "tool.started",
                                f"Claude started {getattr(block, 'name', 'tool')}",
                                {
                                    "tool_call_id": str(getattr(block, "id", "")),
                                    "name": str(getattr(block, "name", "tool")),
                                    "input": _jsonable(getattr(block, "input", {})),
                                },
                            )
                        elif block_name == "ToolResultBlock":
                            yield self._event(
                                session,
                                turn_id,
                                "tool.completed",
                                "Claude tool completed",
                                {
                                    "tool_call_id": str(getattr(block, "tool_use_id", "")),
                                    "content": _jsonable(getattr(block, "content", None)),
                                    "is_error": bool(getattr(block, "is_error", False)),
                                },
                            )

                result = getattr(message, "result", None)
                is_result = result is not None or message.__class__.__name__ == "ResultMessage"
                if is_result:
                    if getattr(message, "is_error", False):
                        errors = getattr(message, "errors", None) or []
                        detail = (
                            "; ".join(str(item) for item in errors)
                            or str(result or "")
                            or str(getattr(message, "subtype", "Claude turn failed"))
                        )
                        raise CodingAdapterError(detail)
                    usage = getattr(message, "usage", None)
                    total_cost_usd = getattr(message, "total_cost_usd", None)
                    if usage is not None or total_cost_usd is not None:
                        yield self._event(
                            session,
                            turn_id,
                            "usage",
                            "Claude usage updated",
                            {
                                "usage": _jsonable(usage),
                                "model_usage": _jsonable(getattr(message, "model_usage", None)),
                                "total_cost_usd": total_cost_usd,
                                "duration_ms": getattr(message, "duration_ms", None),
                                "num_turns": getattr(message, "num_turns", None),
                            },
                        )
                    final_text = str(result or assistant_text or partial_text)
                    yield self._event(
                        session,
                        turn_id,
                        "assistant.final",
                        "Claude final response",
                        {"text": final_text},
                    )
                    final_emitted = True
            if not final_emitted:
                final_text = assistant_text or partial_text
                if not final_text:
                    raise CodingAdapterError("Claude returned no response.")
                yield self._event(
                    session,
                    turn_id,
                    "assistant.final",
                    "Claude final response",
                    {"text": final_text},
                )
        finally:
            if self._active_turns.get(turn_id) is active:
                self._active_turns.pop(turn_id, None)
            with suppress(Exception):
                await client.disconnect()

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        active = self._active_turns.get(turn_id)
        if active is None:
            return
        if active.connected:
            try:
                await active.client.interrupt()
            finally:
                await active.client.disconnect()
                active.connected = False
            return
        if active.task is not None and active.task is not asyncio.current_task():
            active.task.cancel()

    def _event(
        self,
        session: CodingSession,
        turn_id: str,
        event_type: str,
        message: str,
        payload: dict[str, Any],
    ) -> CodingEvent:
        return CodingEvent(
            id="",
            session_id=session.id,
            turn_id=turn_id,
            provider=self.provider,
            type=event_type,
            message=message,
            payload=payload,
            created_at=utc_now(),
        )
