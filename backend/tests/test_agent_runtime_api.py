from __future__ import annotations

from pathlib import Path
import asyncio
import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import api
from agent.agents.live_dispatcher import LiveAgentResult
from agent.organization import OrganizationStore, TaskRoomService
from agent.profiles import ProfileRegistry
from agent.runtime.supervisor import AgentSupervisor


def test_runtime_read_endpoints_and_confirmed_cancel(monkeypatch, tmp_path: Path):
    supervisor = AgentSupervisor(tmp_path / "tasks.db", monitor_interval=0.01)

    def work(control):
        while not control.cancelled:
            control.heartbeat()
            time.sleep(0.01)

    task_id = supervisor.submit(run_id="run", agent_name="SportsAgent", department="sports", work=work)
    store = OrganizationStore(tmp_path / "org.db")
    rooms = TaskRoomService(store)
    room = rooms.create(owner="VellumAgent", purpose="compare", participants=["SportsAgent"])
    monkeypatch.setattr(api._delegation_runtime, "supervisor", supervisor)
    monkeypatch.setattr(api, "_profile_registry", ProfileRegistry(tmp_path / "profiles"))
    monkeypatch.setattr(api, "_organization_store", store)
    monkeypatch.setattr(api, "_task_rooms", rooms)

    with TestClient(api.app) as client:
        assert client.get("/api/agent-runtime/departments").status_code == 200
        assert client.get("/api/agent-runtime/agents").status_code == 200
        assert client.get("/api/agent-runtime/tasks").json()["tasks"][0]["task_id"] == task_id
        assert client.get(f"/api/agent-runtime/tasks/{task_id}").status_code == 200
        assert client.get("/api/agent-runtime/rooms").json()["rooms"][0]["id"] == room.id
        assert client.get("/api/agent-runtime/health").json()["active_workers"] == 1
        assert client.post(f"/api/agent-runtime/tasks/{task_id}/cancel", json={"confirm": False}).status_code == 409
        cancelled = client.post(f"/api/agent-runtime/tasks/{task_id}/cancel", json={"confirm": True})

    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["state"] == "cancelled"


def test_agent_profile_api_exposes_organizational_boundaries(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api, "_profile_registry", ProfileRegistry(tmp_path / "profiles"))
    with TestClient(api.app) as client:
        body = client.get("/api/agent-runtime/agents").json()
    sports = next(agent for agent in body["agents"] if agent["id"] == "SportsAgent")
    assert sports["department"] == "sports"
    assert sports["isolation"]["backend"] == "subprocess"
    assert "identity" in sports and "workspace" in sports


def test_specialist_stream_adds_organization_events_but_only_vellum_final(monkeypatch):
    live = LiveAgentResult(
        handled=True, agent_name="SportsAgent", answer="specialist evidence",
        status="answered", confidence=0.8, run_id="run-1",
    )
    monkeypatch.setattr(api, "_live_dispatcher", SimpleNamespace(maybe_handle=lambda message, thread: live))
    monkeypatch.setattr(api, "_ensure_model", lambda model: asyncio.sleep(0))
    monkeypatch.setattr(api, "_repair_incomplete_tool_history", lambda thread: asyncio.sleep(0))

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="Vellum synthesis")}}

    monkeypatch.setattr(api, "agent", FakeAgent())

    async def collect():
        return [chunk async for chunk in api._stream_agent_turn(
            clean_message="latest nba", active_thread_id="thread", model=None, store=False,
        )]

    chunks = asyncio.run(collect())
    organization = []
    finals = []
    for chunk in chunks:
        event = next((line[6:].strip() for line in chunk.splitlines() if line.startswith("event:")), "")
        data = next((line[5:].strip() for line in chunk.splitlines() if line.startswith("data:")), "")
        if event == "organization":
            organization.append(json.loads(data))
        if event == "final":
            finals.append(json.loads(data))

    assert [item["event"] for item in organization] == [
        "task_queued", "task_started", "task_completed", "message", "vellum_synthesis",
    ]
    assert organization[3]["message_type"] == "final_contribution"
    assert len(finals) == 1
    assert finals[0]["answer"] == "Vellum synthesis"
