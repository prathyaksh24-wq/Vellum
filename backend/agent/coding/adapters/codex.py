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


def codex_sandbox_name(access_mode: AccessMode) -> str:
    return {
        AccessMode.read_only: "read_only",
        AccessMode.workspace_write: "workspace_write",
        AccessMode.full_access: "full_access",
        AccessMode.ask_every_time: "read_only",
    }[access_mode]


def _repo_env_value(name: str) -> str:
    env_path = Path(__file__).resolve().parents[4] / ".env"
    if not env_path.exists():
        return ""
    value = dotenv_values(env_path).get(name)
    return str(value or "").strip()


def _codex_auth_file_exists() -> bool:
    codex_home = os.environ.get("CODEX_HOME")
    candidates = []
    if codex_home:
        candidates.append(Path(codex_home).expanduser() / "auth.json")
    candidates.append(Path.home() / ".codex" / "auth.json")
    return any(path.exists() and path.is_file() for path in candidates)


def codex_auth_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY") or _repo_env_value("OPENAI_API_KEY") or _codex_auth_file_exists())


def codex_runtime_path() -> str | None:
    override = os.environ.get("VELLUM_CODEX_BIN") or _repo_env_value("VELLUM_CODEX_BIN")
    if override:
        path = Path(override).expanduser()
        if path.exists() and path.is_file():
            return str(path.resolve())

    wrapper = shutil.which("codex.cmd") if os.name == "nt" else shutil.which("codex")
    if wrapper:
        wrapper_path = Path(wrapper).resolve()
        if wrapper_path.suffix.casefold() not in {".bat", ".cmd", ".ps1"}:
            return str(wrapper_path)
        package_root = wrapper_path.parent / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai"
        executable_name = "codex.exe" if os.name == "nt" else "codex"
        candidates = sorted(package_root.glob(f"codex-*/vendor/*/bin/{executable_name}"))
        if candidates:
            return str(candidates[-1].resolve())
    return None


def codex_sqlite_home(session_id: str) -> str:
    """Keep Vellum Codex state isolated from the desktop app and other sessions."""
    override = os.environ.get("VELLUM_CODEX_SQLITE_HOME") or _repo_env_value(
        "VELLUM_CODEX_SQLITE_HOME"
    )
    if override:
        root = Path(override).expanduser()
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "Vellum" / "codex-state"
    else:
        state_root = os.environ.get("XDG_STATE_HOME")
        root = (
            Path(state_root).expanduser() / "vellum" / "codex-state"
            if state_root
            else Path.home() / ".local" / "state" / "vellum" / "codex-state"
        )
    safe_session_id = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in session_id
    )
    session_root = root / (safe_session_id or "default")
    session_root.mkdir(parents=True, exist_ok=True)
    return str(session_root.resolve())


def codex_config_overrides() -> tuple[str, ...]:
    """Apply Vellum-specific choices while preserving the user's Codex config."""
    model = os.environ.get("VELLUM_CODEX_MODEL") or _repo_env_value(
        "VELLUM_CODEX_MODEL"
    )
    if not model:
        return ()
    return (f"model={json.dumps(model)}",)


