"""The removed standalone mode cannot be reached by old clients."""

import pytest
from fastapi.testclient import TestClient

from agent import api
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime


@pytest.mark.parametrize("action_id", [
    "coding.workspace.open",
    "github.pull_request.open",
    "github.pull_request.create",
])
def test_legacy_coding_actions_are_unavailable(action_id):
    runtime = AppActionRuntime()
    assert action_id not in {action.id for action in runtime.catalog().actions}
    receipt = runtime.dispatch(
        AppActionRequest(action_id=action_id),
        AppActionContext(source="ui"),
    )
    assert receipt.status == "unavailable"
    assert "navigation" not in receipt.result


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/coding/health"),
    ("GET", "/api/coding/sessions"),
    ("POST", "/api/coding/sessions"),
    ("POST", "/api/coding/sessions/legacy/turns/stream"),
    ("GET", "/api/coding/projects/tree"),
])
def test_removed_coding_endpoints_return_not_found(method, path):
    response = TestClient(api.app).request(method, path)
    assert response.status_code == 404


def test_coding_requests_use_main_chat_instead_of_workspace_navigation():
    runtime = AppActionRuntime()
    for message in ("open coding workspace", "switch to coding", "open coding session Fix issue 171"):
        assert runtime.match_submission(message) is None
