"""Local library mutations through Vellum's existing plugin App Actions."""
import re
from pydantic import ValidationError
from agent.app_actions.models import AppActionDefinition, AppActionRequest
from agent.contracts.local_music import (MusicImportRequest, MusicDownloadRequest,
    MusicFileImportRequest, MusicJobRequest, MusicRemoveRequest, MusicRefreshRequest,
    LocalPlaybackRequest, MusicPlaylistListRequest, LocalNowPlayingRequest)
from agent.music_library import get_music_library, MusicLibraryError
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError


def local_music_contribution(library_provider=get_music_library):
    def execute(action, model, payload):
        try:
            request = model.model_validate(payload.get('arguments') or {})
            library = library_provider()
            if action == 'playlist': return library.import_playlist(request)
            if action == 'file': return library.import_file(request.file_token,request.entry_id)
            if action == 'download':
                return library.enqueue(request.entry_ids, request.source_url, collection_id=request.collection_id)
            if action == 'job': return library.manage_job(request.job_id,request.operation)
            if action == 'remove': return library.remove(request.collection_id,request.entry_id)
            if action == 'refresh': return library.refresh_playlist(request.collection_id)
            if action == 'list_playlists': return library.list_playlists()
            if action == 'now_playing': return library.now_playing(request.detail)
            return library.playback(request)
        except (MusicLibraryError, ValidationError) as exc:
            raise PluginContributionActionError('LOCAL_MUSIC_INVALID',str(exc)) from exc
        except Exception as exc:
            # Provider exceptions may contain signed URLs/headers. Keep those out
            # of receipts and application logs.
            raise PluginContributionActionError('LOCAL_MUSIC_SOURCE_UNAVAILABLE',
                'This music source could not be read. Reconnect its plugin, retry later, or import a playlist manifest and owned audio files.') from exc
    definitions = [
        ('playlist',MusicImportRequest,'Import music or a playlist','Import a manifest, prepare MP3s from a link, or add completed downloads to the library.'),
        ('file',MusicFileImportRequest,'Import audio file','Copy a user-selected, unprotected audio file into the local library.'),
        ('download',MusicDownloadRequest,'Download recordings','Queue missing MP3s for a local playlist or acquire an explicitly selected recording.'),
        ('job',MusicJobRequest,'Manage music download','Cancel or retry an individual local music acquisition.'),
        ('remove',MusicRemoveRequest,'Remove local music','Remove a playlist or song from the local library and cancel its downloads.'),
        ('refresh',MusicRefreshRequest,'Refresh playlist songs','Read the linked playlist again and add newly exposed songs while retaining downloaded audio.'),
        ('list_playlists',MusicPlaylistListRequest,'List Local Music playlists','Read the names and song counts of saved local playlists.'),
        ('playback',LocalPlaybackRequest,'Control local playback','Control Vellum’s local player: play, pause, skip, seek, volume, shuffle, repeat, like.'),
        ('now_playing',LocalNowPlayingRequest,'What is playing in Local Music','Read the current song, artist, album, playlist, like status and what plays next.'),
    ]
    return PluginContribution(owner='local_music',actions=tuple(PluginActionContribution(
        definition=AppActionDefinition(id='local_music.'+action,version='1',owner='local_music',plugin_id='local_music',
            title=title,description=description,scope='device',access_class='read' if action in {'list_playlists','now_playing'} else 'write',executor_location='server',
            supports_undo=False,idempotent=action in {'remove','list_playlists','now_playing'},confirmation_rule='current_user_intent',
            argument_schema=model.model_json_schema(),result_schema={'type':'object','required':['changed']},
            ui_reference='music.local',audit_label='local_music.'+action,required_permissions=['local_music.library']),
        adapter=lambda payload, action=action, model=model: execute(action,model,payload),
        allowed_agents=frozenset({'VellumUI','VellumAgent','MusicAgent'}))
        for action,model,title,description in definitions))


def match_local_music_command(text):
    """Explicit local commands; bare transport follows an active local owner."""
    from agent.contracts.music import match_music_control

    command = text.strip().rstrip('.!?')
    spans = list(re.finditer(r'\S+', command))
    words = [span[0].casefold() for span in spans]
    # Structure words are spell-corrected; titles keep the user's spelling.
    from agent.contracts.music import fix_music_word
    words = [fix_music_word(word) for word in words]
    start = int(words[:1] == ['please'])
    if words[start:start+1] in (['can'], ['could'], ['would']) and words[start+1:start+2] == ['you']:
        start += 2
    end = len(words)
    explicit = False
    for ending in (('local', 'music', 'player'), ('local', 'music', 'library'), ('local', 'music', 'playlists'),
                   ('local', 'music', 'playlist'), ('local', 'music'), ('local', 'library'), ('local', 'player'),
                   ('local', 'playlists'), ('local', 'playlist'), ('local', 'songs'), ('local', 'files')):
        suffix = end - len(ending)
        if suffix <= start or tuple(words[suffix:end]) != ending:
            continue
        if words[suffix-1] in {'my', 'the', 'vellum'}:
            suffix -= 1
        if suffix > start and words[suffix-1] in {'on', 'in', 'from', 'using'}:
            explicit, end = True, suffix-1
        elif suffix == start + 1 and words[start] in {'play', 'shuffle'}:
            # "play my local playlists", "play local music": any local song.
            return AppActionRequest(action_id='local_music.playback',arguments={'action':'play','pick_any':True})
        break
    local_library_mentioned = any(a == 'local' and b in {'music', 'library', 'playlist', 'playlists'}
                                  for a, b in zip(words, words[1:]))
    if local_library_mentioned and 'playlists' in words and words[start:start+1] in (
            ['what'], ['which'], ['show'], ['list'], ['tell'], ['do']):
        return AppActionRequest(action_id='local_music.list_playlists')
    if not explicit and words[-1:] == ['spotify']:
        return None
    control = match_music_control(' '.join(words[start:end]))
    if control:
        if not explicit:
            state = get_music_library().player_state()
            if not state.owner_available or not state.observed.get('playing'):
                return None
        return AppActionRequest(action_id='local_music.playback',arguments={'action':control})
    if words[start:start+1] == ['play']:
        title_start = start + 1
        if explicit and ' '.join(words[title_start:end]) in {'something', 'anything', 'a song', 'some music', 'a random song',
                'something random', 'anything random', 'some songs', 'songs', 'music', 'random', 'a random track', 'a track',
                'any song', 'random songs', 'a playlist', 'any playlist', 'a random playlist', 'one of my playlists',
                'some of my songs', 'my music', 'my songs', 'something good', 'anything good'}:
            return AppActionRequest(action_id='local_music.playback',arguments={'action':'play','pick_any':True})
        kind = title_start + int(words[title_start:title_start+1] in (['my'], ['the']))
        if kind+1 < end and words[kind] in {'playlist', 'song', 'track'}:
            title_start = kind+1
        if explicit and title_start == end:
            return AppActionRequest(action_id='local_music.playback',arguments={'action':'resume'})
        if title_start >= end:
            return None
        query = command[spans[title_start].start():spans[end-1].end()]
        if explicit or get_music_library().has_playlist(query):
            return AppActionRequest(action_id='local_music.playback',arguments={'action':'play','query':query})
    return None
