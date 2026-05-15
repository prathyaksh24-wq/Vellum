import asyncio

from fastapi.testclient import TestClient

from agent import api
from agent.terminal.profiles import TerminalProfile


class FakeSession:
    def __init__(self, profile):
        self.id = "session-test"
        self.profile = profile
        self.writes = []
        self.resizes = []
        self.reads = asyncio.Queue()
        self.reads.put_nowait("hello\r\n")
        self.reads.put_nowait(None)

    async def read(self):
        return await self.reads.get()

    async def write(self, data):
        self.writes.append(data)

    async def resize(self, cols, rows):
        self.resizes.append((cols, rows))

    async def terminate(self):
        return None


class FakeManager:
    def __init__(self):
        self.created = []
        self.terminated = []
        self.session = None

    async def create(self, profile):
        self.session = FakeSession(profile)
        self.created.append(profile.id)
        return self.session

    async def terminate(self, session_id):
        self.terminated.append(session_id)


def available_profile():
    return TerminalProfile("powershell", "PowerShell", "powershell.exe", ["-NoLogo"], api.Path("."), True)


def test_terminal_profiles_endpoint(monkeypatch):
    monkeypatch.setattr(api, "list_terminal_profiles", lambda: [available_profile()])

    with TestClient(api.app) as client:
        response = client.get("/api/terminal/profiles")

    assert response.status_code == 200
    assert response.json()["profiles"][0]["id"] == "powershell"


def test_terminal_websocket_starts_profile_and_streams_output(monkeypatch):
    fake_manager = FakeManager()
    monkeypatch.setattr(api, "terminal_session_manager", fake_manager)
    monkeypatch.setattr(api, "get_terminal_profile", lambda profile_id: available_profile())

    with TestClient(api.app) as client:
        with client.websocket_connect("/api/terminal/ws") as websocket:
            websocket.send_json({"type": "start", "profile": "powershell", "cols": 100, "rows": 30})
            assert websocket.receive_json() == {
                "type": "ready",
                "sessionId": "session-test",
                "profile": "powershell",
            }
            assert websocket.receive_json() == {"type": "output", "data": "hello\r\n"}

    assert fake_manager.created == ["powershell"]


def test_terminal_websocket_rejects_unknown_profile(monkeypatch):
    monkeypatch.setattr(api, "get_terminal_profile", lambda profile_id: None)

    with TestClient(api.app) as client:
        with client.websocket_connect("/api/terminal/ws") as websocket:
            websocket.send_json({"type": "start", "profile": "nope"})
            message = websocket.receive_json()

    assert message["type"] == "error"
    assert "Unknown terminal profile" in message["message"]


def test_terminal_websocket_rejects_unavailable_profile(monkeypatch):
    profile = TerminalProfile("macos", "macOS SSH", "ssh", [], api.Path("."), False, "not configured")
    monkeypatch.setattr(api, "get_terminal_profile", lambda profile_id: profile)

    with TestClient(api.app) as client:
        with client.websocket_connect("/api/terminal/ws") as websocket:
            websocket.send_json({"type": "start", "profile": "macos"})
            message = websocket.receive_json()

    assert message == {"type": "error", "message": "not configured"}
