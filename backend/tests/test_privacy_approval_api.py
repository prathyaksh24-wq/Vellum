from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import api
from agent.mcp import api as plugin_mcp_api
from agent.mcp.plugin_approvals import PluginMcpApprovalStore, PluginMcpOperation
from agent.privacy import api as privacy_api
from agent.privacy.disclosure import DisclosureGrantStore


def test_disclosure_grant_api_issues_lists_and_revokes_local_grant(monkeypatch, tmp_path) -> None:
    store = DisclosureGrantStore(tmp_path / "disclosure-grants.db")
    monkeypatch.setattr(
        privacy_api,
        "get_routing_runtime",
        lambda: SimpleNamespace(broker=SimpleNamespace(grant_store=store)),
    )

    with TestClient(api.app) as client:
        issued = client.post(
            "/api/privacy/disclosure-grants",
            json={
                "mode": "ask_before_sharing",
                "thread_id": "thread-1",
                "categories": ["PERSON"],
                "ttl_seconds": 300,
            },
        )
        grant_id = issued.json()["grant"]["id"]
        listed = client.get(
            "/api/privacy/disclosure-grants", params={"thread_id": "thread-1"}
        )
        revoked = client.delete(f"/api/privacy/disclosure-grants/{grant_id}")
        after = client.get(
            "/api/privacy/disclosure-grants", params={"thread_id": "thread-1"}
        )

    assert issued.status_code == 200
    assert listed.json()["grants"][0]["id"] == grant_id
    assert revoked.json() == {"ok": True, "grant_id": grant_id}
    assert after.json()["grants"] == []


def test_plugin_mcp_approval_api_is_the_only_approval_transition(monkeypatch, tmp_path) -> None:
    store = PluginMcpApprovalStore(tmp_path / "plugin-approvals.db")
    request = store.request(PluginMcpOperation.from_arguments(
        plugin_id="demo",
        connector="records",
        tool_name="delete_record",
        arguments={"id": "1"},
    ))
    monkeypatch.setattr(plugin_mcp_api, "get_plugin_mcp_approval_store", lambda: store)

    with TestClient(api.app) as client:
        pending = client.get("/api/plugins/mcp/approvals")
        approved = client.post(
            f"/api/plugins/mcp/approvals/{request['id']}/approve"
        )

    assert pending.json()["approvals"][0]["status"] == "pending"
    assert approved.json()["approval"]["status"] == "approved"
