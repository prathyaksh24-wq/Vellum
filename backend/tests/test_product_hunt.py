import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.contracts.product_hunt import PLUGIN_ID, ProductHuntRead, ProductHuntFollow
from agent.plugins.product_hunt import ENDPOINT, ProductHuntError, ProductHuntService
from agent.plugins.product_hunt_controls import product_hunt_contribution
from agent.plugins.registry import PluginRegistry
from agent.plugins.sources import PluginSourceRecord

TOKEN = "test-producthunt-secret-do-not-log"
POST = {"id":"1", "name":"A launch", "slug":"a-launch", "url":"https://www.producthunt.com/posts/a-launch"}


class MemoryKeyring:
    def __init__(self):
        self.value = None

    def get_password(self, *_args):
        return self.value

    def set_password(self, _service, _user, value):
        self.value = value


@pytest.fixture
def connection():
    requests = []
    settings = {"code":200, "now":1000.0, "enabled":True, "following":False,
        "actor_id":"viewer-1", "target_id":"maker-2", "account_code":200, "write_code":200}
    def handler(request):
        requests.append(request)
        query = json.loads(request.content)["query"]
        if settings["code"] != 200:
            return httpx.Response(settings["code"], json={"error":TOKEN})
        actor={"id":settings["actor_id"],"username":"me","name":"Viewer","url":"https://www.producthunt.com/@me","isViewer":True}
        target={"id":settings["target_id"],"username":"maker","name":"Maker","url":"https://www.producthunt.com/@maker","isFollowing":settings["following"]}
        if "VellumConnectionCheck" in query:
            data = {"posts":{"edges":[{"node":{"id":"1", "name":"A launch"}}]}}
        elif "mutation VellumFollow" in query:
            if settings["write_code"] != 200:
                return httpx.Response(settings["write_code"],json={"error":TOKEN})
            undo="userFollowUndo" in query
            settings["following"]=not undo
            data={"userFollowUndo" if undo else "userFollow":{"errors":[],"node":{**target,"isFollowing":not undo}}}
        elif "VellumAccountItems" in query:
            if settings["account_code"] != 200:
                return httpx.Response(settings["account_code"],json={"error":TOKEN})
            field=next(x for x in ["votedPosts","madePosts","submittedPosts","followedCollections"] if x in query)
            node={"id":"c1","name":"Collection","url":"https://www.producthunt.com/collections/tools"} if field=="followedCollections" else POST
            data={"viewer":{"user":{field:{"edges":[{"node":node}],"pageInfo":{"hasNextPage":False,"endCursor":None}}}}}
        elif "query VellumAccount " in query:
            if settings["account_code"] != 200:
                return httpx.Response(settings["account_code"],json={"error":TOKEN})
            data={"viewer":{"user":actor}}
        elif "VellumUser" in query:
            data={"user":target}
        elif "VellumPost(" in query:
            data = {"post":POST}
        elif "VellumTopics" in query:
            data = {"topics":{"edges":[{"node":{"id":"t1", "name":"Developer Tools", "slug":"developer-tools"}}],"pageInfo":{"hasNextPage":False,"endCursor":None}}}
        else:
            data = {"posts":{"edges":[{"node":POST}],"pageInfo":{"hasNextPage":True,"endCursor":"cursor-2"}}}
        return httpx.Response(200, json={"data":data})
    keyring = MemoryKeyring()
    service = ProductHuntService(keyring=keyring, enabled=lambda:settings["enabled"], clock=lambda:settings["now"],
        client_factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(handler), **kwargs))
    return service, keyring, settings, requests


def connect(service):
    return service.connect(service.stage(TOKEN))


def test_staging_is_ephemeral_and_verification_precedes_persistence(connection):
    service, keyring, _, requests = connection
    reference = service.stage(TOKEN)
    assert TOKEN not in reference and keyring.value is None and not requests
    assert service.status().status == "not_connected"
    result = service.connect(reference)
    assert result.connected and result.verified_at
    assert TOKEN not in result.model_dump_json()
    assert json.loads(keyring.value)["token"] == TOKEN
    assert str(requests[0].url) == ENDPOINT
    assert requests[0].headers["authorization"] == "Bearer " + TOKEN
    assert "viewer" not in json.loads(requests[0].content)["query"]


