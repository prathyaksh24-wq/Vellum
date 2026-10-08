"""Music wording reaches typed interpretation before any provider action."""
import time
import pytest
from agent.agents.music import MusicAgent
from agent.contracts.music import MusicPlan
from test_music_agent import fixture_agent


@pytest.mark.parametrize('text', ['play a song from any playlist', 'play a song from my playslist', 'play a song. choose any playlist u want'])
def test_any_saved_playlist_wording_is_not_a_song_title(text):
    plan=MusicAgent._fast_plan(text)
    assert plan is not None and plan.operation=='play_saved_playlist'


@pytest.mark.parametrize('text',['paues','pasue','please paues','resuem'])
def test_whole_control_typo_reaches_music_control(text):
    agent=fixture_agent(planner=lambda *_:pytest.fail('A small control typo does not need a model'))[0]
    assert agent.can_handle(text)
    assert agent._fast_plan(text).operation==('resume' if text=='resuem' else 'pause')


def test_any_reply_after_saved_list_uses_saved_collection():
    agent,_,calls=fixture_agent(planner=lambda *_:pytest.fail('An explicit any reply is sufficient after listing playlists'))
    context=agent.thread_context(agent.answer('show my playlists'),{})
    assert agent.can_handle_with_context('any',context)
    result=agent.answer_with_context('any',context)
    assert result.status=='answered'
    assert any(args.get('context_uri')=='spotify:playlist:hindi' for _,args in calls)


def test_numeric_artist_shorthand_after_playlist_list_remains_an_artist():
    seen=[]
    def planner(query,skill):
        seen.append(query)
        return {'operation':'play_artist','artist':'6ix9ine'}
    agent,_,calls=fixture_agent(planner=planner,tracks=[{'uri':'spotify:track:gooba','name':'GOOBA','artists':[{'name':'6ix9ine'}]}])
    context=agent.thread_context(agent.answer('show my playlists'),{})
    result=agent.answer_with_context('play a song from 69',context)
    assert seen and 'list_playlists' in seen[-1]
    assert result.status=='answered'
    assert '6ix9ine' in result.summary
    assert ('spotify_playback',{'action':'play','uris':['spotify:track:gooba']}) in calls


def test_old_model_numeric_playlist_guess_cannot_override_user_artist_alias():
    agent,_,_=fixture_agent(planner=lambda *_:{'operation':'play_saved_playlist','query':'69'},tracks=[{'uri':'spotify:track:gooba','name':'GOOBA','artists':[{'name':'6ix9ine'}]}])
    context=agent.thread_context(agent.answer('show my playlists'),{})
    result=agent.answer_with_context('play a song from 69',context)
    assert result.status=='answered'
    assert result.structured_payload['music_plan']['operation']=='play_artist'
    assert result.structured_payload['music_plan']['artist']=='6ix9ine'


def test_explicit_numeric_playlist_does_not_use_artist_alias():
    agent,_,calls=fixture_agent(playlists=[{'id':'n69','name':'69','uri':'spotify:playlist:n69'}])
    result=agent.answer('play a song from my 69 playlist')
    assert result.status=='answered'
    assert ('spotify_playback',{'action':'play','context_uri':'spotify:playlist:n69'}) in calls


def test_artist_selection_never_plays_wrong_catalog_credit():
    agent,_,calls=fixture_agent(planner=lambda *_:{'operation':'play_artist','artist':'6ix9ine'},tracks=[{'uri':'spotify:track:other','name':'69','artists':[{'name':'Someone else'}]}])
    result=agent.answer('play a song from 69')
    assert result.status=='needs_fetch'
    assert not any(name=='spotify_playback' for name,_ in calls)


@pytest.mark.parametrize('text',[
    'Would you mind picking a tune from whichever of my playlists you fancy?',
    'Could you put Dynamite by BTS on for me?',
    'Would you lower the volume to 25 percent please?',
    'On YT music, play Blinding Lights',
    'rewind the song by 15 seconds',
])
def test_live_persona_wording_reaches_local_music_planning(text):
    assert fixture_agent()[0].can_handle(text)


def test_provider_first_wording_cannot_default_back_to_spotify():
    agent,_,calls=fixture_agent(planner=lambda *_:{'operation':'play_song','query':'Blinding Lights'})
    result=agent.answer('On YT music, play Blinding Lights')
    assert 'Youtube Music is not connected' in result.summary
    assert not calls


