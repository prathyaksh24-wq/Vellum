import asyncio
import base64
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from agent import api


@pytest.fixture(autouse=True)
def disable_runtime_services(monkeypatch):
    monkeypatch.setattr(api, "start_scheduler", lambda: None)
    monkeypatch.setattr(api, "start_vault_watcher", lambda: None)


class FakeVoiceAgent:
    async def astream_events(self, *args, **kwargs):
        yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="Hello ")}}
        yield {"event": "on_tool_start", "name": "search_my_notes"}
        yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="there.")}}


class FakeStt:
    engine = "moonshine"
    model = "tiny"

    def __init__(self, transcript="what did I say about focus"):
        self.transcript = transcript

    def transcribe_wav(self, audio_bytes):
        return self.transcript


class FakeTts:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def synthesize_wav(self, text):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("tts offline")
        return b"RIFFfake-wave"


def _wav_bytes():
    return b"RIFF$\x00\x00\x00WAVEfmt "


def _parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        event = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            events.append((event, json.loads(data)))
    return events


def test_voice_transcribe_returns_transcript_metadata(monkeypatch):
    monkeypatch.setattr(api, "get_stt_engine", lambda: FakeStt("hello vellum"), raising=False)

    with TestClient(api.app) as client:
        response = client.post(
            "/api/voice/transcribe",
            files={"audio": ("speech.wav", _wav_bytes(), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["transcript"] == "hello vellum"
    assert response.json()["engine"] == "moonshine"
    assert response.json()["model"] == "tiny"
    assert response.json()["duration_ms"] >= 0


def test_voice_transcribe_rejects_empty_transcript(monkeypatch):
    monkeypatch.setattr(api, "get_stt_engine", lambda: FakeStt("   "), raising=False)

    with TestClient(api.app) as client:
        response = client.post(
            "/api/voice/transcribe",
            files={"audio": ("speech.wav", _wav_bytes(), "audio/wav")},
        )

    assert response.status_code == 400
    assert "No speech" in response.json()["detail"]


def test_voice_turn_streams_transcript_text_final_then_audio(monkeypatch):
    learned = []

    async def fake_background_learn(query, answer, thread_id="default", source="agent"):
        learned.append((query, answer, thread_id, source))

    def fake_create_task(coro):
        loop = asyncio.get_running_loop()
        return loop.create_task(coro)

    monkeypatch.setattr(api, "agent", FakeVoiceAgent())
    monkeypatch.setattr(api, "get_stt_engine", lambda: FakeStt("tell me about stillness"), raising=False)
    monkeypatch.setattr(api, "get_tts_engine", lambda: FakeTts(), raising=False)
    monkeypatch.setattr(api, "_background_learn", fake_background_learn)
    monkeypatch.setattr(api.asyncio, "create_task", fake_create_task)

    with TestClient(api.app) as client:
        with client.stream(
            "POST",
            "/api/voice/turn",
            data={"thread_id": "voice-thread", "model": ""},
            files={"audio": ("speech.wav", _wav_bytes(), "audio/wav")},
        ) as response:
            body = response.read().decode("utf-8")

    assert response.status_code == 200
    events = _parse_sse(body)
    names = [event for event, _payload in events]
    assert names[:2] == ["transcript", "meta"]
    assert "token" in names
    assert "tool" in names
    assert "audio" in names
    assert names.index("audio") > names.index("final")
    assert events[0][1]["text"] == "tell me about stillness"
    audio_payload = next(payload for event, payload in events if event == "audio")
    assert base64.b64decode(audio_payload["wav_b64"]) == b"RIFFfake-wave"
    final_payload = next(payload for event, payload in events if event == "final")
    assert final_payload["answer"] == "Hello there."
    assert final_payload["voice"] is True
    assert learned == [("tell me about stillness", "Hello there.", "voice-thread", "voice")]


def test_voice_turn_keeps_text_when_tts_fails(monkeypatch):
    monkeypatch.setattr(api, "agent", FakeVoiceAgent())
    monkeypatch.setattr(api, "get_stt_engine", lambda: FakeStt("voice prompt"), raising=False)
    monkeypatch.setattr(api, "get_tts_engine", lambda: FakeTts(fail=True), raising=False)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close() or object())

    with TestClient(api.app) as client:
        with client.stream(
            "POST",
            "/api/voice/turn",
            files={"audio": ("speech.wav", _wav_bytes(), "audio/wav")},
        ) as response:
            body = response.read().decode("utf-8")

    assert response.status_code == 200
    events = _parse_sse(body)
    names = [event for event, _payload in events]
    assert "audio" not in names
    assert events[-1][0] == "final"
    assert events[-1][1]["answer"] == "Hello there."


def test_voice_speak_returns_wav_for_replay(monkeypatch):
    monkeypatch.setattr(api, "get_tts_engine", lambda: FakeTts(), raising=False)

    with TestClient(api.app) as client:
        response = client.post("/api/voice/speak", json={"text": "Read this back."})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFFfake-wave"