@pytest.mark.parametrize("code,state", [(401,"unauthorized"),(403,"unauthorized"),(429,"rate_limited"),(503,"unreachable")])
def test_provider_failure_never_persists_a_new_token_or_echoes_it(connection, code, state):
    service, keyring, settings, _ = connection
    settings["code"] = code
    with pytest.raises(ProductHuntError) as caught:
        connect(service)
    assert caught.value.status == state
    assert TOKEN not in str(caught.value)
    assert keyring.value is None and not service.status().connected


def test_failed_replacement_preserves_existing_connection(connection):
    service, keyring, settings, _ = connection
    connect(service)
    original = keyring.value
    settings["code"] = 401
    with pytest.raises(ProductHuntError):
        service.connect(service.stage("invalid-replacement-token"))
    assert keyring.value == original


def test_expired_or_cancelled_stage_cannot_connect(connection):
    service, keyring, settings, requests = connection
    reference = service.stage(TOKEN)
    service.discard(reference)
    with pytest.raises(ProductHuntError):
        service.connect(reference)
    reference = service.stage(TOKEN)
    settings["now"] += 601
    with pytest.raises(ProductHuntError):
        service.connect(reference)
    assert keyring.value is None and not requests


def test_enablement_is_enforced_and_disconnect_invalidates_pending(connection):
    service, keyring, settings, requests = connection
    connect(service)
    settings["enabled"] = False
    count = len(requests)
    assert not service.status().connected and service.status().status == "disabled"
    with pytest.raises(ProductHuntError, match="disabled"):
        service.read(ProductHuntRead())
    assert len(requests) == count
    settings["enabled"] = True
    reference = service.stage(TOKEN)
    service.disconnect()
    assert json.loads(keyring.value) == {}
    with pytest.raises(ProductHuntError):
        service.connect(reference)


def test_stale_verification_and_revocation_are_truthful(connection):
    service, _, settings, _ = connection
    connect(service)
    settings["now"] += 86401
    assert service.status().configured and not service.status().connected
    assert service.status().status == "not_checked"
    service.verify()
    assert service.status().connected
    settings["code"] = 401
    with pytest.raises(ProductHuntError):
        service.read(ProductHuntRead())
    assert service.status().status == "unauthorized" and not service.status().connected


def test_agent_reads_have_bounded_typed_queries_and_pagination(connection, monkeypatch):
    service, _, _, requests = connection
    from agent.tools import product_hunt as tools
    monkeypatch.setattr(tools, "product_hunt_service", lambda:service)
    assert json.loads(tools.product_hunt.invoke({"operation":"posts"}))["status"] == "not_connected"
    connect(service)
    result = json.loads(tools.product_hunt.invoke({"operation":"posts","topic":"developer-tools","after":"cursor-1","limit":2}))
    assert result["posts"][0]["id"] == "1" and result["end_cursor"] == "cursor-2"
    assert TOKEN not in json.dumps(result)
    sent = json.loads(requests[-1].content)
    assert sent["variables"]["topic"] == "developer-tools"
    assert sent["variables"]["after"] == "cursor-1"
    assert "mutation" not in sent["query"].lower()
    assert service.read(ProductHuntRead(operation="post",slug="a-launch")).posts[0].name == "A launch"
    assert service.read(ProductHuntRead(operation="topics")).topics[0].slug == "developer-tools"
    with pytest.raises(ValueError):
        ProductHuntRead(limit=21)
    with pytest.raises(ValueError):
        ProductHuntRead(operation="post",slug='bad") { mutation')
    with pytest.raises(ValueError):
        ProductHuntRead(posted_after="2026-10-22")


def test_actions_confirm_opaque_reference_and_never_return_credentials(connection, tmp_path):
    service, keyring, _, requests = connection
    registry = PluginRegistry(Path(__file__).resolve().parents[2]/"plugins",state_path=tmp_path/"state.json")
    runtime = AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(product_hunt_contribution(service=service))
    reference = service.stage(TOKEN)
    request = AppActionRequest(action_id="producthunt.connection.connect",arguments={"credential_id":reference})
    context = AppActionContext(source="ui")
    pending = runtime.dispatch(request,context)
    assert pending.status == "confirmation_required" and keyring.value is None and not requests
    assert TOKEN not in pending.model_dump_json()
    result = runtime.confirm(pending.confirmation.token,request,context)
    assert result.status == "applied" and result.result["connection"]["connected"]
    assert TOKEN not in result.model_dump_json()
    denied = runtime.dispatch(AppActionRequest(action_id="producthunt.connection.verify"),AppActionContext(source="nlp"))
    assert denied.status == "unavailable"