def test_explicit_emoji_source_survives_live_model_random_selection_error():
    agent,_,calls=fixture_agent(planner=lambda *_:{'operation':'play_saved_playlist','shuffle':True},playlists=[{'id':'heart','name':'❤️','uri':'spotify:playlist:heart'}])
    result=agent.answer('Could you play a song from my ❤️ playlist?')
    assert result.status=='answered'
    assert ('spotify_playback',{'action':'play','context_uri':'spotify:playlist:heart'}) in calls


def test_suggest_first_is_a_qualifier_not_another_action():
    agent,_,calls=fixture_agent(planner=lambda *_:{'operation':'suggest_music','query':'mellow music'})
    result=agent.answer('recommend a mellow song for winding down; suggest first')
    assert result.status=='needs_fetch' and result.action_request['action']=='music.play_suggestion'
    assert not any(name=='spotify_playback' for name,_ in calls)


def test_live_polite_absolute_volume_cannot_become_a_relative_drop_to_zero():
    plan=MusicAgent._fast_plan('Would you lower the volume to 25 percent please?')
    assert plan.operation=='set_volume' and plan.volume_percent==25
    assert plan.volume_delta_percent is None


def test_artist_search_uses_live_supported_page_size():
    agent,registry,calls=fixture_agent(planner=lambda *_:{'operation':'play_artist','artist':'6ix9ine'},tracks=[{'uri':'spotify:track:gooba','name':'GOOBA','artists':[{'name':'6ix9ine'}]}])
    original=registry.invoke
    def provider_limit(name,args,**kwargs):
        if name=='spotify_search' and args.get('limit',10)>10:
            raise ValueError('Spotify request failed with status 400')
        return original(name,args,**kwargs)
    registry.invoke=provider_limit
    assert agent.answer('play a song from 69').status=='answered'
    assert ('spotify_playback',{'action':'play','uris':['spotify:track:gooba']}) in calls


@pytest.mark.parametrize('alias',['yt music','YT music/player','yt player'])
def test_provider_alias_does_not_fall_back_to_spotify(alias):
    agent,_,calls=fixture_agent()
    result=agent.answer('play Blinding Lights on '+alias)
    assert 'Youtube Music is not connected' in result.summary
    assert calls==[]


def test_casual_music_language_uses_local_planner_and_keeps_provider_ids_out():
    seen=[]
    def planner(query,skill):
        seen.append(query)
        return {'operation':'play_playlist','query':'Hindi','source_uri':'spotify:playlist:invented'}
    agent,_,calls=fixture_agent(planner=planner)
    assert agent.can_handle('yo chuck on a tune from my Hindi playlist pls')
    result=agent.answer('yo chuck on a tune from my Hindi playlist pls')
    assert seen and result.status=='answered'
    assert any(args.get('context_uri')=='spotify:playlist:hindi' for _,args in calls)
    assert not any(args.get('context_uri')=='spotify:playlist:invented' for _,args in calls)


def test_literal_control_typo_title_keeps_song_identity():
    plan=MusicAgent._fast_plan('play "Paues"')
    assert plan.operation=='play_song' and plan.query=='Paues'


def test_expired_any_reply_does_not_start_saved_playback():
    agent=fixture_agent()[0]
    context={'last_plan':MusicPlan(operation='list_playlists').model_dump(),'at':time.time()-1801}
    assert not agent.can_handle_with_context('any',context)


def test_previous_track_is_distinct_from_restart_and_seek():
    agent,_,calls=fixture_agent(planner=lambda *_:pytest.fail('An explicit previous track needs no model'))
    result=agent.answer('go back to the previous song')
    assert result.status=='answered' and calls==[('spotify_playback',{'action':'previous'})]
    context=agent.thread_context(agent.answer('skip'),{})
    assert agent.can_handle_with_context('go back',context)
    result=agent.answer_with_context('go back',context)
    assert result.status=='answered' and calls[-1]==('spotify_playback',{'action':'previous'})
    assert agent._fast_plan('go back 45 secs').operation=='seek'
    assert agent._fast_plan('go back to the beginning of the song').operation=='restart'
    assert not agent.can_handle_with_context('go back',{'last_plan':MusicPlan(operation='next').model_dump(),'at':time.time()-1801})
