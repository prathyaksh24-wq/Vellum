"""Local library mutations through Vellum's existing plugin App Actions."""
import re
from pydantic import ValidationError
from agent.app_actions.models import AppActionDefinition, AppActionRequest
from agent.contracts.local_music import (MusicImportRequest, MusicDownloadRequest,
    MusicFileImportRequest, MusicJobRequest, LocalPlaybackRequest)
from agent.music_library import get_music_library, MusicLibraryError
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError


def local_music_contribution(library_provider=get_music_library):
    def execute(action, model, payload):
        try:
            request = model.model_validate(payload.get('arguments') or {})
            library = library_provider()
            if action == 'playlist': return library.import_playlist(request)
            if action == 'file': return library.import_file(request.file_token,request.entry_id)
            if action == 'download': return library.enqueue(request.entry_ids,request.source_url)
            if action == 'job': return library.manage_job(request.job_id,request.operation)
            return library.playback(request)
        except (MusicLibraryError, ValidationError) as exc:
            raise PluginContributionActionError('LOCAL_MUSIC_INVALID',str(exc)) from exc
        except Exception as exc:
            # Provider exceptions may contain signed URLs/headers. Keep those out
            # of receipts and application logs.
            raise PluginContributionActionError('LOCAL_MUSIC_SOURCE_UNAVAILABLE',
                'This music source could not be read. Reconnect its plugin, retry later, or import a playlist manifest and owned audio files.') from exc
    definitions = [
        ('playlist',MusicImportRequest,'Import playlist information','Import public or connected playlist information without acquiring audio.'),
        ('file',MusicFileImportRequest,'Import audio file','Copy a user-selected, unprotected audio file into the local library.'),
        ('download',MusicDownloadRequest,'Download selected recordings','Acquire explicitly selected, permitted YouTube recordings into the local library.'),
        ('job',MusicJobRequest,'Manage music download','Cancel or retry an individual local music acquisition.'),
        ('playback',LocalPlaybackRequest,'Control local playback','Queue a command for Vellum’s persistent local player; measured status reports application.'),
    ]
    return PluginContribution(owner='local_music',actions=tuple(PluginActionContribution(
        definition=AppActionDefinition(id='local_music.'+action,version='1',owner='local_music',plugin_id='local_music',
            title=title,description=description,scope='device',access_class='write',executor_location='server',
            supports_undo=False,idempotent=False,confirmation_rule='current_user_intent',
            argument_schema=model.model_json_schema(),result_schema={'type':'object','required':['changed']},
            ui_reference='music.local',audit_label='local_music.'+action,required_permissions=['local_music.library']),
        adapter=lambda payload, action=action, model=model: execute(action,model,payload),
        allowed_agents=frozenset({'VellumUI','VellumAgent','MusicAgent'}))
        for action,model,title,description in definitions))


def match_local_music_command(text):
    """Explicit local commands; bare transport follows an active local owner."""
    command = re.sub(r'^(?:please\s+)?(?:(?:can|could|would) you\s+)?','',text.strip(),flags=re.I).rstrip('.!?')
    explicit = re.search(r'\s+(?:on|in|from)\s+(?:my\s+)?local\s+(?:music|library|player)$',command,re.I)
    if explicit: command = command[:explicit.start()]
    play = re.fullmatch(r'play\s+(.+)',command,re.I)
    if explicit and play:
        return AppActionRequest(action_id='local_music.playback',arguments={'action':'play','query':play[1].strip()})
    from agent.contracts.music import match_music_control
    control = match_music_control(command)
    if control:
        if not explicit:
            state = get_music_library().snapshot().player
            if not state.owner_available or not state.observed.get('playing'): return None
        return AppActionRequest(action_id='local_music.playback',arguments={'action':control})
    return None
