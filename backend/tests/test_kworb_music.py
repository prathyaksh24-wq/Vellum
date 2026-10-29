from dataclasses import replace

import pytest
from pydantic import ValidationError

from agent.agents.music import MusicAgent
from agent.tools.capabilities.kworb_service import KworbCapabilityService, KworbRequest
from agent.tools.registry import ToolPermissionError
from test_music_agent import fixture_agent


LISTENERS = '''<table><tr><th>#</th><th>Artist</th><th>Listeners</th></tr>
<tr><td>14</td><td><a href="artist/guetta_songs.html">David Guetta</a></td><td>83,220,280</td><td>-107,842</td><td>4</td><td>89,315,609</td></tr>
<tr><td>22</td><td><a href="artist/drake_songs.html">Drake</a></td><td>80,000,000</td><td>123</td><td>1</td><td>90,000,000</td></tr></table>'''
INDEX = '''<table><tr><td>India</td><td><a href="country/in_daily.html">Daily</a><a href="country/in_weekly.html">Weekly</a></td></tr>
<tr><td>United States</td><td><a href="country/us_daily.html">Daily</a></td></tr>
<tr><td>Japan</td><td><a href="country/jp_daily.html">Daily</a></td></tr>
<tr><td>France</td><td><a href="country/fr_daily.html">Daily</a></td></tr></table>'''
CHART = '''<h1>Spotify Chart - India - 2026/10/04</h1><table>
<tr><th>Pos</th><th>P+</th><th>Artist and Title</th></tr>
<tr><td>1</td><td>=</td><td>First Artist - <a href="../track/first.html">First Song</a></td></tr>
<tr><td>2</td><td>+1</td><td>Second Artist - <a href="https://open.spotify.com/track/second">Second Song</a></td></tr></table>'''
ALBUMS = '''<p>Last updated: 2026/10/05</p><table><tr><td><a href="https://open.spotify.com/album/compilation">Compilation</a></td><td>99,000</td><td>50</td></tr></table>'''


def service():
    calls=[]
    def fetch(url):
        calls.append(url)
        if url.endswith('listeners.html'):return LISTENERS
        if url.endswith('/spotify/'):return INDEX
        if url.endswith('_albums.html'):return ALBUMS
        return CHART
    return KworbCapabilityService(fetch=fetch),calls


def chart_agent(planner=None):
    agent,registry,calls=fixture_agent(planner=planner)
    original=registry.get('spotify_playback')
    def playback(args):
        if args['action']=='get_state':
            played=next((a for n,a in reversed(calls) if n=='spotify_playback' and a['action']=='play'),{})
            return {'ok':True,'data':{'is_playing':True,'track':{'uri':(played.get('uris') or [''])[0]}}}
        return original.adapter(args)
    registry._records['spotify_playback']=replace(original,adapter=playback)
    return agent,registry,calls


def test_listener_table_is_numeric_identity_bound_and_cached_without_search():
    reader,calls=service()
    response=reader.invoke({'action':'artist','artist':'davide guttea'})
    assert response['data']['name']=='David Guetta'
    assert response['data']['listeners']==83220280 and response['data']['artist_id']=='guetta'
    assert reader.invoke({'action':'artist','artist':'David Guetta'})==response
    assert calls==['https://kworb.net/spotify/listeners.html']


@pytest.mark.parametrize('period',['daily','weekly'])
def test_country_chart_uses_discovered_country_and_actual_track_links_and_date(period):
    reader,calls=service()
    response=reader.invoke({'action':'chart','country':'India','period':period})
    assert response['ok']
    assert response['data']['data_date']=='2026-10-04'
    assert [row['uri'] for row in response['data']['items']]==['spotify:track:first','spotify:track:second']
    assert calls[-1]==f'https://kworb.net/spotify/country/in_{period}.html'


def test_unlisted_country_and_unknown_artist_do_not_guess_or_fetch_arbitrary_urls():
    reader,calls=service()
    assert not reader.invoke({'action':'chart','country':'http://127.0.0.1'})['ok']
    assert not reader.invoke({'action':'artist','artist':'Unlisted artist'})['ok']
    assert all(url.startswith('https://kworb.net/spotify/') for url in calls)
    with pytest.raises(ValidationError):reader.invoke({'action':'chart','url':'http://127.0.0.1'})


