import asyncio
import importlib.util
import os
from types import SimpleNamespace

from agent.coding.adapters import claude as claude_adapter_module
from agent.coding.adapters import codex as codex_adapter_module
from agent.coding.adapters.base import CodingAdapterError
from agent.coding.adapters.claude import (
    ClaudeAdapter,
    claude_permission_mode,
    claude_auth_configured,
    extract_claude_session_id,
    message_result_text,
)
from agent.coding.adapters.codex import (
    CodexAdapter,
    _codex_error_message,
    codex_auth_configured,
    codex_config_overrides,
    codex_runtime_path,
    codex_sandbox_name,
    codex_sqlite_home,
)
from agent.coding.models import AccessMode, CodingSession, CodingSessionCreate, ProviderName, utc_now


def test_adapter_dependency_module_names_are_stable():
    assert CodexAdapter().sdk_module_name == "openai_codex"
    assert ClaudeAdapter().sdk_module_name == "claude_agent_sdk"


def test_adapter_capabilities_are_explicit_and_provider_specific():
    codex = CodexAdapter().capabilities()
    claude = ClaudeAdapter().capabilities()

    assert codex.access_modes == (
        AccessMode.read_only,
        AccessMode.workspace_write,
        AccessMode.full_access,
    )
    assert AccessMode.ask_every_time not in codex.access_modes
    assert AccessMode.ask_every_time not in claude.access_modes
    assert codex.file_change_events is True
    assert claude.file_change_events is False
    assert codex.native_approval_events is False
    assert claude.native_approval_events is False


