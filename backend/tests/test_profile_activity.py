from datetime import date, datetime, timezone

import pytest

from agent.contracts.profile import ProfileDetails
from agent.observability import ObservabilityService


def test_profile_days_use_local_midnight_and_count_responses_once(tmp_path):
    service = ObservabilityService(tmp_path / "activity.db")
    for index, at in enumerate(("2026-11-10T18:29:00+00:00", "2026-11-10T18:31:00+00:00")):
        base = {"response_id": str(index), "thread_id": "local", "created_at": at}
        service.capture({**base, "type": "response.created"})
        service.capture({**base, "type": "response.completed", "response": {}})
    snapshot = service.profile_activity(
        time_zone="Asia/Calcutta", selected_date=date(2026, 11, 11),
        now=datetime(2026, 11, 11, 8, tzinfo=timezone.utc),
    )
    assert {item.date: item.count for item in snapshot.days} == {date(2026, 11, 10): 1, date(2026, 11, 11): 1}
    assert [item.id for item in snapshot.selected_items] == ["1"]
    assert snapshot.selected_items[0].label == "Completed a response"


def test_empty_activity_has_no_sample_history_and_future_selection_is_rejected(tmp_path):
    service = ObservabilityService(tmp_path / "empty.db")
    now = datetime(2026, 11, 11, 8, tzinfo=timezone.utc)
    snapshot = service.profile_activity(time_zone="UTC", now=now)
    assert snapshot.days == snapshot.recent == snapshot.selected_items == []
    with pytest.raises(ValueError):
        service.profile_activity(time_zone="UTC", now=now, selected_date=date(2026, 11, 12))


@pytest.mark.parametrize("website", ["javascript:alert(1)", "data:text/html,hi", "https://user:password@example.com"])
def test_profile_rejects_unsafe_website_links(website):
    with pytest.raises(ValueError):
        ProfileDetails.model_validate({"website": website})


def test_profile_patch_preserves_omitted_fields_and_allows_clearing_optional_details():
    patch = ProfileDetails.model_validate({"username": "", "website": ""})
    assert patch.model_dump(exclude_unset=True) == {"username": "", "website": ""}
