"""Real App Action confirmation and connector paths against a disposable Spotify account."""
import json
import time
from pathlib import Path

import httpx
import pytest

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.plugins import spotify_controls, spotify_runtime
from agent.plugins.registry import PluginRegistry


@pytest.fixture
def editing(tmp_path, monkeypatch):
    store = spotify_runtime._spotify_module.auth.SpotifyAuthStore(tmp_path/'spotify')
    store.save_tokens({'access_token':'fake-access','refresh_token':'fake-refresh','client_id':'fake-client','expires_at':time.time()+3600})
    state = {'account':'Listener','owner':'Listener','name':'Tamil','description':'Old description','snapshot':'s1','saved':True,'tracks':['spotify:track:First','spotify:track:First','spotify:track:Second'],'ignore_write':False}
    writes = []
    def handle(request):
        path = request.url.path.removeprefix('/v1')
        if request.method == 'GET':
            if path.startswith('/tracks/'): return httpx.Response(200,json={'uri':'spotify:track:'+path.split('/')[-1],'name':path.split('/')[-1],'artists':[{'name':'Original Artist'}]})
            if path == '/me': return httpx.Response(200,json={'id':state['account']})
            if path == '/me/playlists': return httpx.Response(200,json={'items':[{'id':'Tamil','name':state['name']}],'total':1})
            if path == '/me/library/contains': return httpx.Response(200,json=[state['saved']])
            if path == '/playlists/Tamil': return httpx.Response(200,json={'id':'Tamil','name':state['name'],'description':state['description'],'owner':{'id':state['owner']},'snapshot_id':state['snapshot']})
            if path == '/playlists/Tamil/items': return httpx.Response(200,json={'items':[{'item':{'uri':uri}} for uri in state['tracks']],'total':len(state['tracks'])})
        writes.append((request.method,path,json.loads(request.content or b'{}')))
        if not state['ignore_write']:
            if path == '/playlists/Tamil' and request.method == 'PUT': state.update(json.loads(request.content))
            if path == '/me/library' and request.method == 'DELETE': state['saved'] = False
            if path == '/playlists/Tamil/items':
                body=json.loads(request.content)
                if request.method == 'POST': state['tracks'].extend(body['uris'])
                else: state['tracks']=[uri for uri in state['tracks'] if uri not in {row['uri'] for row in body['items']}]
                state['snapshot']='s2'
        return httpx.Response(200,json={'snapshot_id':state['snapshot']})
    client = spotify_runtime._spotify_module.tools.SpotifyClient(store,transport=httpx.MockTransport(handle))
    monkeypatch.setattr(spotify_controls,'spotify_client',lambda:client)
    registry=PluginRegistry(Path(__file__).resolve().parents[2]/'plugins',state_path=tmp_path/'plugin-state.json')
    runtime=AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(spotify_controls.spotify_plugin_contribution(authenticated=lambda:True))
    return runtime,state,writes


def request(**kwargs):
    return AppActionRequest(action_id='spotify.playlist.edit',arguments=kwargs)


def test_rename_selected_playlist_requires_confirmation_and_pins_the_target(editing):
    runtime,state,writes=editing
    action=runtime.match_submission('change the name of this playlist to Road Trip')
    assert action.action_id == 'spotify.playlist.edit'
    context=AppActionContext(source='nlp',music_collection_uri='spotify:playlist:Tamil')
    review=runtime.dispatch(action,context)
    assert review.status=='confirmation_required' and writes==[]
    assert review.target.id=='Tamil' and 'Tamil to Road Trip' in review.message
    receipt=runtime.confirm(review.confirmation.token,action,AppActionContext(source='nlp',music_collection_uri='spotify:playlist:Different'))
    assert receipt.status=='applied' and state['name']=='Road Trip'
    assert writes==[('PUT','/playlists/Tamil',{'name':'Road Trip'})]
    assert receipt.target.id=='Tamil'


@pytest.mark.parametrize('message',[
    'rename my Tamil playlist to Chill',
    'please change the name of my Tamil playlist to Chill on Spotify',
    'could you rename playlist Tamil to Chill',
    "change my Tamil playlist's name to Chill",
])
def test_named_rename_wordings_resolve_the_saved_identity(editing,message):
    runtime,state,writes=editing
    action=runtime.match_submission(message)
    assert action.arguments['playlist_name']=='Tamil'
    review=runtime.dispatch(action,AppActionContext(source='nlp'))
    assert review.status=='confirmation_required' and review.target.id=='Tamil' and writes==[]


