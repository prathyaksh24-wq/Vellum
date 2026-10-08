import json
import time
from uuid import uuid4
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agent import api
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.plugins import spotify_controls
from agent.plugins import spotify_runtime
from agent.plugins.registry import PluginRegistry
from plugins.connectors.spotify.auth import SpotifyAuthStore, DEFAULT_SCOPES

# Exercise the exact portable module namespace used by the API and agent.
SpotifyClient = spotify_runtime._spotify_module.tools.SpotifyClient
SpotifyAuthError = spotify_runtime.SpotifyAuthError
SpotifyNoActiveDevice = spotify_runtime._spotify_module.tools.SpotifyNoActiveDevice
spotify_playback = spotify_runtime.spotify_playback
spotify_queue = spotify_runtime._spotify_module.tools.spotify_queue


HEADERS = {"Origin": "http://127.0.0.1:5173", "X-Vellum-Spotify-Playback": "1"}


@pytest.fixture
def service(tmp_path, monkeypatch):
    store = SpotifyAuthStore(tmp_path / "spotify")
    store.save_tokens({"client_id": "public-client", "access_token": "sdk-access",
                       "refresh_token": "private-refresh", "expires_at": time.time() + 3600,
                       "scope": " ".join(DEFAULT_SCOPES)})
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(204)
    client = SpotifyClient(store, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(api, "_spotify_store", lambda: store)
    monkeypatch.setattr(api, "_spotify_client", lambda: client)
    monkeypatch.setattr(spotify_controls, "spotify_client", lambda: client)
    monkeypatch.setattr(api, "start_scheduler", lambda: None)
    monkeypatch.setattr(api, "start_vault_watcher", lambda: None)
    return client, requests


def test_token_only_reaches_trusted_local_playback_view_and_is_not_cached(service):
    with TestClient(api.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as web:
        response = web.post("/api/plugins/spotify/playback/token", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["access_token"] == "sdk-access"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
        assert "private-refresh" not in response.text
        assert "public-client" not in response.text
        for headers in ({}, {"Origin": HEADERS["Origin"]}, {**HEADERS, "Origin": "https://evil.example"},
                        {**HEADERS, "Origin": "http://127.0.0.1:9999"}, {**HEADERS, "Origin": "null"}):
            denied = web.post("/api/plugins/spotify/playback/token", headers=headers)
            assert denied.status_code == 403
            assert "sdk-access" not in denied.text
    with TestClient(api.app, base_url="http://evil.example", client=("127.0.0.1", 50000)) as web:
        assert web.post("/api/plugins/spotify/playback/token", headers=HEADERS).status_code == 403
    with TestClient(api.app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 50000)) as web:
        assert web.post("/api/plugins/spotify/playback/token", headers=HEADERS).status_code == 403


def test_old_authorization_requires_new_consent(service):
    client, _ = service
    saved = client.auth_store.load_tokens()
    saved["scope"] = "user-read-private"
    client.auth_store.save_tokens(saved)
    with pytest.raises(SpotifyAuthError, match="Reconnect"):
        client.playback_token()
    with TestClient(api.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as web:
        result = web.post("/api/plugins/spotify/oauth/start", json={})
        assert result.status_code == 200
        assert client.auth_store.consume_flow(client.auth_store._read_json(client.auth_store.flow_path)["state"])["client_id"] == "public-client"


def test_typed_connection_reuses_saved_app_and_retains_playback_actions(service, tmp_path):
    client, _ = service
    saved = client.auth_store.load_tokens()
    saved["client_id"] = "savedpublicclient"
    client.auth_store.save_tokens(saved)
    controls = spotify_controls.SpotifyConnectionService(
        store_provider=lambda: client.auth_store,
        pkce_provider=lambda: ("verifier", "challenge"),
        state_factory=lambda: "typed-reconnect",
        authorization_url_provider=lambda **kwargs: "https://accounts.spotify.com/authorize",
    )
    contribution = spotify_controls.spotify_plugin_contribution(controls, authenticated=lambda: True)
    assert {action.definition.id for action in contribution.actions} == {
        "spotify.connection.start", "spotify.connection.disconnect",
        "spotify.playback.control", "spotify.playback.session",
    }
    runtime = AppActionRuntime(plugin_registry=PluginRegistry(
        Path(__file__).resolve().parents[2] / "plugins", state_path=tmp_path / "plugin-state.json"))
    runtime.register_plugin_contribution(contribution)
    receipt = runtime.dispatch(AppActionRequest(
        action_id="spotify.connection.start", arguments={"reuse_existing_client": True}),
        AppActionContext(source="ui"))
    assert receipt.status == "applied"
    assert receipt.result["changed"] is True
    assert client.auth_store.consume_flow("typed-reconnect")["client_id"] == "savedpublicclient"


def test_sdk_rejected_token_refresh_is_coalesced_and_keeps_scopes(service):
    client, _ = service
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "rotated-sdk-access", "expires_in": 3600, "refresh_token": "rotated-refresh"})
    client.transport = httpx.MockTransport(handle)
    first = client.playback_token(force_refresh=True)
    second = client.playback_token(force_refresh=True)
    assert first["access_token"] == second["access_token"] == "rotated-sdk-access"
    assert len(calls) == 1
    assert client.auth_store.load_tokens()["scope"] == " ".join(DEFAULT_SCOPES)
    assert client.auth_store.load_tokens()["refresh_token"] == "rotated-refresh"


def test_device_registration_requires_owner_and_valid_contract(service):
    client, _ = service
    owner = str(uuid4())
    with TestClient(api.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as web:
        body = {"owner_id": owner, "device_id": "vellum-device"}
        assert web.post("/api/plugins/spotify/playback/device", json=body, headers=HEADERS).status_code == 409
        client.claim_web_player(owner)
        assert web.post("/api/plugins/spotify/playback/device", json=body, headers=HEADERS).json() == {"status": "ready"}
        assert web.post("/api/plugins/spotify/playback/device", json={**body, "access_token": "bad"}, headers=HEADERS).status_code == 422
        assert client.preferred_device_id() == "vellum-device"


@pytest.mark.parametrize("handler,args", [
    (spotify_playback, {"action": "play", "uris": ["spotify:track:example"]}),
    (spotify_playback, {"action": "next"}), (spotify_playback, {"action": "pause"}),
    (spotify_playback, {"action": "seek", "position_ms": 100}),
    (spotify_playback, {"action": "set_shuffle", "shuffle": True}),
    (spotify_playback, {"action": "set_repeat", "state": "context"}),
    (spotify_queue, {"action": "add", "uri": "spotify:track:example"}),
])
def test_existing_tools_target_vellum_and_do_not_require_external_devices(service, handler, args):
    client, requests = service
    owner = str(uuid4())
    client.claim_web_player(owner)
    client.update_web_player(owner, "vellum-device")
    assert json.loads(handler(args, service=client))["ok"]
    assert len(requests) == 1
    assert requests[0].url.params["device_id"] == "vellum-device"
    assert json.loads(handler({**args, "device_id": "explicit-speaker"}, service=client))["ok"]
    assert requests[-1].url.params["device_id"] == "explicit-speaker"
    client.update_web_player(owner, "")
    before = len(requests)
    result = json.loads(handler(args, service=client))
    assert result["error"]["code"] == "no_active_device"
    assert len(requests) == before  # No random external-device fallback.


def test_local_volume_waits_for_exact_sdk_ack_without_web_api_write(service):
    from concurrent.futures import ThreadPoolExecutor
    client, requests = service
    owner=str(uuid4())
    client.claim_web_player(owner); client.update_web_player(owner,'vellum-device')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(spotify_playback,{'action':'set_volume','volume_percent':17},service=client)
        response={}
        for _ in range(100):
            response=client.update_web_player(owner,'vellum-device')
            if response.get('volume_request'):break
            time.sleep(.005)
        command=response['volume_request']
        assert command['percent']==17 and not future.done()
        client.update_web_player(owner,'vellum-device',volume_ack='wrong',volume_percent=17)
        assert not future.done()
        client.update_web_player(owner,'vellum-device',volume_ack=command['id'],volume_percent=17)
        assert json.loads(future.result(timeout=1))['ok']
    assert not requests
    assert json.loads(spotify_playback({'action':'set_volume','volume_percent':30,'device_id':'speaker'},service=client))['ok']
    assert requests[-1].url.params['device_id']=='speaker'


def test_fresh_sdk_state_wins_then_expires_and_cannot_cross_owner(service,monkeypatch):
    client, requests=service
    now=[1.0]; monkeypatch.setattr(time,'monotonic',lambda:now[0])
    owner=str(uuid4()); client.claim_web_player(owner)
    observation={'track':{'uri':'spotify:track:hindi','name':'Hindi song'},'artists':['Artist'],'is_playing':True}
    client.update_web_player(owner,'vellum-device',observation=observation,volume_percent=23)
    assert client.get_player()['track']['name']=='Hindi song'
    assert client.get_player()['device']['volume_percent']==23
    assert not requests
    with pytest.raises(SpotifyNoActiveDevice):
        client.update_web_player('other','vellum-device',observation={'track':{'name':'Wrong'}})
    now[0]+=6
    assert client.local_player_state() is None
    assert client.get_player()['track'] is None
    assert len(requests)==1
    client.update_web_player(owner,'different-device')
    assert client.local_player_state() is None


def test_fresh_sdk_volume_remains_controllable_without_a_track_snapshot(service,monkeypatch):
    client,_=service
    owner=str(uuid4()); client.claim_web_player(owner)
    client.update_web_player(owner,'vellum-device',volume_percent=50)
    # Spotify can omit the active device when paused; local audio volume still exists.
    monkeypatch.setattr(client,'request',lambda *args,**kwargs:{})
    state=client.get_player()
    assert state['track'] is None
    assert state['device']['id']=='vellum-device'
    assert state['device']['volume_percent']==50
    monkeypatch.setattr(client,'request',lambda *args,**kwargs:{'device':{'id':'speaker','volume_percent':17}})
    assert client.get_player()['device']['volume_percent']==17
    client._web_player['volume_observed_at']-=6
    monkeypatch.setattr(client,'request',lambda *args,**kwargs:{})
    assert client.get_player()['device'] is None


def test_observation_uses_existing_trusted_device_contract(service):
    client,_=service; owner=str(uuid4()); client.claim_web_player(owner)
    body={'owner_id':owner,'device_id':'vellum-device','observation':{
        'track':{'id':'one','uri':'spotify:track:one','name':'Song'},'artists':['Artist'],'is_playing':True},'volume_percent':23}
    with TestClient(api.app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as web:
        assert web.post('/api/plugins/spotify/playback/device',json=body,headers={}).status_code==403
        assert web.post('/api/plugins/spotify/playback/device',json=body,headers=HEADERS).status_code==200
        assert client.get_player()['device']['volume_percent']==23
        bad={**body,'observation':{**body['observation'],'secret':'never accepted'}}
        assert web.post('/api/plugins/spotify/playback/device',json=bad,headers=HEADERS).status_code==422


def test_expired_window_cannot_steal_device_or_release_new_owner(service, monkeypatch):
    client, _ = service
    owner, second = str(uuid4()), str(uuid4())
    now = [1.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    client.claim_web_player(owner)
    client.update_web_player(owner, "first-device")
    with pytest.raises(SpotifyNoActiveDevice, match="another window"):
        client.claim_web_player(second)
    now[0] += 91
    with pytest.raises(SpotifyNoActiveDevice, match="not ready"):
        client.preferred_device_id()
    client.claim_web_player(second)
    client.update_web_player(second, "second-device")
    client.release_web_player(owner)
    with pytest.raises(SpotifyNoActiveDevice):
        client.update_web_player(owner, "first-device")
    assert client.preferred_device_id() == "second-device"


def test_typed_activation_is_a_ui_only_plugin_action(service, tmp_path):
    registry = PluginRegistry(Path(__file__).resolve().parents[2] / "plugins", state_path=tmp_path / "plugin-state.json")
    runtime = AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(spotify_controls.spotify_plugin_contribution())
    request = AppActionRequest(action_id="spotify.playback.session", arguments={"owner_id": str(uuid4()), "operation": "enable"})
    receipt = runtime.dispatch(request, AppActionContext(source="ui"))
    assert receipt.status == "applied"
    assert receipt.result["status"] == "connecting"
    denied = runtime.dispatch(request.model_copy(update={"request_id": "different"}), AppActionContext(source="nlp", active_agent="VellumAgent"))
    assert denied.status == "unavailable"
    assert "sdk-access" not in receipt.model_dump_json()


@pytest.mark.parametrize("message, expected", [
    ("pause Spotify", {"action": "pause"}),
])
def test_explicit_music_commands_use_actions_instead_of_selected_specialists(service, tmp_path, message, expected):
    registry = PluginRegistry(Path(__file__).resolve().parents[2] / "plugins", state_path=tmp_path / "plugin-state.json")
    runtime = AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(spotify_controls.spotify_plugin_contribution())
    turn = runtime.plan_submission(message)
    assert not turn.conversation_message
    assert len(turn.actions) == 1
    assert turn.actions[0].action_id == "spotify.playback.control"
    assert turn.actions[0].arguments == expected


def test_next_control_issues_one_request_to_the_selected_vellum_device(service, tmp_path):
    client, requests = service
    owner = str(uuid4())
    client.claim_web_player(owner)
    client.update_web_player(owner, "vellum-device")
    registry = PluginRegistry(Path(__file__).resolve().parents[2] / "plugins", state_path=tmp_path / "plugin-state.json")
    runtime = AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(spotify_controls.spotify_plugin_contribution())
    request = AppActionRequest(action_id="spotify.playback.control", arguments={"action": "next"})
    context = AppActionContext(source="ui")
    receipt = runtime.dispatch(request, context)
    assert receipt.status == "applied"
    assert len(requests) == 1
    assert requests[0].url.params["device_id"] == "vellum-device"


def test_song_title_search_plays_one_resolved_uri_and_keeps_private_queries_local(service):
    client, requests = service
    owner = str(uuid4())
    client.claim_web_player(owner)
    client.update_web_player(owner, "vellum-device")
    def handle(request):
        requests.append(request)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"tracks": {"items": [
                {"name": "Senorita remix", "uri": "spotify:track:remix", "artists": []},
                {"name": "Señorita", "uri": "spotify:track:original", "artists": [{"name": "Shawn Mendes"}]},
            ]}})
        return httpx.Response(204)
    client.transport = httpx.MockTransport(handle)
    result = spotify_controls.execute_spotify_control({"arguments": {"action": "play", "query": "senorita"}})
    assert result["changed"]
    assert "Señorita" in result["_message"]
    assert [r.method for r in requests] == ["GET", "PUT"]
    assert json.loads(requests[1].content)["uris"] == ["spotify:track:original"]
    before = len(requests)
    with pytest.raises(spotify_controls.PluginContributionActionError, match="Withheld"):
        spotify_controls.execute_spotify_control({"arguments": {"action": "play", "query": "private@example.com"}})
    assert len(requests) == before


def test_bare_pause_is_music_only_for_a_selected_vellum_player(service):
    client, requests = service
    assert spotify_controls.match_spotify_command("pause") is None
    client.claim_web_player(str(uuid4()))
    assert spotify_controls.match_spotify_command("pause").arguments == {"action": "pause"}
    assert spotify_controls.match_spotify_command("search X posts about Spotify") is None
    assert spotify_controls.match_spotify_command("play from my Hindi playlist on Spotify") is None


@pytest.mark.parametrize("separator", [" ", "\t", "\u2003"])
def test_spotify_control_with_long_whitespace_runs_promptly(service, separator):
    start = time.perf_counter()
    assert spotify_controls.match_spotify_command("pause" + separator * 20_000 + "unrelated") is None
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize("message", [
    "Please could you please pause on Spotify!",
    "PLEASE\tCOULD\nYOU PLEASE\u2003PAUSE ON\tSPOTIFY?",
    "skip\u2003this\tsong spotify.",
])
def test_spotify_control_preserves_polite_case_and_whitespace_support(service, message):
    request = spotify_controls.match_spotify_command(message)
    assert request.action_id == "spotify.playback.control"
    assert request.arguments == {"action": "next" if message.startswith("skip") else "pause"}


def test_compound_pause_and_play_stays_in_the_same_ordered_action_turn(service, tmp_path):
    client, _ = service
    client.claim_web_player(str(uuid4()))
    registry = PluginRegistry(Path(__file__).resolve().parents[2] / "plugins", state_path=tmp_path / "plugin-state.json")
    runtime = AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(spotify_controls.spotify_plugin_contribution())
    turn = runtime.plan_submission("pause and play senorita on spotify")
    assert turn.is_mixed
    assert turn.conversation_message == "play senorita on spotify"
    assert [request.arguments for request in turn.actions] == [{"action":"pause"}]


def test_chat_stream_executes_music_control_even_with_a_selected_x_agent(service, monkeypatch):
    client, requests = service
    owner = str(uuid4())
    client.claim_web_player(owner)
    client.update_web_player(owner, "vellum-device")
    with TestClient(api.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as web:
        response = web.post("/api/chat/stream", json={"message":"pause Spotify", "thread_id":"spotify-qa-action-only", "store":False,
            "action_context":{"source":"nlp", "active_agent":"XAgent"}})
    assert response.status_code == 200
    assert 'spotify.playback.control' in response.text
    assert 'Spotify paused.' in response.text
    assert len(requests) == 1


def test_skip_turn_is_checkpointed_with_its_own_acknowledgement(service, monkeypatch):
    client, requests = service
    owner = str(uuid4())
    client.claim_web_player(owner)
    client.update_web_player(owner, "vellum-device")
    checkpoints = []
    async def checkpoint(message, answer, thread_id, model):
        checkpoints.append((message, answer, thread_id))
    monkeypatch.setattr(api, "_checkpoint_specialist_exchange", checkpoint)
    with TestClient(api.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as web:
        response = web.post("/api/chat/stream", json={"message":"skip", "thread_id":"music-skip-qa", "store":False})
    assert response.status_code == 200
    assert checkpoints == [("skip", "Skipped to the next track.", "music-skip-qa")]
    assert len(requests) == 1


def test_app_action_skip_retains_navigation_for_short_music_followup(service,monkeypatch,tmp_path):
    from test_music_compound_actions import compound_dispatcher
    dispatcher,calls,_,state=compound_dispatcher(tmp_path)
    monkeypatch.setattr(api,'_live_dispatcher',dispatcher)
    client,requests=service
    owner=str(uuid4());client.claim_web_player(owner);client.update_web_player(owner,'vellum-device')
    with TestClient(api.app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as web:
        result=web.post('/api/chat/stream',json={'message':'skip','thread_id':'compound','store':False})
        assert result.status_code==200
        context=state.get_specialist_context('compound','MusicAgent')
        assert context.get('last_plan',{}).get('operation')=='next'
        result=web.post('/api/chat/stream',json={'message':'go back','thread_id':'compound','store':False})
        assert 'Previous track requested' in result.text
        assert any(name=='spotify_playback' and args['action']=='previous' for name,args in calls)
        assert not any(args.get('action')=='seek' for _,args in calls)
        result=web.post('/api/chat/stream',json={'message':'go back to the previous song','thread_id':'compound','store':False})
        assert 'Previous track requested' in result.text
        assert requests[-1].url.path.endswith('/player/previous')


def test_playback_health_is_bounded_and_cannot_accept_arbitrary_diagnostic_content(service):
    client, requests = service
    owner = str(uuid4())
    client.claim_web_player(owner)
    for index in range(50):
        client.update_web_player(owner, "vellum-device", [{"event":"state", "at_ms":index, "position_ms":index*1000}])
    status = client.web_playback_status()
    assert len(status["diagnostics"]) == 32
    assert "sdk-access" not in json.dumps(status)
    spotify_playback({"action":"next"}, service=client)
    assert client.web_playback_status()["commands"] == {"POST /me/player/next":1}
    with pytest.raises(ValueError):
        spotify_controls.SpotifyPlaybackDeviceRequest(owner_id=owner, diagnostics=[{"event":"state", "at_ms":0, "access_token":"secret"}])
