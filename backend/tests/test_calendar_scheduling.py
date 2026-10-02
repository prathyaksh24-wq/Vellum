from datetime import datetime
from pathlib import Path
import pytest
from agent.agents.calendar import CalendarAgent
from agent.plugins import google_calendar_api, google_calendar_runtime
from agent.tools.capabilities.calendar_service import CalendarCapabilityService, CalendarConflictError
from agent.tools.registry import ToolPermissionError


def event(title="Review", event_id="review-1", start="2026-10-02T15:00:00+05:30", end="2026-10-02T15:30:00+05:30", **extra):
    return {"id":event_id,"summary":title,"start":{"dateTime":start},"end":{"dateTime":end},**extra}


def service(items=(), calls=None):
    calls = calls if calls is not None else []
    return CalendarCapabilityService(
        account_backend=lambda:{"configured":True,"connected":True,"enabled":True,"time_zone":"Asia/Kolkata"},
        calendars_backend=lambda:[{"id":"primary","summary":"Personal","primary":True,"accessRole":"owner"}],
        events_backend=lambda **kw:list(items),
        event_backend=lambda **kw:next(e for e in items if e["id"]==kw["event_id"]),
        create_backend=lambda **kw:calls.append(("create",kw)) or {"id":"new-event",**kw["event"]},
        update_backend=lambda **kw:calls.append(("update",kw)) or {"id":kw["event_id"],**kw["patch"]},
        delete_backend=lambda **kw:calls.append(("delete",kw)) or {"deleted":True,**kw},
    )


def payload(**extra):
    return {"calendar_id":"primary","summary":"New event","start":"2026-10-02T15:00:00+05:30",
            "end":"2026-10-02T15:30:00+05:30","time_zone":"Asia/Kolkata","confirm":True,**extra}


def agent(items=(), calls=None):
    return CalendarAgent(tool_registry=service(items,calls).build_registry(), now=lambda tz:datetime(2026,10,1,10,tzinfo=tz))


def test_collision_proposes_adjacent_slot_without_writing():
    calls=[]; result=service([event()],calls).availability(payload())
    assert result["available"] is False
    assert result["proposed"]["start"]=="2026-10-02T15:30:00+05:30"
    assert calls==[]


def test_service_rechecks_collision_at_write_time():
    calls=[]
    with pytest.raises(CalendarConflictError):service([event()],calls).create_event(payload())
    assert calls==[]


def test_update_ignores_only_its_own_event():
    result=service([event()]).availability(payload(event_id="review-1"))
    assert result["available"] is True
    with pytest.raises(CalendarConflictError):service([event()]).create_event(payload(event_id="review-1"))


@pytest.mark.parametrize("extra",[{"transparency":"transparent"},{"status":"cancelled"},{"attendees":[{"self":True,"responseStatus":"declined"}]}])
def test_non_busy_events_do_not_block(extra):
    assert service([event(**extra)]).availability(payload())["available"]


def test_all_day_event_is_busy():
    item={"id":"holiday","start":{"date":"2026-10-02"},"end":{"date":"2026-10-03"}}
    result=service([item]).availability(payload())
    assert result["proposed"]["start"]=="2026-10-03T09:00:00+05:30"


def test_no_slot_when_whole_horizon_is_busy():
    item=event(start="2026-10-02T00:00:00+05:30",end="2026-10-10T00:00:00+05:30")
    assert service([item]).availability(payload())["proposed"] is None


def test_many_events_fail_closed():
    with pytest.raises(ValueError,match="safely"):service([event()]*250).availability(payload())


def test_natural_create_title_and_conflict_confirmation():
    calls=[]; cal=agent([event()],calls)
    response=cal.answer("Schedule Vellum test tomorrow at 3 PM for 30 minutes on my calendar")
    assert "Does that time work" in response.summary
    assert response.action_request["payload"]["summary"]=="Vellum test"
    assert response.action_request["payload"]["start"]=="2026-10-02T15:30:00+05:30"
    assert calls==[]
    assert cal.execute_action_request(response.action_request).status=="answered"
    assert len(calls)==1


def test_find_then_update_by_title_preserves_duration():
    calls=[]; response=agent([event()],calls).answer('Move "Review" on my calendar tomorrow at 4 PM')
    assert response.action_request["payload"]["event_id"]=="review-1"
    assert response.action_request["payload"]["end"]=="2026-10-02T16:30:00+05:30"
    assert calls==[]


def test_delete_by_title_is_confirmed_and_unambiguous():
    calls=[]; cal=agent([event()],calls); response=cal.answer('Delete "Review" from my calendar')
    assert response.action_request["payload"]["event_id"]=="review-1"
    assert calls==[]
    cal.execute_action_request(response.action_request)
    assert calls[0][0]=="delete"


def test_duplicate_event_titles_require_clarification():
    response=agent([event(),event(event_id="review-2")]).answer('Delete "Review" from my calendar')
    assert not response.action_request
    assert "more than one" in response.summary


def test_late_collision_produces_new_confirmation():
    cal=agent([event()])
    result=cal.execute_action_request({"action":"calendar.create_event","payload":payload()})
    assert result.status=="blocked"
    assert result.action_request["payload"]["start"]=="2026-10-02T15:30:00+05:30"


def test_disabled_runtime_blocks_private_reads(monkeypatch):
    registry=type("Registry",(),{"is_enabled":lambda self,id:False})()
    monkeypatch.setattr(google_calendar_runtime,"get_plugin_registry",lambda:registry)
    with pytest.raises(ToolPermissionError,match="disabled"):google_calendar_runtime.google_calendar_client()


def test_disabled_agent_does_not_fetch_events():
    svc=service();svc.account_backend=lambda:{"configured":True,"connected":True,"enabled":False}
    svc.events_backend=lambda **kw:pytest.fail("Disabled agent read events")
    assert "disabled" in CalendarAgent(tool_registry=svc.build_registry()).answer("My calendar today").summary


def test_api_exposes_conflict_details(monkeypatch):
    from fastapi import APIRouter,FastAPI
    from fastapi.testclient import TestClient
    monkeypatch.setattr(google_calendar_api,"google_calendar_service",lambda:service([event()]))
    app=FastAPI();router=APIRouter(prefix="/api");router.include_router(google_calendar_api.router);app.include_router(router)
    result=TestClient(app).post("/api/plugins/google-calendar/events",json=payload())
    assert result.status_code==409
    assert result.json()["detail"]["availability"]["proposed"]["start"].endswith("15:30:00+05:30")
