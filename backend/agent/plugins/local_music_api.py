"""Typed local music reads and file ingress; all user mutations use App Actions."""
import asyncio
from typing import Annotated
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from agent.app_actions.models import ActionReceipt, AppActionContext, AppActionRequest
from agent.contracts.local_music import (LocalMusicLibrary, LocalPlayerState, LocalPlayerReport,
    MusicDiscoveryPage, MusicAccountPlaylists)
from agent.music_library import MAX_AUDIO_BYTES, MusicLibraryError, get_music_library
from agent.plugins.registry import get_plugin_registry


def enabled():
    if not get_plugin_registry().is_enabled('local_music'):
        raise HTTPException(409,detail='Enable Local Music in Plugins to use this library.')


def trusted(request: Request):
    if not request.client or request.client.host not in {'127.0.0.1','::1'}:
        raise HTTPException(403,detail='Local music requires a loopback connection.')
    if request.url.hostname not in {'127.0.0.1','localhost','::1'}:
        raise HTTPException(403,detail='Local music requires a loopback host.')
    origin = request.headers.get('origin')
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {'http','https'} or parsed.hostname not in {'127.0.0.1','localhost','::1'} or parsed.port not in {5173,8000} or parsed.username or parsed.password:
            raise HTTPException(403,detail='Local music is available only to the Vellum workspace.')
    if request.method != 'GET' and request.headers.get('X-Vellum-Music') != '1':
        raise HTTPException(403,detail='Use the Vellum music controls.')
    # Browsers classify localhost -> 127.0.0.1 as cross-site. An explicitly
    # verified Vellum origin remains trusted; opaque/foreign requests do not.
    if not origin and request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403,detail='Use the Vellum music controls.')


router = APIRouter(prefix='/music/local',tags=['music'],dependencies=[Depends(enabled),Depends(trusted)])


@router.get('/library',response_model=LocalMusicLibrary)
def library(): return get_music_library().snapshot()


@router.get('/player',response_model=LocalPlayerState)
def player():
    return get_music_library().player_state()


class PlayerReportResponse(BaseModel):
    accepted: bool
    player: LocalPlayerState


@router.post('/player/report',response_model=PlayerReportResponse)
def report(body: LocalPlayerReport): return get_music_library().report(body)


@router.get('/audio/{entry_id}')
def audio(entry_id: str):
    try: path = get_music_library().asset_path(entry_id)
    except MusicLibraryError as exc: raise HTTPException(404,detail=str(exc)) from exc
    media = {'.m4a':'audio/mp4','.opus':'audio/ogg','.flac':'audio/flac','.webm':'audio/webm','.aac':'audio/aac','.ogg':'audio/ogg','.wav':'audio/wav','.mp3':'audio/mpeg'}
    return FileResponse(path,media_type=media[path.suffix],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get('/artwork/{entry_id}')
def artwork(entry_id: str):
    try:path=get_music_library().artwork_path(entry_id)
    except MusicLibraryError as exc:raise HTTPException(404,detail=str(exc)) from exc
    return FileResponse(path,media_type={'.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp'}[path.suffix],
        headers={'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'})


@router.get('/export/{collection_id}')
def export(collection_id: str):
    try: manifest = get_music_library().export(collection_id)
    except MusicLibraryError as exc: raise HTTPException(404,detail=str(exc)) from exc
    return JSONResponse(manifest,headers={'Content-Disposition':'attachment; filename="playlist.vellum-music.json"','Cache-Control':'no-store'})


@router.get('/search',response_model=MusicDiscoveryPage)
def search(query: str = Query(min_length=1,max_length=200)):
    try: return MusicDiscoveryPage(items=get_music_library().sources.discover(query))
    except Exception as exc:
        raise HTTPException(422,detail=str(exc) if isinstance(exc,MusicLibraryError) else 'Public music search is unavailable. Paste an exact YouTube song link instead.') from exc


@router.get('/account-playlists',response_model=MusicAccountPlaylists)
def account_playlists():
    """Official YouTube read-only OAuth, independent of the Music web session."""
    from agent.plugins.youtube_runtime import youtube_client
    if not get_plugin_registry().is_enabled('youtube'):
        return MusicAccountPlaylists(note='Enable and connect YouTube in Plugins to list your YouTube playlists.')
    try:
        client,items,token = youtube_client(),[],''
        for _ in range(20):
            page = client._api_get('/playlists',params={'part':'snippet','mine':'true','maxResults':50,**({'pageToken':token} if token else {})})
            items.extend({'name':str(row.get('snippet',{}).get('title') or 'Playlist')[:200],
                'url':'https://www.youtube.com/playlist?list='+row['id']} for row in page.get('items',[]) if row.get('id'))
            token = page.get('nextPageToken') or ''
            if not token: break
        return MusicAccountPlaylists(items=items,note='YouTube Data API playlists. Some YouTube Music-only collections may not be exposed.' + (' More playlists exist; the first 1,000 are shown.' if token else ''))
    except Exception:
        return MusicAccountPlaylists(note='Connect or reconnect YouTube in Plugins to read account playlists. Public playlist links can also be imported.')


@router.post('/files',response_model=ActionReceipt)
async def import_file(file: Annotated[UploadFile,File(...)], entry_id: Annotated[str,Form(max_length=64)] = ''):
    from agent.app_actions.runtime import get_app_action_runtime
    try:
        content = await file.read(MAX_AUDIO_BYTES + 1)
        token = await asyncio.to_thread(get_music_library().stage_file,str(file.filename or ''),content)
    except MusicLibraryError as exc: raise HTTPException(422,detail=str(exc)) from exc
    finally: await file.close()
    return await asyncio.to_thread(get_app_action_runtime().dispatch,
        AppActionRequest(action_id='local_music.file',arguments={'file_token':token,'entry_id':entry_id}),AppActionContext(source='ui'))