def test_catalog_has_one_product_hunt_and_uses_real_connection_status(connection, tmp_path):
    service, _, _, _ = connection
    class Source:
        def discover(self):
            return [PluginSourceRecord(id=PLUGIN_ID,name="Product Hunt",version="legacy",description="App reference",category="Other",developer="OpenAI",source="openai_plugin",root=tmp_path)]
    registry = PluginRegistry(Path(__file__).resolve().parents[2]/"plugins",state_path=tmp_path/"state.json",sources=[Source()])
    items = registry.catalog(runtime_statuses=[{"id":PLUGIN_ID,"configured":False,"status":service.status().status}])
    selected = [p for p in items if p["id"]==PLUGIN_ID]
    assert len(selected)==1
    assert selected[0]["status"]=="not_connected" and not selected[0]["configured"]
    assert selected[0]["source"]=="portable" and selected[0]["tools"]==["product_hunt"]


def test_vellum_runtime_discovers_and_invokes_product_hunt(connection, monkeypatch):
    from agent.graph.agent import core_tool_registry
    from agent.tools import product_hunt as tools
    service, _, _, _ = connection
    monkeypatch.setattr(tools, "product_hunt_service", lambda: service)
    registry = core_tool_registry()
    assert "product_hunt" in registry.names()
    assert registry.get("product_hunt").access.value == "read"
    assert "token" not in registry.get("product_hunt").schema()["properties"]
    connect(service)
    answer = registry.invoke("product_hunt", {"operation":"posts", "limit":1}, agent_name="VellumAgent")
    assert json.loads(answer)["posts"][0]["name"] == "A launch"


def test_graphql_and_network_errors_do_not_echo_secrets():
    def unavailable(request):
        raise httpx.ConnectError(TOKEN)
    for handler in (
        lambda request: httpx.Response(200, json={"errors":[{"message":TOKEN}]}),
        unavailable,
    ):
        keyring = MemoryKeyring()
        service = ProductHuntService(keyring=keyring, enabled=lambda: True,
            client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs))
        with pytest.raises(ProductHuntError) as error:
            connect(service)
        assert TOKEN not in str(error.value) and keyring.value is None


def test_secret_transport_requires_local_origin_and_redacts_validation(connection, monkeypatch):
    from agent.plugins import product_hunt_api as api
    service, _, _, _ = connection
    monkeypatch.setattr(api,"product_hunt_service",lambda:service)
    app=FastAPI();app.include_router(api.router)
    with TestClient(app,base_url="http://127.0.0.1:8000",client=("127.0.0.1",1234)) as client:
        assert client.post("/plugins/producthunt/credentials/stage",json={"token":TOKEN}).status_code==403
        headers={"Origin":"http://127.0.0.1:5173","X-Vellum-ProductHunt":"1"}
        response=client.post("/plugins/producthunt/credentials/stage",headers=headers,json={"token":TOKEN,"unexpected":TOKEN})
        assert response.status_code==422 and TOKEN not in response.text
        response=client.post("/plugins/producthunt/credentials/stage",headers=headers,json={"token":TOKEN})
        assert response.status_code==200 and TOKEN not in response.text
        assert response.headers["cache-control"]=="no-store"
        assert service.status().configured is False


def test_account_reads_are_typed_paginated_and_do_not_send_mutations(connection):
    service, _, _, requests=connection
    connect(service)
    result=service.read(ProductHuntRead(operation="viewer"))
    assert result.user.username=="me" and result.data_visibility=="authenticated_account"
    assert service.status().access=="account_read" and service.status().account_access=="available"
    for feed in ("voted","made","submitted"):
        result=service.read(ProductHuntRead(operation="account_posts",account_feed=feed,limit=2))
        assert result.posts[0].id=="1" and result.account_feed==feed
        assert result.data_visibility=="authenticated_account"
    result=service.read(ProductHuntRead(operation="account_collections"))
    assert result.collections[0].id=="c1"
    assert service.read(ProductHuntRead(operation="user",username="@maker")).user.username=="maker"
    assert not any(json.loads(r.content)["query"].startswith("mutation") for r in requests)
    service.verify()
    assert service.status().account_access=="available"


