from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
import subprocess
import uuid

from agent.terminal.profiles import TerminalProfile


class TerminalTransport:
    async def start(self) -> None:
        raise NotImplementedError

    async def read(self) -> str | None:
        raise NotImplementedError

    async def write(self, data: str) -> None:
        raise NotImplementedError

    async def resize(self, cols: int, rows: int) -> None:
        raise NotImplementedError

    async def terminate(self) -> None:
        raise NotImplementedError


class SubprocessTerminalTransport(TerminalTransport):
    def __init__(self, profile: TerminalProfile):
        self.profile = profile
        self.process: subprocess.Popen[str] | None = None
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [self.profile.command, *self.profile.args],
            cwd=str(self.profile.cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())

    async def _read_stdout(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        loop = asyncio.get_running_loop()
        try:
            while True:
                line = await loop.run_in_executor(None, self.process.stdout.readline)
                if line == "":
                    break
                await self._queue.put(line)
        finally:
            await self._queue.put(None)

    async def read(self) -> str | None:
        return await self._queue.get()

    async def write(self, data: str) -> None:
        if self.process is None or self.process.stdin is None:
            return
        self.process.stdin.write(data)
        self.process.stdin.flush()

    async def resize(self, cols: int, rows: int) -> None:
        return None

    async def terminate(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(self.process.wait), timeout=2)
            except asyncio.TimeoutError:
                self.process.kill()
        if self._reader_task:
            self._reader_task.cancel()


class WinPtyTerminalTransport(TerminalTransport):
    def __init__(self, profile: TerminalProfile, cols: int = 120, rows: int = 32):
        self.profile = profile
        self.cols = cols
        self.rows = rows
        self._process = None
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        from winpty import PtyProcess

        command_line = " ".join([self.profile.command, *self.profile.args])
        self._process = PtyProcess.spawn(command_line, cwd=str(self.profile.cwd), dimensions=(self.rows, self.cols))
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._process is not None
        while self._process.isalive():
            try:
                data = await asyncio.to_thread(self._process.read, 4096)
            except EOFError:
                break
            if data:
                await self._queue.put(data)
        await self._queue.put(None)

    async def read(self) -> str | None:
        return await self._queue.get()

    async def write(self, data: str) -> None:
        if self._process is not None and self._process.isalive():
            self._process.write(data)

    async def resize(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        if self._process is not None and self._process.isalive():
            if hasattr(self._process, "set_size"):
                self._process.set_size(rows, cols)
            else:
                self._process.setwinsize(rows, cols)

    async def terminate(self) -> None:
        if self._process is not None and self._process.isalive():
            self._process.terminate(force=True)
        if self._reader_task:
            self._reader_task.cancel()


def default_transport_factory(profile: TerminalProfile) -> TerminalTransport:
    if os.name == "nt":
        try:
            import winpty  # noqa: F401

            return WinPtyTerminalTransport(profile)
        except Exception:
            return SubprocessTerminalTransport(profile)
    return SubprocessTerminalTransport(profile)


class TerminalSession:
    def __init__(
        self,
        session_id: str,
        profile: TerminalProfile,
        transport_factory: Callable[[TerminalProfile], TerminalTransport] = default_transport_factory,
    ):
        self.id = session_id
        self.profile = profile
        self.transport = transport_factory(profile)
        self.started = False

    async def start(self) -> None:
        if self.started:
            return
        await self.transport.start()
        self.started = True

    async def read(self) -> str | None:
        return await self.transport.read()

    async def write(self, data: str) -> None:
        if not self.started:
            raise RuntimeError("terminal session is not ready")
        await self.transport.write(data)

    async def resize(self, cols: int, rows: int) -> None:
        if not self.started:
            return
        await self.transport.resize(cols, rows)

    async def terminate(self) -> None:
        await self.transport.terminate()


class TerminalSessionManager:
    def __init__(self, transport_factory: Callable[[TerminalProfile], TerminalTransport] = default_transport_factory):
        self.transport_factory = transport_factory
        self.sessions: dict[str, TerminalSession] = {}

    async def create(self, profile: TerminalProfile) -> TerminalSession:
        session = TerminalSession(str(uuid.uuid4()), profile, self.transport_factory)
        await session.start()
        self.sessions[session.id] = session
        return session

    def get(self, session_id: str) -> TerminalSession | None:
        return self.sessions.get(session_id)

    async def terminate(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is not None:
            await session.terminate()
