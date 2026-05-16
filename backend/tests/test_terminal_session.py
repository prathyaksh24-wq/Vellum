import asyncio
from pathlib import Path

import pytest

from agent.terminal.profiles import TerminalProfile
from agent.terminal.session import TerminalSession, TerminalSessionManager, WinPtyTerminalTransport


class FakeTransport:
    def __init__(self):
        self.started = False
        self.closed = False
        self.inputs = []
        self.resizes = []
        self.output = asyncio.Queue()
        self.returncode = None

    async def start(self):
        self.started = True
        await self.output.put("ready\r\n")

    async def read(self):
        return await self.output.get()

    async def write(self, data):
        self.inputs.append(data)

    async def resize(self, cols, rows):
        self.resizes.append((cols, rows))

    async def terminate(self):
        self.closed = True
        self.returncode = 0
        await self.output.put(None)


def make_profile():
    return TerminalProfile(
        id="powershell",
        label="PowerShell",
        command="powershell.exe",
        args=["-NoLogo"],
        cwd=Path("C:/work"),
        available=True,
    )


@pytest.mark.asyncio
async def test_terminal_session_starts_and_streams_output():
    transport = FakeTransport()
    session = TerminalSession("session-1", make_profile(), lambda profile: transport)

    await session.start()
    output = await asyncio.wait_for(session.read(), timeout=1)

    assert transport.started is True
    assert output == "ready\r\n"


@pytest.mark.asyncio
async def test_terminal_session_forwards_input_and_resize():
    transport = FakeTransport()
    session = TerminalSession("session-1", make_profile(), lambda profile: transport)

    await session.start()
    await session.write("Get-Location\r")
    await session.resize(120, 32)

    assert transport.inputs == ["Get-Location\r"]
    assert transport.resizes == [(120, 32)]


@pytest.mark.asyncio
async def test_terminal_session_terminate_closes_transport():
    transport = FakeTransport()
    session = TerminalSession("session-1", make_profile(), lambda profile: transport)

    await session.start()
    await session.terminate()

    assert transport.closed is True


@pytest.mark.asyncio
async def test_manager_creates_and_removes_sessions():
    transport = FakeTransport()
    manager = TerminalSessionManager(transport_factory=lambda profile: transport)

    session = await manager.create(make_profile())
    assert session.id in manager.sessions

    await manager.terminate(session.id)

    assert session.id not in manager.sessions
    assert transport.closed is True


@pytest.mark.asyncio
async def test_winpty_resize_supports_setwinsize_api():
    class FakePtyProcess:
        def __init__(self):
            self.calls = []

        def isalive(self):
            return True

        def setwinsize(self, rows, cols):
            self.calls.append((rows, cols))

    transport = WinPtyTerminalTransport(make_profile())
    fake = FakePtyProcess()
    transport._process = fake

    await transport.resize(100, 30)

    assert fake.calls == [(30, 100)]
