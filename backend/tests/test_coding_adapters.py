import asyncio
import importlib.util
from types import SimpleNamespace

from agent.coding.adapters.claude import (
    ClaudeAdapter,
    claude_permission_mode,
    extract_claude_session_id,
    message_result_text,
)
from agent.coding.adapters.codex import CodexAdapter, codex_sandbox_name
from agent.coding.models import AccessMode, CodingSession, CodingSessionCreate, ProviderName, utc_now


def test_adapter_dependency_module_names_are_stable():
    assert CodexAdapter().sdk_module_name == "openai_codex"
    assert ClaudeAdapter().sdk_module_name == "claude_agent_sdk"


def test_codex_health_reports_missing_dependency(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    health = CodexAdapter().health()

    assert health.provider == ProviderName.codex
    assert health.available is False
    assert health.configured is False
    assert health.message == "Codex SDK is not installed."


def test_claude_health_reports_available_dependency(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    health = ClaudeAdapter().health()

    assert health.provider == ProviderName.claude
    assert health.available is True
    assert health.configured is True


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


def test_codex_start_session_resolves_cwd_and_returns_thread_id(monkeypatch, tmp_path):
    calls = []
    find_spec_calls = []
    import_module_calls = []

    class FakeSandbox:
        read_only = "read_only"
        workspace_write = "workspace_write"
        full_access = "full_access"

    class FakeThread:
        thread_id = "codex-thread-from-start"

    class FakeCodex:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def thread_start(self, **kwargs):
            calls.append(kwargs)
            return FakeThread()

    fake_module = SimpleNamespace(AsyncCodex=FakeCodex, Sandbox=FakeSandbox)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: find_spec_calls.append(name) or object())
    monkeypatch.setattr("importlib.import_module", lambda name: import_module_calls.append(name) or fake_module)

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

    assert provider_session_id == "codex-thread-from-start"
    assert find_spec_calls == [adapter.sdk_module_name]
    assert import_module_calls == [adapter.sdk_module_name]
    assert calls == [{"cwd": str(tmp_path.resolve()), "sandbox": "full_access"}]


def test_codex_run_turn_binds_cwd_sandbox_resume_and_provider_session(monkeypatch, tmp_path):
    calls = []

    class FakeSandbox:
        read_only = "read_only"
        workspace_write = "workspace_write"
        full_access = "full_access"

    class FakeResult:
        final_response = "codex done"

    class FakeThread:
        id = "codex-thread-1"

        async def run(self, prompt, cwd=None, sandbox=None):
            calls.append(("run", prompt, cwd, sandbox))
            return FakeResult()

    class FakeCodex:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def thread_start(self, **kwargs):
            calls.append(("start", kwargs))
            return FakeThread()

        async def thread_resume(self, provider_session_id, **kwargs):
            calls.append(("resume", provider_session_id, kwargs))
            return FakeThread()

    fake_module = SimpleNamespace(AsyncCodex=FakeCodex, Sandbox=FakeSandbox)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("importlib.import_module", lambda name: fake_module)

    session = CodingSession(
        id="code_1",
        provider=ProviderName.codex,
        cwd=str(tmp_path),
        access_mode=AccessMode.workspace_write,
        title="Repo",
    )

    events = asyncio.run(_collect(CodexAdapter().run_turn(session, "fix tests", "turn_1")))

    assert [event.type for event in events] == ["session.resumed", "assistant.final"]
    assert events[0].payload == {"provider_session_id": "codex-thread-1"}
    assert events[1].payload == {"text": "codex done"}
    assert calls == [
        ("start", {"cwd": str(tmp_path), "sandbox": "workspace_write"}),
        ("run", "fix tests", str(tmp_path), "workspace_write"),
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

    assert [event.type for event in events] == ["assistant.final"]
    assert calls == [
        ("resume", "existing-thread", {"cwd": str(tmp_path), "sandbox": "read_only"}),
        ("run", "review", str(tmp_path), "read_only"),
    ]


def test_claude_run_turn_binds_cwd_permission_mode_and_resume(monkeypatch, tmp_path):
    options_seen = []
    find_spec_calls = []
    import_module_calls = []

    class FakeOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            options_seen.append(kwargs)

    async def fake_query(prompt, options):
        assert prompt == "fix tests"
        assert options.kwargs == {
            "cwd": str(tmp_path),
            "permission_mode": "acceptEdits",
            "resume": "claude-session-1",
        }
        yield SimpleNamespace(subtype="init", data={"session_id": "claude-session-2"})
        yield SimpleNamespace(content=[SimpleNamespace(text="working "), {"text": "now"}])
        yield SimpleNamespace(session_id="claude-session-3", result="claude done")

    fake_module = SimpleNamespace(query=fake_query, ClaudeAgentOptions=FakeOptions)
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
        "assistant.final",
    ]
    assert events[0].payload == {"provider_session_id": "claude-session-2"}
    assert events[1].payload == {"text": "working now"}
    assert events[2].payload == {"provider_session_id": "claude-session-3"}
    assert events[3].payload == {"text": "claude done"}
    assert find_spec_calls == [adapter.sdk_module_name]
    assert import_module_calls == [adapter.sdk_module_name]
    assert options_seen == [
        {"cwd": str(tmp_path), "permission_mode": "acceptEdits", "resume": "claude-session-1"}
    ]


async def _collect(events):
    return [event async for event in events]