def test_private_permission_failure_preserves_working_public_reads(connection):
    service, _, settings, _=connection
    connect(service);settings["account_code"]=403
    with pytest.raises(ProductHuntError) as error:
        service.read(ProductHuntRead(operation="viewer"))
    assert error.value.status=="insufficient_scope"
    assert service.status().connected and service.status().account_access=="needs_permission"
    assert service.read(ProductHuntRead()).posts[0].id=="1"


def test_follow_requires_bound_confirmation_and_verifies_provider_result(connection, monkeypatch, tmp_path):
    from agent.plugins import product_hunt_controls as controls
    service, _, settings, requests=connection
    connect(service);monkeypatch.setattr(controls,"product_hunt_service",lambda:service)
    registry=PluginRegistry(Path(__file__).resolve().parents[2]/"plugins",state_path=tmp_path/"state.json")
    runtime=AppActionRuntime(plugin_registry=registry);runtime.register_plugin_contribution(product_hunt_contribution(service=service))
    context=AppActionContext(source="nlp")
    request=AppActionRequest(action_id="producthunt.user.follow",arguments={"username":"maker"})
    pending=runtime.dispatch(request,context)
    assert pending.status=="confirmation_required" and "@maker" in pending.message
    assert pending.target.id=="maker-2" and TOKEN not in pending.model_dump_json()
    assert not any(json.loads(r.content)["query"].startswith("mutation") for r in requests)
    changed=runtime.confirm(pending.confirmation.token,request,AppActionContext(source="ui"))
    assert changed.status=="applied" and changed.result["following"] is True
    assert settings["following"] and service.status().write_access=="verified"
    assert json.loads(requests[-1].content)["variables"]["input"]=={"userId":"maker-2"}
    undone=AppActionRequest(action_id="producthunt.user.unfollow",arguments={"username":"maker"})
    review=runtime.dispatch(undone,context)
    result=runtime.confirm(review.confirmation.token,undone,AppActionContext(source="ui"))
    assert result.status=="applied" and not settings["following"]


@pytest.mark.parametrize("changed",["account","target","credential"])
def test_follow_rechecks_account_target_and_credential_before_mutation(connection,changed):
    service,keyring,settings,requests=connection
    connect(service);binding=service.prepare_follow("maker",following=True)
    if changed=="account":settings["actor_id"]="other-account"
    if changed=="target":settings["target_id"]="other-target"
    if changed=="credential":keyring.value=json.dumps({**json.loads(keyring.value),"token":"replacement-token"})
    with pytest.raises(ProductHuntError,match="changed"):
        service.set_following(ProductHuntFollow(username="maker"),following=True,binding=binding,confirmed=True)
    assert not any(json.loads(r.content)["query"].startswith("mutation") for r in requests)


def test_follow_permission_failure_never_claims_success_or_breaks_reads(connection):
    service,_,settings,requests=connection
    connect(service);binding=service.prepare_follow("maker",following=True)
    settings["write_code"]=403
    with pytest.raises(ProductHuntError) as error:
        service.set_following(ProductHuntFollow(username="maker"),following=True,binding=binding,confirmed=True)
    assert error.value.status=="approval_required" and TOKEN not in str(error.value)
    assert not settings["following"] and service.status().write_access=="approval_required"
    assert service.status().connected and service.read(ProductHuntRead()).posts


def test_follow_cannot_bypass_confirmation_or_duplicate_an_existing_follow(connection):
    service,_,settings,requests=connection
    connect(service);binding=service.prepare_follow("maker",following=True)
    with pytest.raises(ProductHuntError,match="confirm"):
        service.set_following(ProductHuntFollow(username="maker"),following=True,binding=binding)
    settings["following"]=True
    answer=service.set_following(ProductHuntFollow(username="maker"),following=True,binding=binding,confirmed=True)
    assert not answer["changed"]
    assert not any(json.loads(r.content)["query"].startswith("mutation") for r in requests)