def test_no_selected_playlist_or_ambiguous_name_never_writes(editing):
    runtime,state,writes=editing
    review=runtime.dispatch(request(operation='update_details',name='Chill'),AppActionContext(source='nlp'))
    assert review.status=='failed' and review.error_code=='PLAYLIST_TARGET_REQUIRED' and writes==[]
    review=runtime.dispatch(request(operation='update_details',playlist_name='Not in library',name='Chill'),AppActionContext(source='nlp'))
    assert review.status=='failed' and writes==[]


@pytest.mark.parametrize('field,value',[('account','Other'),('snapshot','s2'),('name','Renamed elsewhere'),('owner','Other')])
def test_changed_account_revision_name_or_owner_blocks_confirmed_write(editing,field,value):
    runtime,state,writes=editing
    action=request(operation='update_details',playlist_id='Tamil',name='Chill')
    context=AppActionContext(source='ui')
    review=runtime.dispatch(action,context)
    state[field]=value
    receipt=runtime.confirm(review.confirmation.token,action,context)
    assert receipt.status=='failed' and writes==[]


def test_followed_playlist_cannot_be_renamed_but_can_be_removed_from_library(editing):
    runtime,state,writes=editing
    state['owner']='SomeoneElse'
    context=AppActionContext(source='ui')
    denied=runtime.dispatch(request(operation='update_details',playlist_id='Tamil',name='Chill'),context)
    assert denied.error_code=='PLAYLIST_NOT_OWNED' and writes==[]
    action=request(operation='remove',playlist_id='Tamil')
    review=runtime.dispatch(action,context)
    receipt=runtime.confirm(review.confirmation.token,action,context)
    assert receipt.status=='applied' and not state['saved']
    assert writes[0][:2]==('DELETE','/me/library')
    assert state['tracks']==['spotify:track:First','spotify:track:First','spotify:track:Second']


@pytest.mark.parametrize('operation,uri',[('add_items','spotify:track:New'),('remove_items','spotify:track:First')])
def test_song_edits_verify_provider_contents_and_remove_duplicate_occurrences(editing,operation,uri):
    runtime,state,writes=editing
    action=request(operation=operation,playlist_id='Tamil',uris=[uri])
    context=AppActionContext(source='ui')
    review=runtime.dispatch(action,context)
    assert writes==[]
    receipt=runtime.confirm(review.confirmation.token,action,context)
    assert receipt.status=='applied'
    assert (uri in state['tracks']) == (operation=='add_items')


def test_unverified_response_and_cancel_never_claim_success(editing):
    runtime,state,writes=editing
    context=AppActionContext(source='ui')
    action=request(operation='update_details',playlist_id='Tamil',name='Chill')
    review=runtime.dispatch(action,context)
    cancelled=runtime.cancel(review.confirmation.token,context)
    assert cancelled.status=='cancelled' and writes==[]
    review=runtime.dispatch(action,context)
    state['ignore_write']=True
    receipt=runtime.confirm(review.confirmation.token,action,context)
    assert receipt.status=='failed' and receipt.error_code=='PLAYLIST_EDIT_UNVERIFIED'


def test_playlist_edit_matcher_does_not_intercept_conversation_renames(editing):
    runtime,state,writes=editing
    assert spotify_controls.match_spotify_playlist_command('rename this chat to Music') is None


def test_confirmed_arguments_cannot_be_substituted(editing):
    runtime,state,writes=editing
    context=AppActionContext(source='ui')
    review=runtime.dispatch(request(operation='update_details',playlist_id='Tamil',name='Chill'),context)
    result=runtime.confirm(review.confirmation.token,request(operation='remove',playlist_id='Tamil'),context)
    assert result.error_code=='CONFIRMATION_MISMATCH' and writes==[]


@pytest.mark.asyncio
async def test_typed_playlist_rename_stream_uses_selected_collection_without_model(editing,monkeypatch):
    from types import SimpleNamespace
    from agent import api
    import agent.skills.curator_runtime as curator_runtime
    runtime,state,writes = editing
    monkeypatch.setattr(api,'_app_action_runtime',runtime)
    monkeypatch.setattr(curator_runtime,'get_curator_runtime',lambda:SimpleNamespace(mark_activity=lambda:None))
    async def passthrough(stream,_audit):
        async for chunk in stream: yield chunk
    async def no_model(**kwargs):
        raise AssertionError('A complete playlist edit must use App Actions')
        yield ''
    monkeypatch.setattr(api,'_audited_turn_stream',passthrough)
    monkeypatch.setattr(api,'_stream_agent_turn',no_model)
    response = await api.chat_stream(api.ChatRequest(message='change the name of this playlist to Road Trip',thread_id='music-edit',
        action_context=AppActionContext(source='ui',music_collection_uri='spotify:playlist:Tamil')))
    body = ''.join([chunk async for chunk in response.body_iterator])
    assert 'confirmation_required' in body and 'Rename Tamil to Road Trip?' in body
    assert writes == [] and state['name'] == 'Tamil'