def test_artist_albums_explicitly_are_stream_ranked_not_latest_release_catalog():
    reader,_=service()
    data=reader.invoke({'action':'albums','artist':'David Guetta'})['data']
    assert data['ordering']=='streams' and data['complete_catalog'] is False
    assert data['items'][0]['uri']=='spotify:album:compilation'


def test_cache_expiry_refetches_and_failed_fetch_cannot_return_stale_numbers():
    now=[0];calls=[]
    def fetch(url):
        calls.append(url)
        if len(calls)>1:raise ValueError('source unavailable')
        return LISTENERS
    reader=KworbCapabilityService(fetch=fetch,clock=lambda:now[0],ttl=10)
    assert reader.invoke({'action':'artist','artist':'Drake'})['ok']
    now[0]=11
    assert not reader.invoke({'action':'artist','artist':'Drake'})['ok']


def test_permission_boundary_read_only_and_public_lookup_needs_no_spotify_connection():
    reader,_=service(); registry=reader.build_registry()
    with pytest.raises(ToolPermissionError):registry.invoke('music_kworb',{'action':'artists'},agent_name='BrowserAgent')
    agent=MusicAgent(tool_registry=registry,integrations={},planner=lambda *_:pytest.fail('No model or Spotify needed'))
    assert agent.can_handle('how many monthly listeners does David Guetta have?')
    response=agent.answer('how many monthly listeners does David Guetta have?')
    assert response.status=='answered' and '83,220,280' in response.summary
    assert response.sources[0].path_or_url.endswith('listeners.html')
    assert not response.action_request


def test_chart_show_does_not_play_and_explicit_play_queues_exact_distinct_chart_tracks():
    agent,registry,calls=chart_agent(planner=lambda *_:pytest.fail('No chart name guessing'))
    reader,_=service()
    registry.register(reader.build_registry().get('music_kworb'))
    assert agent.can_handle('show top 2 songs in India this week')
    result=agent.answer('show top 2 songs in India this week')
    assert result.status=='answered' and '2026-10-04' in result.summary and not calls
    played=agent.answer('play top 2 songs in India this week')
    assert played.status=='answered'
    assert calls==[('spotify_playback',{'action':'play','uris':['spotify:track:first','spotify:track:second']})]


def test_schema_validated_public_plan_uses_same_reader_and_cannot_turn_listing_into_playback():
    agent,registry,calls=fixture_agent(planner=lambda *_:{'operation':'find_artists','limit':2})
    reader,_=service(); registry.register(reader.build_registry().get('music_kworb'))
    result=agent.answer('who leads listener rankings?')
    assert result.status=='answered' and 'David Guetta' in result.summary
    agent.planner=lambda *_:{'operation':'play_chart','country':'India','limit':2}
    result=agent.answer('which songs lead the India rankings?')
    assert result.status=='needs_fetch' and not calls


def test_latest_album_discovery_verifies_release_dates_not_kworb_stream_ranking():
    agent,registry,calls=fixture_agent(planner=lambda *_:pytest.fail('No model album title'))
    reader,_=service(); registry.register(reader.build_registry().get('music_kworb'))
    original=registry.get('spotify_albums')
    albums=[{'name':'Old Album','uri':'spotify:album:old','album_type':'album','artists':[{'id':'drake'}],'release_date':'2010-01-01'},
        {'name':'New Album','uri':'spotify:album:new','album_type':'album','artists':[{'id':'drake'}],'release_date':'2026-01-01'},
        {'name':'Future Album','uri':'spotify:album:future','album_type':'album','artists':[{'id':'drake'}],'release_date':'2099-01-01'},
        {'name':'Someone Else','uri':'spotify:album:other','album_type':'album','artists':[{'id':'other'}],'release_date':'2026-02-01'}]
    registry._records['spotify_albums']=replace(original,adapter=lambda args:{'ok':True,'data':{'items':albums,'next':None}})
    result=agent.answer('what is the latest album by Drake?')
    assert result.status=='answered' and 'New Album' in result.summary
    assert all(name not in result.summary for name in ['Old Album','Future Album','Compilation','Someone Else'])
    assert not calls


