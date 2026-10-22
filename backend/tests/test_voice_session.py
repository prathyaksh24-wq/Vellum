import asyncio
import json
from types import SimpleNamespace

import pytest
import anyio

from agent.voice.session import LfmVoiceSession, VoiceSessionError


class FakeInput:
    def __init__(self):
        self.payload = b""

    def write(self, data):
        self.payload += data

    async def drain(self):
        return None


class FakeOutput:
    def __init__(self, process, mode):
        self.process = process
        self.mode = mode
        self.count = 0

    async def readline(self):
        self.count += 1
        if self.mode == "timeout":
            await asyncio.sleep(1)
        if self.mode == "eof":
            return b""
        request = json.loads(self.process.stdin.payload)
        payload = {"request_id":request["request_id"]}
        if self.mode == "error":
            payload.update(type="error", message="GPU unavailable.")
        elif self.count == 1:
            payload.update(type="text_delta", delta="Hello")
        else:
            payload.update(type="completed", text="Hello")
        return (json.dumps(payload) + "\n").encode()


class FakeProcess:
    returncode = None
    pid = 123
    def __init__(self, mode="complete"):
        self.stdin = FakeInput()
        self.stdout = FakeOutput(self,mode)
        self.stderr = None
        self.terminated = False

    def terminate(self):
        self.terminated = True
        self.returncode = -1

    async def wait(self):
        return self.returncode


def session_with_worker(monkeypatch, mode="complete"):
    settings = SimpleNamespace(voice_enabled=True,voice_turn_timeout_seconds=0.02)
    session = LfmVoiceSession(settings)
    process = FakeProcess(mode)
    monkeypatch.setattr("agent.voice.session.subprocess.run", lambda *args, **kwargs: process.terminate())
    monkeypatch.setattr(LfmVoiceSession,"installed",property(lambda self:True))
    async def ensure():
        session._process = process
        session._ready = True
    monkeypatch.setattr(session,"_ensure_worker",ensure)
    session._process = process
    session._ready = True
    return session, process


@pytest.mark.asyncio
async def test_worker_turn_uses_thread_identity_and_completes(monkeypatch):
    session, process = session_with_worker(monkeypatch)
    events = [event async for event in session.stream_turn(b"audio",session_id="voice-thread")]
    assert [event.type for event in events] == ["text_delta","completed"]
    request = json.loads(process.stdin.payload)
    assert request["session_id"] == "voice-thread"
    assert request["audio_b64"] == "YXVkaW8="
    assert session._state == "ready"
    assert not process.terminated
    await session.close()
    assert process.terminated


@pytest.mark.asyncio
async def test_worker_receives_bounded_per_turn_response_preferences(monkeypatch):
    session, process = session_with_worker(monkeypatch)
    _ = [event async for event in session.stream_turn(b'audio', session_id='prefs', response_preferences='Be concise. ' * 1200)]
    request = json.loads(process.stdin.payload)
    assert request['response_preferences'].startswith('Be concise.')
    assert len(request['response_preferences']) == 10000
    await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,message",[("timeout","timed out"),("eof","stopped unexpectedly"),("error","GPU unavailable")])
async def test_worker_failures_stop_process_and_allow_restart(monkeypatch, mode, message):
    session, process = session_with_worker(monkeypatch,mode)
    with pytest.raises(VoiceSessionError,match=message):
        async for _event in session.stream_turn(b"audio",session_id="voice-thread"):
            pass
    assert process.terminated
    assert session._process is None
    assert session._state == "error"


@pytest.mark.asyncio
async def test_cancelled_generation_releases_worker(monkeypatch):
    session, process = session_with_worker(monkeypatch,"timeout")
    session.settings.voice_turn_timeout_seconds = 5
    async def consume():
        async for _event in session.stream_turn(b"audio",session_id="voice-thread"):
            pass
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated
    assert session._process is None
    assert session._state == "cold"


@pytest.mark.asyncio
async def test_cancel_during_loading_preserves_single_warm_worker(monkeypatch):
    session, process = session_with_worker(monkeypatch)
    session._ready = False
    loaded = asyncio.Event()
    calls = []

    async def load():
        calls.append("load")
        await loaded.wait()
        session._ready = True
        session._state = "ready"

    monkeypatch.setattr(session, "_ensure_worker", load)
    async def consume():
        return [event async for event in session.stream_turn(b"audio", session_id="test")]

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not process.terminated
    assert not session._warmup_task.done()
    # Repeated prepare requests share the same in-flight startup.
    session.prepare()
    loaded.set()
    await session._warmup_task
    assert calls == ["load"]
    assert session.status().ready
    await session.close()


@pytest.mark.asyncio
async def test_repeated_task_cancellation_finishes_cleanup_before_releasing_lock(monkeypatch):
    session, process = session_with_worker(monkeypatch, "timeout")
    session.settings.voice_turn_timeout_seconds = 5
    finishing = asyncio.Event()
    entered = asyncio.Event()
    original_stop = session._stop_worker_tree

    async def delayed_stop():
        entered.set()
        await finishing.wait()
        await original_stop()

    monkeypatch.setattr(session, "_stop_worker_tree", delayed_stop)
    async def consume():
        async for _event in session.stream_turn(b"audio", session_id="test"):
            pass
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    task.cancel()
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert session._lock.locked()
    assert session._process is process
    finishing.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated
    assert session._process is None
    assert session._state == "cold"


@pytest.mark.asyncio
async def test_disconnected_stream_cancel_scope_does_not_orphan_worker(monkeypatch):
    """Starlette cancels streaming responses with level-triggered AnyIO scopes."""
    session, process = session_with_worker(monkeypatch, "timeout")
    session.settings.voice_turn_timeout_seconds = 5
    with anyio.CancelScope() as scope:
        scope.cancel()
        async for _event in session.stream_turn(b"audio", session_id="disconnected"):
            pass
    assert process.terminated, "Disconnect left a live model behind while forgetting its PID"
    assert session._process is None
    assert session._state == "cold"
