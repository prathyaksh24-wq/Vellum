from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from agent.agents.calendar import CalendarAgent
from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.agents.live_dispatcher import LiveAgentDispatcher
from agent.master.state import MasterThreadStateStore
from agent.plugins.portable import PortablePluginContext, load_portable_plugin
from agent.profiles.catalog import AgentCatalog
from agent.tools.calendar import _external_response_json
from agent.tools.capabilities.calendar_service import CalendarCapabilityService
from agent.tools.registry import ToolPermissionError


pytestmark = pytest.mark.usefixtures("repo_root_cwd")


class FakeKeyring:
    def __init__(self) -> None:
        self.values = {}

    def get_password(self, service_name, username):
        return self.values.get((service_name, username))

    def set_password(self, service_name, username, password):
        self.values[(service_name, username)] = password

    def delete_password(self, service_name, username):
        self.values.pop((service_name, username), None)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def calendar_module():
    return load_portable_plugin(Path("plugins/connectors/google_calendar")).module


def test_manifest_registers_one_calendar_connector() -> None:
    plugin = load_portable_plugin(Path("plugins/connectors/google_calendar"))
    context = PortablePluginContext()

    plugin.register(context)

    assert list(context.connectors) == ["google-calendar"]
    assert "calendar.events" in plugin.manifest.capabilities
    assert "calendar.create_event" in context.connectors["google-calendar"]["capabilities"]


def test_oauth_url_requests_only_approved_calendar_scopes() -> None:
    module = calendar_module()
    url = module.auth.authorization_url(
        client_id="desktop-client",
        redirect_uri="http://127.0.0.1:8000",
        state="calendar.state",
        code_challenge="challenge",
    )
    query = parse_qs(urlparse(url).query)

    assert set(query["scope"][0].split()) == set(module.auth.DEFAULT_SCOPES)
    assert "https://www.googleapis.com/auth/calendar" not in query["scope"][0].split()
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]


def test_tokens_are_keyring_only_and_disconnect_is_local(tmp_path: Path) -> None:
    module = calendar_module()
    keyring = FakeKeyring()
    store = module.auth.GoogleCalendarAuthStore(tmp_path, keyring_backend=keyring)
    store.save_tokens({
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "expires_in": 3600,
        "scope": " ".join(module.auth.DEFAULT_SCOPES),
    })
    store.save_profile({"id": "private-account", "summary": "Primary", "timeZone": "Asia/Kolkata"})

    persisted = store.metadata_path.read_text(encoding="utf-8")
    assert "access-secret" not in persisted
    assert "refresh-secret" not in persisted
    client = module.client.GoogleCalendarClient(client_id="client", client_secret="secret", store=store)
    client.disconnect()
    assert store.load_tokens(required=False) == {}


def test_client_refreshes_and_lists_events(tmp_path: Path) -> None:
    module = calendar_module()
    store = module.auth.GoogleCalendarAuthStore(tmp_path, keyring_backend=FakeKeyring())
    store.save_tokens({"access_token": "expired", "refresh_token": "refresh", "expires_at": 1})
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url == module.auth.TOKEN_URL:
            return FakeResponse({"access_token": "fresh", "expires_in": 3600})
        return FakeResponse({"items": [{
            "id": "event-1",
            "summary": "Review",
            "start": {"dateTime": "2026-09-10T10:00:00+05:30"},
            "end": {"dateTime": "2026-09-10T11:00:00+05:30"},
        }]})

    client = module.client.GoogleCalendarClient(
        client_id="client",
        client_secret="secret",
        store=store,
        request_backend=request,
        clock=lambda: 100.0,
    )
    events = client.list_events(
        time_min="2026-09-10T00:00:00+05:30",
        time_max="2026-09-11T00:00:00+05:30",
    )

    assert events[0]["id"] == "event-1"
    assert calls[0][2]["data"]["refresh_token"] == "refresh"
    assert calls[1][2]["headers"]["Authorization"] == "Bearer fresh"
    assert calls[1][2]["params"]["singleEvents"] == "true"


def test_client_reads_calendar_timezone_settings(tmp_path: Path) -> None:
    module = calendar_module()
    store = module.auth.GoogleCalendarAuthStore(tmp_path, keyring_backend=FakeKeyring())
    store.save_tokens({"access_token": "access", "refresh_token": "refresh", "expires_at": 1000})

    def request(method, url, **_kwargs):
        assert method == "GET"
        assert url.endswith("/users/me/settings")
        return FakeResponse({"items": [{"id": "timezone", "value": "Asia/Kolkata"}]})

    client = module.client.GoogleCalendarClient(
        client_id="client",
        client_secret="secret",
        store=store,
        request_backend=request,
        clock=lambda: 100.0,
    )

    assert client.calendar_settings() == {"timezone": "Asia/Kolkata"}


def build_service(**overrides) -> CalendarCapabilityService:
    defaults = {
        "account_backend": lambda: {"configured": True, "connected": True, "time_zone": "Asia/Kolkata"},
        "calendars_backend": lambda: [{"id": "primary", "summary": "Primary", "primary": True}],
        "events_backend": lambda **_kwargs: [],
        "event_backend": lambda **kwargs: {"id": kwargs["event_id"], "summary": "Review"},
        "free_busy_backend": lambda **_kwargs: {"calendars": {"primary": {"busy": []}}},
        "create_backend": lambda **kwargs: {"id": "new-event", **kwargs["event"]},
        "update_backend": lambda **kwargs: {"id": kwargs["event_id"], **kwargs["patch"]},
        "delete_backend": lambda **kwargs: {"deleted": True, **kwargs},
    }
    defaults.update(overrides)
    return CalendarCapabilityService(**defaults)


