from __future__ import annotations

from collections.abc import AsyncIterator
import inspect
import importlib
import importlib.util
import os
from pathlib import Path

from dotenv import dotenv_values

from agent.coding.adapters.base import CodingAdapterError
from agent.coding.models import AccessMode, CodingEvent, CodingSession, CodingSessionCreate, ProviderHealth, ProviderName, utc_now


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


class CodexAdapter:
    provider = ProviderName.codex
    sdk_module_name = "openai_codex"

    def health(self) -> ProviderHealth:
        available = importlib.util.find_spec(self.sdk_module_name) is not None
        configured = available and codex_auth_configured()
        return ProviderHealth(
            provider=self.provider,
            available=available,
            configured=configured,
            message=(
                "Codex SDK ready."
                if configured
                else "Codex SDK is installed, but Codex auth is not configured."
                if available
                else "Codex SDK is not installed."
            ),
        )

    async def start_session(self, request: CodingSessionCreate) -> str | None:
        if importlib.util.find_spec(self.sdk_module_name) is None:
            raise CodingAdapterError("Codex SDK is not installed.")
        if not codex_auth_configured():
            raise CodingAdapterError("Codex auth is not configured.")
        return None

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        if importlib.util.find_spec(self.sdk_module_name) is None:
            raise CodingAdapterError("Codex SDK is not installed.")
        module = importlib.import_module(self.sdk_module_name)
        AsyncCodex = getattr(module, "AsyncCodex")
        Sandbox = getattr(module, "Sandbox")
        sandbox = getattr(Sandbox, codex_sandbox_name(session.access_mode))
        async with AsyncCodex() as codex:
            if session.provider_session_id:
                thread = await _maybe_await(
                    codex.thread_resume(
                        session.provider_session_id,
                        cwd=session.cwd,
                        sandbox=sandbox,
                    )
                )
            else:
                thread = await _maybe_await(codex.thread_start(cwd=session.cwd, sandbox=sandbox))
                provider_session_id = extract_codex_thread_id(thread)
                if provider_session_id:
                    yield CodingEvent(
                        id="",
                        session_id=session.id,
                        turn_id=turn_id,
                        provider=self.provider,
                        type="session.resumed",
                        message="Codex session initialized",
                        payload={"provider_session_id": provider_session_id},
                        created_at=utc_now(),
                    )
            result = await _maybe_await(thread.run(prompt, cwd=session.cwd, sandbox=sandbox))
        text = str(getattr(result, "final_response", result) or "")
        yield CodingEvent(
            id="",
            session_id=session.id,
            turn_id=turn_id,
            provider=self.provider,
            type="assistant.final",
            message="Codex final response",
            payload={"text": text},
            created_at=utc_now(),
        )

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        return None


def extract_codex_thread_id(thread: object) -> str | None:
    for attr in ("id", "thread_id", "session_id"):
        value = getattr(thread, attr, None)
        if value:
            return str(value)
    return None


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value