def test_codex_health_reports_missing_dependency(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    health = CodexAdapter().health()

    assert health.provider == ProviderName.codex
    assert health.available is False
    assert health.configured is False
    assert health.message == "Codex SDK is not installed."


def test_claude_health_reports_available_dependency(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        os,
        "environ",
        {"ANTHROPIC_API_KEY": "test-key"},
    )

    health = ClaudeAdapter().health()

    assert health.provider == ProviderName.claude
    assert health.available is True
    assert health.configured is True


def test_claude_health_requires_auth_configuration(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr("agent.coding.adapters.claude._claude_cli_auth_configured", lambda: False)

    health = ClaudeAdapter().health()

    assert health.available is True
    assert health.configured is False
    assert "local Claude login" in health.message


def test_claude_auth_configuration_accepts_supported_provider_env(monkeypatch):
    monkeypatch.setattr(os, "environ", {"CLAUDE_CODE_USE_VERTEX": "1"})

    assert claude_auth_configured() is True


def test_claude_auth_configuration_accepts_local_cli_login(monkeypatch):
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr("agent.coding.adapters.claude._repo_env_value", lambda name: "")
    monkeypatch.setattr("agent.coding.adapters.claude.shutil.which", lambda name: "claude.exe")
    monkeypatch.setattr(
        "agent.coding.adapters.claude.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='{"loggedIn": true}'),
    )
    monkeypatch.setattr("agent.coding.adapters.claude.time.monotonic", lambda: 100.0)
    monkeypatch.setattr(claude_adapter_module, "_CLAUDE_AUTH_CACHE", (0.0, False))

    assert claude_auth_configured() is True


def test_codex_health_reports_sdk_installed_but_unconfigured(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("agent.coding.adapters.codex.codex_auth_configured", lambda: False)

    health = CodexAdapter().health()

    assert health.available is True
    assert health.configured is False
    assert "auth" in health.message.lower()


def test_codex_auth_configuration_accepts_api_key(monkeypatch):
    monkeypatch.setattr(os, "environ", {"OPENAI_API_KEY": "test-key"})

    assert codex_auth_configured() is True


def test_codex_runtime_prefers_native_binary_behind_npm_wrapper(monkeypatch, tmp_path):
    wrapper = tmp_path / "bin" / "codex.cmd"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("@echo off", encoding="utf-8")
    native = (
        wrapper.parent
        / "node_modules"
        / "@openai"
        / "codex"
        / "node_modules"
        / "@openai"
        / "codex-win32-x64"
        / "vendor"
        / "x86_64-pc-windows-msvc"
        / "bin"
        / "codex.exe"
    )
    native.parent.mkdir(parents=True)
    native.write_bytes(b"")
    monkeypatch.setattr(codex_adapter_module.shutil, "which", lambda name: str(wrapper))
    monkeypatch.setattr(codex_adapter_module, "_repo_env_value", lambda name: "")
    monkeypatch.delenv("VELLUM_CODEX_BIN", raising=False)

    assert codex_runtime_path() == str(native.resolve())


def test_codex_sqlite_home_is_isolated_per_vellum_session(monkeypatch, tmp_path):
    monkeypatch.setenv("VELLUM_CODEX_SQLITE_HOME", str(tmp_path / "codex-state"))

    first = codex_sqlite_home("code/session-1")
    second = codex_sqlite_home("code-session-2")

    assert first == str((tmp_path / "codex-state" / "code_session-1").resolve())
    assert second == str((tmp_path / "codex-state" / "code-session-2").resolve())
    assert first != second
    assert os.path.isdir(first)
    assert os.path.isdir(second)


def test_codex_config_overrides_only_sets_an_explicit_vellum_model(monkeypatch):
    monkeypatch.setenv("VELLUM_CODEX_MODEL", "gpt-test")

    assert codex_config_overrides() == ('model="gpt-test"',)

    monkeypatch.delenv("VELLUM_CODEX_MODEL")
    monkeypatch.setattr(codex_adapter_module, "_repo_env_value", lambda _name: "")
    assert codex_config_overrides() == ()


def test_codex_error_message_extracts_nested_provider_detail():
    error = SimpleNamespace(
        message='{"type":"error","error":{"message":"Upgrade Codex to use this model."}}'
    )

    assert _codex_error_message(error) == "Upgrade Codex to use this model."


def test_codex_access_mode_mapping_is_explicit():
    assert codex_sandbox_name(AccessMode.read_only) == "read_only"
    assert codex_sandbox_name(AccessMode.workspace_write) == "workspace_write"
    assert codex_sandbox_name(AccessMode.full_access) == "full_access"
    assert codex_sandbox_name(AccessMode.ask_every_time) == "read_only"


def test_claude_permission_mode_mapping_is_explicit():
    assert claude_permission_mode(AccessMode.read_only) == "plan"
    assert claude_permission_mode(AccessMode.workspace_write) == "acceptEdits"
    assert claude_permission_mode(AccessMode.full_access) == "bypassPermissions"
    assert claude_permission_mode(AccessMode.ask_every_time) == "default"


def test_claude_session_id_extraction_from_init_message():
    class InitMessage:
        subtype = "init"
        data = {"session_id": "claude-session-1"}

    assert extract_claude_session_id(InitMessage()) == "claude-session-1"


def test_claude_session_id_extraction_from_result_message():
    assert extract_claude_session_id(SimpleNamespace(session_id="claude-session-2")) == "claude-session-2"


def test_claude_message_text_extracts_content_blocks_without_repr():
    message = SimpleNamespace(content=[SimpleNamespace(text="Hello "), {"text": "there."}])

    assert message_result_text(message) == "Hello there."


def test_codex_start_session_validates_dependency_without_prestarting_thread(monkeypatch, tmp_path):
    find_spec_calls = []
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: find_spec_calls.append(name) or object())
    monkeypatch.setattr("agent.coding.adapters.codex.codex_auth_configured", lambda: True)

    adapter = CodexAdapter()
    provider_session_id = asyncio.run(
        adapter.start_session(
            CodingSessionCreate(
                provider=ProviderName.codex,
                cwd=str(tmp_path / ".." / tmp_path.name),
                access_mode=AccessMode.full_access,
            )
        )
    )

    assert provider_session_id is None
    assert find_spec_calls == [adapter.sdk_module_name]


def test_codex_run_turn_binds_cwd_sandbox_resume_and_provider_session(monkeypatch, tmp_path):
    calls = []
    configs = []

    class FakeSandbox:
        read_only = "read_only"
        workspace_write = "workspace_write"
        full_access = "full_access"

    class FakeTurn:
        id = "codex-turn-1"

        async def stream(self):
            yield SimpleNamespace(
                method="item/agentMessage/delta",
                payload=SimpleNamespace(delta="codex done"),
            )
            yield SimpleNamespace(
                method="thread/tokenUsage/updated",
                payload=SimpleNamespace(token_usage={"total_tokens": 12}),
            )
            yield SimpleNamespace(
                method="turn/completed",
                payload=SimpleNamespace(turn=SimpleNamespace(status="completed", error=None)),
            )

        async def interrupt(self):
            calls.append(("interrupt", self.id))

    class FakeThread:
        id = "codex-thread-1"

        async def turn(self, prompt, cwd=None, sandbox=None):
            calls.append(("turn", prompt, cwd, sandbox))
            return FakeTurn()

    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            configs.append(kwargs)

    class FakeCodex:
        def __init__(self, config=None):
            self.config = config

        async def __aenter__(self):
            calls.append(("connect",))
            return self

        async def close(self):
            calls.append(("close",))

        async def thread_start(self, **kwargs):
            calls.append(("start", kwargs))
            return FakeThread()

        async def thread_resume(self, provider_session_id, **kwargs):
            calls.append(("resume", provider_session_id, kwargs))
            return FakeThread()

    fake_module = SimpleNamespace(
        AsyncCodex=FakeCodex, Sandbox=FakeSandbox, CodexConfig=FakeConfig
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("importlib.import_module", lambda name: fake_module)
    monkeypatch.setattr(codex_adapter_module, "codex_runtime_path", lambda: None)
    monkeypatch.setenv("VELLUM_CODEX_SQLITE_HOME", str(tmp_path / "codex-state"))
    monkeypatch.setenv("VELLUM_CODEX_MODEL", "gpt-test")

    session = CodingSession(
        id="code_1",
        provider=ProviderName.codex,
        cwd=str(tmp_path),
        access_mode=AccessMode.workspace_write,
        title="Repo",
    )

    events = asyncio.run(_collect(CodexAdapter().run_turn(session, "fix tests", "turn_1")))

    assert [event.type for event in events] == [
        "session.resumed",
        "assistant.delta",
        "usage",
        "assistant.final",
    ]
    assert events[0].payload == {"provider_session_id": "codex-thread-1"}
    assert events[1].payload == {"text": "codex done"}
    assert events[2].payload == {"usage": {"total_tokens": 12}}
    assert events[3].payload == {"text": "codex done"}
    assert calls == [
        ("connect",),
        ("start", {"cwd": str(tmp_path), "sandbox": "workspace_write"}),
        ("turn", "fix tests", str(tmp_path), "workspace_write"),
        ("close",),
    ]
    assert configs == [
        {
            "env": {
                "CODEX_SQLITE_HOME": str(
                    (tmp_path / "codex-state" / "code_1").resolve()
                )
            },
            "config_overrides": ('model="gpt-test"',),
        }
    ]

    resumed_session = CodingSession(
        id="code_1",
        provider=ProviderName.codex,
        cwd=str(tmp_path),
        access_mode=AccessMode.read_only,
        title="Repo",
        provider_session_id="existing-thread",
    )
    calls.clear()

    events = asyncio.run(_collect(CodexAdapter().run_turn(resumed_session, "review", "turn_2")))

    assert [event.type for event in events] == ["assistant.delta", "usage", "assistant.final"]
    assert calls == [
        ("connect",),
        ("resume", "existing-thread", {"cwd": str(tmp_path), "sandbox": "read_only"}),
        ("turn", "review", str(tmp_path), "read_only"),
        ("close",),
    ]
    assert configs[-1] == configs[0]


def test_claude_run_turn_binds_cwd_permission_mode_and_resume(monkeypatch, tmp_path):
    options_seen = []
    find_spec_calls = []
    import_module_calls = []
    calls = []

    class FakeOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            options_seen.append(kwargs)

    class FakeClient:
        def __init__(self, *, options):
            self.options = options

        async def connect(self):
            calls.append(("connect",))

        async def query(self, prompt):
            calls.append(("query", prompt))

        async def receive_response(self):
            yield SimpleNamespace(subtype="init", data={"session_id": "claude-session-2"})
            yield SimpleNamespace(content=[SimpleNamespace(text="working "), {"text": "now"}])
            yield SimpleNamespace(
                session_id="claude-session-3",
                result="claude done",
                usage={"input_tokens": 10},
                total_cost_usd=0.01,
                model_usage=None,
                duration_ms=100,
                num_turns=1,
                is_error=False,
            )

        async def interrupt(self):
            calls.append(("interrupt",))

        async def disconnect(self):
            calls.append(("disconnect",))

    fake_module = SimpleNamespace(ClaudeSDKClient=FakeClient, ClaudeAgentOptions=FakeOptions)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: find_spec_calls.append(name) or object())
    monkeypatch.setattr("importlib.import_module", lambda name: import_module_calls.append(name) or fake_module)

    session = CodingSession(
        id="code_1",
        provider=ProviderName.claude,
        cwd=str(tmp_path),
        access_mode=AccessMode.workspace_write,
        title="Repo",
        provider_session_id="claude-session-1",
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    adapter = ClaudeAdapter()
    events = asyncio.run(_collect(adapter.run_turn(session, "fix tests", "turn_1")))

    assert [event.type for event in events] == [
        "session.resumed",
        "assistant.delta",
        "session.resumed",
        "usage",
        "assistant.final",
    ]
    assert events[0].payload == {"provider_session_id": "claude-session-2"}
    assert events[1].payload == {"text": "working now"}
    assert events[2].payload == {"provider_session_id": "claude-session-3"}
    assert events[3].payload == {
        "usage": {"input_tokens": 10},
        "model_usage": None,
        "total_cost_usd": 0.01,
        "duration_ms": 100,
        "num_turns": 1,
    }
    assert events[4].payload == {"text": "claude done"}
    assert find_spec_calls == [adapter.sdk_module_name]
    assert import_module_calls == [adapter.sdk_module_name]
    assert options_seen == [
        {
            "cwd": str(tmp_path),
            "permission_mode": "acceptEdits",
            "resume": "claude-session-1",
            "include_partial_messages": True,
        }
    ]
    assert calls == [("connect",), ("query", "fix tests"), ("disconnect",)]


def test_codex_stop_interrupts_active_sdk_turn_and_closes_runtime(monkeypatch, tmp_path):
    calls = []

    class FakeSandbox:
        read_only = "read_only"
        workspace_write = "workspace_write"
        full_access = "full_access"

    class FakeTurn:
        async def stream(self):
            yield SimpleNamespace(
                method="item/agentMessage/delta",
                payload=SimpleNamespace(delta="working"),
            )
            yield SimpleNamespace(
                method="turn/completed",
                payload=SimpleNamespace(turn=SimpleNamespace(status="completed", error=None)),
            )

        async def interrupt(self):
            calls.append("interrupt")

    class FakeThread:
        async def turn(self, prompt, cwd=None, sandbox=None):
            return FakeTurn()

    class FakeCodex:
        async def __aenter__(self):
            return self

        async def thread_resume(self, provider_session_id, **kwargs):
            return FakeThread()

        async def close(self):
            calls.append("close")

    fake_module = SimpleNamespace(AsyncCodex=FakeCodex, Sandbox=FakeSandbox)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("importlib.import_module", lambda name: fake_module)
    session = CodingSession(
        id="code_1",
        provider=ProviderName.codex,
        cwd=str(tmp_path),
        access_mode=AccessMode.read_only,
        title="Repo",
        provider_session_id="thread-1",
    )
    adapter = CodexAdapter()

    async def run_stop():
        stream = adapter.run_turn(session, "inspect", "turn_1")
        first = await anext(stream)
        await adapter.stop_turn(session, "turn_1")
        await stream.aclose()
        return first

    first = asyncio.run(run_stop())

    assert first.type == "assistant.delta"
    assert calls[0:2] == ["interrupt", "close"]


def test_codex_stop_closes_runtime_when_interrupt_fails(tmp_path):
    calls = []

    class FailingHandle:
        async def interrupt(self):
            calls.append("interrupt")
            raise RuntimeError("interrupt failed")

    class FakeCodex:
        async def close(self):
            calls.append("close")

    session = CodingSession(
        id="code_1",
        provider=ProviderName.codex,
        cwd=str(tmp_path),
        access_mode=AccessMode.read_only,
        title="Repo",
    )
    adapter = CodexAdapter()
    adapter._active_turns["turn_1"] = SimpleNamespace(
        handle=FailingHandle(), codex=FakeCodex(), initialized=True, task=None
    )

    try:
        asyncio.run(adapter.stop_turn(session, "turn_1"))
    except RuntimeError as exc:
        assert str(exc) == "interrupt failed"
    else:
        raise AssertionError("expected interrupt failure")

    assert calls == ["interrupt", "close"]


def test_claude_stop_interrupts_active_sdk_turn_and_disconnects(monkeypatch, tmp_path):
    calls = []

    class FakeOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeClient:
        def __init__(self, *, options):
            self.options = options

        async def connect(self):
            calls.append("connect")

        async def query(self, prompt):
            calls.append("query")

        async def receive_response(self):
            yield SimpleNamespace(subtype="init", data={"session_id": "claude-session-2"})
            yield SimpleNamespace(result="done", session_id="claude-session-2", is_error=False)

        async def interrupt(self):
            calls.append("interrupt")

        async def disconnect(self):
            calls.append("disconnect")

    fake_module = SimpleNamespace(ClaudeSDKClient=FakeClient, ClaudeAgentOptions=FakeOptions)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("importlib.import_module", lambda name: fake_module)
    session = CodingSession(
        id="code_1",
        provider=ProviderName.claude,
        cwd=str(tmp_path),
        access_mode=AccessMode.read_only,
        title="Repo",
    )
    adapter = ClaudeAdapter()

    async def run_stop():
        stream = adapter.run_turn(session, "inspect", "turn_1")
        first = await anext(stream)
        await adapter.stop_turn(session, "turn_1")
        await stream.aclose()
        return first

    first = asyncio.run(run_stop())

    assert first.type == "session.resumed"
    assert calls[:4] == ["connect", "query", "interrupt", "disconnect"]


def test_claude_stop_disconnects_when_interrupt_fails(tmp_path):
    calls = []

    class FakeClient:
        async def interrupt(self):
            calls.append("interrupt")
            raise RuntimeError("interrupt failed")

        async def disconnect(self):
            calls.append("disconnect")

    session = CodingSession(
        id="code_1",
        provider=ProviderName.claude,
        cwd=str(tmp_path),
        access_mode=AccessMode.read_only,
        title="Repo",
    )
    adapter = ClaudeAdapter()
    adapter._active_turns["turn_1"] = SimpleNamespace(client=FakeClient(), connected=True, task=None)

    try:
        asyncio.run(adapter.stop_turn(session, "turn_1"))
    except RuntimeError as exc:
        assert str(exc) == "interrupt failed"
    else:
        raise AssertionError("expected interrupt failure")

    assert calls == ["interrupt", "disconnect"]


def test_claude_error_result_preserves_provider_detail(monkeypatch, tmp_path):
    class FakeOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeClient:
        def __init__(self, *, options):
            self.options = options

        async def connect(self):
            return None

        async def query(self, prompt):
            return None

        async def receive_response(self):
            yield SimpleNamespace(
                result="OAuth access token has expired.",
                subtype="success",
                is_error=True,
                errors=None,
                session_id="claude-session-1",
            )

        async def disconnect(self):
            return None

    fake_module = SimpleNamespace(ClaudeSDKClient=FakeClient, ClaudeAgentOptions=FakeOptions)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("importlib.import_module", lambda name: fake_module)
    session = CodingSession(
        id="code_1",
        provider=ProviderName.claude,
        cwd=str(tmp_path),
        access_mode=AccessMode.read_only,
        title="Repo",
    )

    try:
        asyncio.run(_collect(ClaudeAdapter().run_turn(session, "inspect", "turn_1")))
    except CodingAdapterError as exc:
        assert str(exc) == "OAuth access token has expired."
    else:
        raise AssertionError("expected Claude provider error")


async def _collect(events):
    return [event async for event in events]