def test_writes_require_confirmation_at_service_and_registry() -> None:
    service = build_service()
    payload = {
        "summary": "Review",
        "start": "2026-09-10T10:00:00+05:30",
        "end": "2026-09-10T11:00:00+05:30",
    }

    with pytest.raises(ToolPermissionError, match="explicit confirmation"):
        service.create_event(payload)
    registry = service.build_registry()
    with pytest.raises(ToolPermissionError, match="requires explicit confirmation"):
        registry.invoke("calendar.create_event", payload, agent_name="CalendarAgent")
    result = registry.invoke("calendar.create_event", {**payload, "confirm": True}, agent_name="CalendarAgent")
    assert result["event"]["id"] == "new-event"


def test_agent_reads_today_and_prepares_then_executes_create() -> None:
    recorded = []
    service = build_service(
        events_backend=lambda **_kwargs: [{
            "id": "event-1",
            "summary": "Morning review",
            "start": {"dateTime": "2026-09-10T09:00:00+05:30"},
            "end": {"dateTime": "2026-09-10T10:00:00+05:30"},
        }],
        create_backend=lambda **kwargs: recorded.append(kwargs) or {"id": "event-2", **kwargs["event"]},
    )
    agent = CalendarAgent(
        tool_registry=service.build_registry(),
        now=lambda tz: datetime(2026, 9, 10, 8, 0, tzinfo=tz),
    )

    read = agent.answer("What is on my calendar today?")
    prepared = agent.answer('Schedule "Project review" tomorrow at 3 PM for 30 minutes on my calendar')
    completed = agent.execute_action_request(prepared.action_request)

    assert "Morning review" in read.summary
    assert prepared.action_request["action"] == "calendar.create_event"
    assert prepared.action_request["payload"]["start"] == "2026-09-11T15:00:00+05:30"
    assert completed.status == "answered"
    assert recorded[0]["event"]["summary"] == "Project review"


def test_agent_refuses_ambiguous_calendar_changes() -> None:
    agent = CalendarAgent(tool_registry=build_service().build_registry())

    response = agent.answer("Schedule a meeting sometime tomorrow on my calendar")

    assert response.status == "blocked"
    assert response.action_request == {}
    assert "title in quotes" in response.summary


def test_agent_reports_account_probe_failure_as_connector_error() -> None:
    def fail_account():
        raise RuntimeError("offline")

    agent = CalendarAgent(tool_registry=build_service(account_backend=fail_account).build_registry())

    response = agent.answer("Are you connected to my calendar?")

    assert response.status == "error"
    assert response.summary == "CalendarAgent could not check Google Calendar."
    assert response.analysis == "Calendar connector failed: RuntimeError."


def test_event_answers_include_the_exact_id_needed_for_a_safe_change() -> None:
    service = build_service(events_backend=lambda **_kwargs: [{
        "id": "event-123",
        "summary": "Review",
        "start": {"dateTime": "2026-09-10T10:00:00+05:30"},
        "end": {"dateTime": "2026-09-10T11:00:00+05:30"},
    }])
    agent = CalendarAgent(
        tool_registry=service.build_registry(),
        now=lambda tz: datetime(2026, 9, 10, tzinfo=tz),
    )

    response = agent.answer("What is on my calendar today?")

    assert "event ID: event-123" in response.summary


def test_main_model_calendar_envelope_withholds_event_content_and_action_payload() -> None:
    response = SpecialistResponse(
        agent="CalendarAgent",
        status="blocked",
        summary="Private meeting with Example Person at Private Place",
        sources=[SpecialistSource(
            kind="api",
            title="Private meeting",
            path_or_url="google-calendar://events/private-event-id",
        )],
        action_request={
            "action": "calendar.create_event",
            "payload": {"summary": "Private meeting", "attendees": ["private@example.com"]},
        },
    )

    payload = _external_response_json(response)

    assert '"privacy": "local_only_content_withheld"' in payload
    assert '"action": "calendar.create_event"' in payload
    assert "Private meeting" not in payload
    assert "private@example.com" not in payload
    assert "private-event-id" not in payload


def test_live_dispatcher_routes_calendar_queries_to_the_local_specialist(tmp_path: Path) -> None:
    service = build_service(events_backend=lambda **_kwargs: [{
        "id": "event-123",
        "summary": "Project review",
        "start": {"dateTime": "2026-09-10T10:00:00+05:30"},
        "end": {"dateTime": "2026-09-10T11:00:00+05:30"},
    }])
    calendar = CalendarAgent(
        tool_registry=service.build_registry(),
        now=lambda tz: datetime(2026, 9, 10, tzinfo=tz),
    )
    catalog = AgentCatalog(profile_dir=tmp_path / "profiles", executors={calendar.name: calendar})
    dispatcher = LiveAgentDispatcher(
        vault_root=tmp_path / "Vault",
        agent_catalog=catalog,
        state_store=MasterThreadStateStore(sessions_db=tmp_path / "sessions.db"),
    )

    result = dispatcher.maybe_handle("Calendar agent: what is on my calendar today?", thread_id="calendar-thread")

    assert result is not None
    assert result.agent_name == "CalendarAgent"
    assert result.tools == ["calendar_agent"]
    assert "Project review" in result.answer