def extract_codex_thread_id(thread: object) -> str | None:
    for attr in ("id", "thread_id", "session_id"):
        value = getattr(thread, attr, None)
        if value:
            return str(value)
    return None


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
    if hasattr(value, "__dict__"):
        return {
            str(key): _jsonable(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _unwrap_thread_item(item: Any) -> Any:
    return getattr(item, "root", item)


def _codex_error_message(error: Any) -> str:
    raw = str(getattr(error, "message", "") or "")
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(payload, dict):
        return raw
    nested = payload.get("error")
    if isinstance(nested, dict) and nested.get("message"):
        return str(nested["message"])
    return raw


@dataclass
class _ActiveCodexTurn:
    codex: Any
    task: asyncio.Task[Any] | None
    handle: Any = None
    initialized: bool = False


class CodexAdapter:
    provider = ProviderName.codex
    sdk_module_name = "openai_codex"

    def __init__(self) -> None:
        self._active_turns: dict[str, _ActiveCodexTurn] = {}

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            access_modes=(AccessMode.read_only, AccessMode.workspace_write, AccessMode.full_access),
            session_resume=True,
            cancellation=True,
            structured_tool_events=True,
            usage_events=True,
            file_change_events=True,
            native_approval_events=False,
        )

    def health(self) -> ProviderHealth:
        available = importlib.util.find_spec(self.sdk_module_name) is not None
        configured = available and codex_auth_configured()
        return ProviderHealth(
            provider=self.provider,
            available=available,
            configured=configured,
            message=(
                "Codex SDK and credentials detected."
                if configured
                else "Codex SDK is installed, but Codex auth is not configured."
                if available
                else "Codex SDK is not installed."
            ),
            capabilities=self.capabilities(),
        )

    async def start_session(self, request: CodingSessionCreate) -> str | None:
        if importlib.util.find_spec(self.sdk_module_name) is None:
            raise CodingAdapterError("Codex SDK is not installed.")
        if not codex_auth_configured():
            raise CodingAdapterError("Codex auth is not configured.")
        return None

    async def run_turn(
        self,
        session: CodingSession,
        prompt: str,
        turn_id: str,
    ) -> AsyncIterator[CodingEvent]:
        if importlib.util.find_spec(self.sdk_module_name) is None:
            raise CodingAdapterError("Codex SDK is not installed.")
        module = importlib.import_module(self.sdk_module_name)
        AsyncCodex = getattr(module, "AsyncCodex")
        Sandbox = getattr(module, "Sandbox")
        sandbox = getattr(Sandbox, codex_sandbox_name(session.access_mode))
        CodexConfig = getattr(module, "CodexConfig", None)
        runtime_path = codex_runtime_path()
        if CodexConfig:
            config_kwargs: dict[str, Any] = {
                "env": {"CODEX_SQLITE_HOME": codex_sqlite_home(session.id)},
                "config_overrides": codex_config_overrides(),
            }
            if runtime_path:
                config_kwargs["codex_bin"] = runtime_path
            codex = AsyncCodex(CodexConfig(**config_kwargs))
        else:
            codex = AsyncCodex()
        active = _ActiveCodexTurn(codex=codex, task=asyncio.current_task())
        self._active_turns[turn_id] = active

        assistant_text = ""
        final_candidate = ""
        completed_status = ""
        completed_error = ""
        try:
            await codex.__aenter__()
            active.initialized = True
            if session.provider_session_id:
                thread = await codex.thread_resume(
                    session.provider_session_id,
                    cwd=session.cwd,
                    sandbox=sandbox,
                )
            else:
                thread = await codex.thread_start(cwd=session.cwd, sandbox=sandbox)
                provider_session_id = extract_codex_thread_id(thread)
                if provider_session_id:
                    yield self._event(
                        session,
                        turn_id,
                        "session.resumed",
                        "Codex session initialized",
                        {"provider_session_id": provider_session_id},
                    )

            handle = await thread.turn(prompt, cwd=session.cwd, sandbox=sandbox)
            active.handle = handle
            async for notification in handle.stream():
                method = str(getattr(notification, "method", ""))
                payload = getattr(notification, "payload", None)
                if method == "item/agentMessage/delta":
                    delta = str(getattr(payload, "delta", "") or "")
                    if delta:
                        assistant_text += delta
                        yield self._event(
                            session,
                            turn_id,
                            "assistant.delta",
                            "Codex assistant update",
                            {"text": delta},
                        )
                    continue
                if method == "thread/tokenUsage/updated":
                    yield self._event(
                        session,
                        turn_id,
                        "usage",
                        "Codex usage updated",
                        {"usage": _jsonable(getattr(payload, "token_usage", None))},
                    )
                    continue
                if method in {
                    "item/commandExecution/outputDelta",
                    "command/exec/outputDelta",
                    "process/outputDelta",
                }:
                    yield self._event(
                        session,
                        turn_id,
                        "command.output",
                        "Codex command output",
                        {
                            "item_id": str(getattr(payload, "item_id", "")),
                            "delta": str(getattr(payload, "delta", "") or ""),
                        },
                    )
                    continue
                if method in {"turn/diff/updated", "item/fileChange/patchUpdated"}:
                    yield self._event(
                        session,
                        turn_id,
                        "file.changed",
                        "Codex workspace diff updated",
                        _jsonable(payload),
                    )
                    continue
                if method in {"item/started", "item/completed"}:
                    item = _unwrap_thread_item(getattr(payload, "item", None))
                    item_name = item.__class__.__name__ if item is not None else ""
                    item_text = str(getattr(item, "text", "") or "")
                    if item_name == "AgentMessageThreadItem" and item_text:
                        final_candidate = item_text
                    item_event = self._item_event(session, turn_id, method, item_name, item)
                    if item_event is not None:
                        yield item_event
                    continue
                if method == "turn/completed":
                    completed_turn = getattr(payload, "turn", None)
                    status = getattr(completed_turn, "status", "")
                    completed_status = str(getattr(status, "value", status) or "")
                    error = getattr(completed_turn, "error", None)
                    completed_error = _codex_error_message(error)
                    continue
                if method in {"warning", "guardianWarning", "configWarning"}:
                    yield self._event(
                        session,
                        turn_id,
                        "provider.warning",
                        "Codex warning",
                        _jsonable(payload),
                    )

            if completed_status == "failed":
                raise CodingAdapterError(completed_error or "Codex turn failed.")
            if not completed_status:
                raise CodingAdapterError("Codex turn ended without a completion event.")
            final_text = final_candidate or assistant_text
            if not final_text:
                raise CodingAdapterError("Codex returned no response.")
            yield self._event(
                session,
                turn_id,
                "assistant.final",
                "Codex final response",
                {"text": final_text},
            )
        finally:
            if self._active_turns.get(turn_id) is active:
                self._active_turns.pop(turn_id, None)
            with suppress(Exception):
                await codex.close()

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        active = self._active_turns.get(turn_id)
        if active is None:
            return
        if active.initialized:
            try:
                if active.handle is not None:
                    await active.handle.interrupt()
            finally:
                await active.codex.close()
                active.initialized = False
            return
        if active.task is not None and active.task is not asyncio.current_task():
            active.task.cancel()

    def _item_event(
        self,
        session: CodingSession,
        turn_id: str,
        method: str,
        item_name: str,
        item: Any,
    ) -> CodingEvent | None:
        phase = "started" if method == "item/started" else "completed"
        payload = {"item": _jsonable(item)}
        if item_name == "CommandExecutionThreadItem":
            return self._event(
                session,
                turn_id,
                f"command.{phase}",
                f"Codex command {phase}",
                payload,
            )
        if item_name == "FileChangeThreadItem":
            return self._event(
                session,
                turn_id,
                "file.changed",
                f"Codex file change {phase}",
                payload,
            )
        if item_name in {
            "CollabAgentToolCallThreadItem",
            "DynamicToolCallThreadItem",
            "ImageGenerationThreadItem",
            "ImageViewThreadItem",
            "McpToolCallThreadItem",
            "WebSearchThreadItem",
        }:
            return self._event(
                session,
                turn_id,
                f"tool.{phase}",
                f"Codex tool {phase}",
                payload,
            )
        return None

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