def test_shared_dispatcher_delegates_artist_statistics_and_charts_without_model(tmp_path):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog
    reader,_=service()
    agent=MusicAgent(tool_registry=reader.build_registry(),integrations={},planner=lambda *_:pytest.fail('No model lookup'))
    dispatcher=LiveAgentDispatcher(vault_root=tmp_path,agent_catalog=AgentCatalog(profile_dir=tmp_path/'profiles',executors={'MusicAgent':agent}),
        state_store=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db'))
    result=dispatcher.maybe_handle('how many monthly listeners does David Guetta have?','music-statistics')
    assert result.agent_name=='MusicAgent' and '83,220,280' in result.answer
    assert result.sources[0]['url']=='https://kworb.net/spotify/listeners.html'
    assert result.tools==['music_agent','music_kworb']
    chart=dispatcher.maybe_handle('show top 2 songs in India this week','music-statistics')
    assert chart.agent_name=='MusicAgent' and '2026-10-04' in chart.answer
    assert 'First Song' in chart.answer and 'Second Song' in chart.answer
    assert chart.tools==['music_agent','music_kworb']


def test_unavailable_monthly_listener_source_keeps_main_public_web_fallback(tmp_path):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog
    reader,_=service()
    agent=MusicAgent(tool_registry=reader.build_registry(),integrations={})
    dispatcher=LiveAgentDispatcher(vault_root=tmp_path,agent_catalog=AgentCatalog(profile_dir=tmp_path/'profiles',executors={'MusicAgent':agent}),
        state_store=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db'))
    assert dispatcher.maybe_handle('how many monthly listeners does Unlisted Artist have?','music-statistics') is None


@pytest.mark.parametrize('query,country,period,plays',[
    ('Show Japan’s weekly charts.','Japan','weekly',False),
    ('play from the global charts','global','daily',True),
    ('play songs from japan','japan','daily',True),
    ('play a song from france','france','daily',True),
    ('play France top 10 songs','France','daily',True),
])
def test_country_wording_from_saved_chat_preserves_country_and_chart_intent(query,country,period,plays):
    agent,registry,calls=chart_agent(planner=lambda *_:pytest.fail('Country request is not a song title'))
    reader,_=service();registry.register(reader.build_registry().get('music_kworb'))
    result=agent.answer(query)
    assert result.status=='answered',result.summary
    plan=result.structured_payload['music_plan']
    assert plan['country'].casefold()==country.casefold() and plan['chart_period']==period
    assert bool(calls)==plays


def test_list_chart_then_play_it_uses_the_displayed_tracks_without_refetch(tmp_path):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog
    agent,registry,calls=chart_agent(planner=lambda *_:pytest.fail('Retain the displayed chart'))
    reader,fetches=service();registry.register(reader.build_registry().get('music_kworb'))
    state=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db')
    state.set_active_agent('chart-followup','YoutubeAgent',selected=True)
    dispatcher=LiveAgentDispatcher(vault_root=tmp_path,agent_catalog=AgentCatalog(profile_dir=tmp_path/'profiles',executors={'MusicAgent':agent}),state_store=state)
    listed=dispatcher.maybe_handle('top 10 songs from france','chart-followup')
    before=len(fetches)
    played=dispatcher.maybe_handle('play it','chart-followup')
    assert played.agent_name=='MusicAgent' and played.status=='answered',played.answer
    assert len(fetches)==before
    assert calls==[('spotify_playback',{'action':'play','uris':['spotify:track:first','spotify:track:second']})]
    assert state.get('chart-followup').active_agent=='YoutubeAgent'


def test_discovered_album_name_followup_uses_verified_album_not_another_agent():
    from agent.agents.base import SpecialistResponse
    from agent.contracts.music import MusicPlan
    agent,_,calls=fixture_agent(planner=lambda *_:pytest.fail('Keep verified album identity'))
    discovered=SpecialistResponse(agent='MusicAgent',status='answered',summary='August 26',structured_payload={
        'music_plan':MusicPlan(operation='list_albums',artist='Post Malone',latest=True).model_dump(),
        'kworb':{'name':'Post Malone','released_albums':[{'name':'August 26','uri':'spotify:album:august','release_date':'2026-08-26'}]}})
    context=agent.thread_context(discovered,{})
    assert agent.can_handle_with_context('whta is the name of the album?',context)
    result=agent.answer_with_context('whta is the name of the album?',context)
    assert result.status=='answered' and 'August 26' in result.summary and not calls


@pytest.mark.parametrize('query',[
    'who is the artist of this song','what is the artist name?',
    'what is the artist name of the current song','who is the artist?',
    'what is the name of the album?','what album is this from?',
])
def test_current_artist_and_album_wording_reads_live_player(query):
    agent,registry,calls=fixture_agent(planner=lambda *_:pytest.fail('Never generate artist or album names'))
    observed=[]
    def live(name,args,**kwargs):
        observed.append((name,args))
        return {'ok':True,'data':{'track':{'name':'Live song','uri':'spotify:track:live'},'artists':['David Guetta'],'album':'Live album','is_playing':True}}
    registry.invoke=live
    assert agent.can_handle(query)
    result=agent.answer(query)
    assert result.status=='answered'
    assert ('Live album' if 'album' in query else 'David Guetta') in result.summary
    assert observed==[('spotify_playback',{'action':'get_state'})]


def test_latest_album_playback_resolves_duplicate_artist_names_by_verified_kworb_id():
    from agent.contracts.music import MusicPlan
    from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
    calls=[]
    def invoke(name,args):
        calls.append((name,args))
        if name=='spotify_search':return {'artists':{'items':[{'id':'post','name':'Post Malone'},{'id':'other','name':'Post Malone'}]}}
        if name=='music_kworb':return {'name':'Post Malone','artist_id':'post'}
        if name=='spotify_albums':
            assert args['artist_id']=='post'
            return {'items':[{'name':'August 26','uri':'spotify:album:august','album_type':'album','release_date':'2026-08-26','artists':[{'id':'post','name':'Post Malone'}]}],'next':None}
        if args['action']=='get_currently_playing':return {'is_playing':True,'context':{'uri':'spotify:album:august'}}
        return {}
    result=SpotifyCapabilityService().execute(MusicPlan(operation='play_album',artist='post malone',latest=True),invoke)
    assert 'August 26' in result
    assert [a for n,a in calls if n=='spotify_playback' and a['action']=='play']==[{'action':'play','context_uri':'spotify:album:august'}]


def test_chart_cannot_claim_playback_when_live_state_is_still_an_unrelated_song(monkeypatch):
    agent,registry,calls=fixture_agent()
    reader,_=service();registry.register(reader.build_registry().get('music_kworb'))
    original=registry.get('spotify_playback')
    registry._records['spotify_playback']=replace(original,adapter=lambda args:
        {'ok':True,'data':{'is_playing':True,'track':{'uri':'spotify:track:unrelated'}}} if args['action']=='get_state' else original.adapter(args))
    monkeypatch.setattr('agent.tools.capabilities.spotify_service.time.sleep',lambda _:None)
    result=agent.answer('play top 2 songs in France')
    assert result.status=='error' and 'did not confirm' in result.summary
    assert len([a for n,a in calls if a.get('action')=='play'])==1


def test_failed_chart_keeps_displayed_target_for_an_explicit_play_retry():
    agent,registry,calls=chart_agent()
    reader,fetches=service();registry.register(reader.build_registry().get('music_kworb'))
    original=registry.get('spotify_playback');attempts=[]
    def playback(args):
        if args['action']=='play':
            attempts.append(args)
            if len(attempts)==1:return {'ok':False,'error':{'message':'No active device'}}
        return original.adapter(args)
    registry._records['spotify_playback']=replace(original,adapter=playback)
    failed=agent.answer('play songs from Japan')
    assert failed.status=='error' and len(attempts)==1
    before=len(fetches)
    context=agent.thread_context(failed,{})
    retried=agent.answer_with_context('play it',context)
    assert retried.status=='answered',retried.summary
    assert len(attempts)==2 and len(fetches)==before and attempts[0]==attempts[1]
