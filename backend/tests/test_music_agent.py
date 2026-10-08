import json
from datetime import datetime, timedelta, timezone

import pytest

from dataclasses import replace
from agent.agents.music import LocalMusicPlanner, MusicAgent
from agent.contracts.music import MusicPlan
from agent.master.runtime import DelegationRequest, DelegationRuntime
from agent.profiles import AgentCatalog
from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
from agent.tools.registry import ToolPermissionError


@pytest.mark.parametrize('query', ['what drake songs did I play yesterday', 'what song did u play from drake yesterday?'])
def test_yesterday_artist_recall_uses_history_credits_not_model_guesses(query):
    zone = timezone(timedelta(hours=5, minutes=30))
    clock = datetime(2026, 10, 5, 10, tzinfo=zone)
    yesterday = clock.date() - timedelta(days=1)
    stamp = datetime.combine(yesterday, datetime.min.time(), zone).replace(hour=12).isoformat()
    history = {"items":[
        {"played_at":stamp, "track":{"uri":"spotify:track:gucci", "name":"Step Out (feat. Future and Foogiano)", "artists":[{"id":"gucci", "name":"Gucci Mane"}]}},
        {"played_at":stamp, "track":{"uri":"spotify:track:drake", "name":"The Ride", "artists":[{"id":"drake", "name":"Drake"}]}}
    ], "next":None}
    agent, _, calls = fixture_agent(history=history, planner=lambda *_:pytest.fail("Recall must never ask the model to invent history"))
    agent.now = lambda: clock
    assert agent.can_handle(query)
    response = agent.answer(query)
    assert response.status == "answered"
    assert "The Ride" in response.summary
    assert "Step Out" not in response.summary
    assert calls and all(name == "spotify_playback" and args["action"] == "recently_played" for name,args in calls)
    assert response.structured_payload["history"][0]["artists"] == ["Drake"]


def test_mood_suggestion_reads_catalog_but_waits_for_acceptance():
    agent, _, calls = fixture_agent(planner=lambda *_:{"operation":"suggest_music", "query":"mellow music"})
    assert agent.can_handle("suggest music for a stressful evening")
    response = agent.answer("suggest music for a stressful evening")
    assert response.status == "needs_fetch"
    assert response.action_request["action"] == "music.play_suggestion"
    assert not any(name == "spotify_playback" for name,_ in calls)
    accepted = agent.execute_action_request(response.action_request)
    assert accepted.status == "answered"
    assert calls[-1] == ("spotify_playback", {"action":"play", "uris":["spotify:track:original"]})


def test_history_paginates_and_filters_local_day_and_exact_artist():
    zone = timezone(timedelta(hours=5, minutes=30))
    def row(stamp, artist, uri):
        return {'played_at':stamp, 'track':{'uri':uri, 'name':'Verified song', 'artists':[{'name':artist}]}}
    pages = [
        {'items':[row('2026-10-04T18:30:00Z','Drake','spotify:track:today'), row('2026-10-04T12:00:00Z','Gucci Mane','spotify:track:gucci')], 'next':'provider-page', 'cursors':{'before':'1791115200000'}},
        {'items':[row('2026-10-03T18:30:00Z','Drake','spotify:track:start'), row('2026-10-03T18:29:59Z','Drake','spotify:track:old')], 'next':None},
    ]
    agent, _, calls = fixture_agent(history=pages)
    agent.now = lambda: datetime(2026, 10, 5, 10, tzinfo=zone)
    result = agent.answer('what songs by drake did I play yesterday')
    assert result.status == 'answered'
    assert [r['uri'] for r in result.structured_payload['history']] == ['spotify:track:start']
    assert len(calls) == 2
    assert all(args['action'] == 'recently_played' for _,args in calls)


def test_empty_history_is_not_a_claim_that_user_never_listened():
    agent, _, calls = fixture_agent(planner=lambda *_:pytest.fail('No model history fallback'))
    result = agent.answer('what drake songs I played yesterday')
    assert result.status == 'answered'
    assert 'available history' in result.summary
    assert result.structured_payload['history'] == []
    assert len(calls) == 1


def test_suggestion_planner_cannot_turn_a_recommendation_into_playback():
    agent, _, calls = fixture_agent(planner=lambda *_:{'operation':'play_song', 'query':'Blinding Lights'})
    result = agent.answer('recommend music for my mood')
    assert result.status == 'needs_fetch' and not result.action_request
    assert not calls


@pytest.mark.parametrize('confirmation', ['confirm', 'cancel'])
def test_suggestion_acceptance_is_bound_to_one_pending_action(tmp_path, confirmation):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    agent, _, calls = fixture_agent(planner=lambda *_:{'operation':'suggest_music', 'query':'mellow'})
    state = MasterThreadStateStore(sessions_db=tmp_path / 'sessions.db')
    catalog = AgentCatalog(profile_dir=tmp_path / 'profiles', executors={'MusicAgent':agent})
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state)
    assert dispatcher.maybe_handle('suggest music for my mood', 'music').status == 'needs_fetch'
    assert not any(name == 'spotify_playback' for name,_ in calls)
    result = dispatcher.maybe_handle(confirmation, 'music')
    assert result.status == ('answered' if confirmation == 'confirm' else 'blocked')
    assert len([args for name,args in calls if name == 'spotify_playback']) == (1 if confirmation == 'confirm' else 0)
    repeated = dispatcher.delegation_runtime.delegate(DelegationRequest(agent_id='MusicAgent', task='confirm', parent_thread_id='music', confirm_pending_action=True))
    assert repeated.response.status == 'blocked'


def test_music_preference_survives_reload_and_remains_scoped(tmp_path):
    from test_delegation_runtime import build_runtime
    from agent.memory.orchestrator import SQLiteMemoryStore
    planner_queries = []
    def planner(query, _):
        planner_queries.append(query)
        return {'operation':'suggest_music', 'query':'instrumental music'}
    agent, _, calls = fixture_agent(planner=planner)
    runtime, _ = build_runtime(tmp_path)
    runtime.agent_catalog = AgentCatalog(profile_dir=tmp_path / 'profiles', executors={'MusicAgent':agent})
    saved = runtime.delegate(DelegationRequest(agent_id='MusicAgent', task='remember I prefer instrumental music when working', parent_thread_id='music'))
    assert saved.response.status == 'answered'
    assert saved.response.structured_payload['scope'] == 'agent:MusicAgent'
    store = SQLiteMemoryStore(tmp_path / 'memory.db')
    assert len(store.list_saved(scopes=['agent:MusicAgent'])) == 1
    runtime.memory_orchestrator.store = store
    store.save_memory(kind='preference', text='I like keeping my medical records private', source_thread_id='other', confidence=1, scope='global')
    response = runtime.delegate(DelegationRequest(agent_id='MusicAgent', task='recommend a song', parent_thread_id='new-thread', context='I am working on a report and want to concentrate'))
    assert response.response.status == 'needs_fetch'
    assert 'instrumental music' in planner_queries[-1]
    assert 'want to concentrate' in planner_queries[-1]
    assert 'medical' not in planner_queries[-1]
    assert not any(name == 'spotify_playback' for name,_ in calls)
    assert 'global' not in runtime.agent_catalog.get('MusicAgent').memory.read_scopes


def test_artist_constrained_suggestion_never_substitutes_another_artist():
    agent, _, calls = fixture_agent(tracks=[{'name':'Step Out', 'uri':'spotify:track:gucci', 'artists':[{'name':'Gucci Mane'}]}],
        planner=lambda *_:{'operation':'suggest_music', 'query':'Drake songs', 'artist':'Drake'})
    result = agent.answer('recommend songs by Drake')
    assert result.status == 'error' and not result.action_request
    assert not any(name == 'spotify_playback' for name,_ in calls)


def test_disabled_profile_memory_scope_cannot_fall_back_to_global(tmp_path):
    from test_delegation_runtime import build_runtime
    from agent.profiles import builtin_profiles
    agent, _, _ = fixture_agent()
    runtime, _ = build_runtime(tmp_path)
    profile = builtin_profiles()['MusicAgent']
    profile = profile.model_copy(update={'memory':profile.memory.model_copy(update={'write_scope':''})})
    runtime.agent_catalog = AgentCatalog(profile_dir=tmp_path / 'profiles', builtins={'MusicAgent':profile}, executors={'MusicAgent':agent})
    result = runtime.delegate(DelegationRequest(agent_id='MusicAgent', task='remember I prefer quiet music', parent_thread_id='music'))
    assert result.response.status == 'blocked'
    assert not runtime.memory_orchestrator.store.list_saved(scopes=['global', 'agent:MusicAgent'])


def test_exact_dated_recall_delegates_even_with_memory_agent_selected(tmp_path):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    agent, _, calls = fixture_agent(planner=lambda *_:pytest.fail('No model recall'))
    state = MasterThreadStateStore(sessions_db=tmp_path / 'sessions.db')
    state.set_active_agent('music', 'MemoryAgent', selected=True)
    catalog = AgentCatalog(profile_dir=tmp_path / 'profiles', executors={'MusicAgent':agent})
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state)
    result = dispatcher.maybe_handle('what song did u play from drake yesterday?', 'music')
    assert result.agent_name == 'MusicAgent' and result.status == 'answered'
    assert calls[0][1]['action'] == 'recently_played'
    assert state.get('music').active_agent == 'MemoryAgent'


def test_disabled_memory_blocks_preference_retention(tmp_path):
    from test_delegation_runtime import build_runtime
    agent, _, _ = fixture_agent()
    runtime, _ = build_runtime(tmp_path)
    runtime.agent_catalog = AgentCatalog(profile_dir=tmp_path / 'profiles', executors={'MusicAgent':agent})
    runtime.memory_orchestrator.store.update_settings({'memory_enabled':False})
    result = runtime.delegate(DelegationRequest(agent_id='MusicAgent', task='remember I prefer quiet music', parent_thread_id='music'))
    assert result.response.status == 'blocked'
    assert not runtime.memory_orchestrator.store.list_saved(scopes=['agent:MusicAgent'])


def fixture_agent(planner=None, tracks=None, playlists=None, library=None, shows=None, episodes=None, public_playlists=None, history=None):
    calls = []
    created_playlist = {}
    saved_uris = []
    def handler(name):
        def run(args, **kwargs):
            calls.append((name, args))
            if name == "spotify_search":
                kind = (args.get("types") or ["track"])[0]
                data = {kind+"s":{"items":({"track":tracks if tracks is not None else [{"name":"Blinding Lights", "uri":"spotify:track:original", "artists":[{"name":"The Weeknd"}]}], "show":shows or [], "episode":episodes or [], "playlist":public_playlists or []})[kind]}}
            elif name == "spotify_podcasts":
                data = {"items":episodes or []} if args.get("action") == "episodes" else next((s for s in shows or [] if s["id"] == args.get("show_id")), {})
            elif name == "spotify_playlists":
                if args.get("action") == "create":
                    created_playlist.update(id="created", name=args["name"])
                    data = dict(created_playlist)
                elif args.get("action") == "add_items":
                    saved_uris[:] = args["uris"]
                    data = {"snapshot_id":"added"}
                elif args.get("action") == "get" and args.get("playlist_id") == "created":
                    data = dict(created_playlist)
                elif args.get("action") == "tracks":
                    data = {"items":[{"track":{"uri":uri}} for uri in saved_uris]}
                else:
                    choices = (playlists if playlists is not None else [{"id":"hindi", "name":"Hindi", "uri":"spotify:playlist:hindi"}]) + (public_playlists or [])
                    data = (next(({**p,"items":{"total":4}} for p in choices if p["id"] == args.get("playlist_id")), {"items":{"total":4}}) if args.get("action") == "get" else
                            {"items":playlists if playlists is not None else [{"id":"hindi", "name":"Hindi", "uri":"spotify:playlist:hindi"}], "next":None})
            elif name == "spotify_playback" and args.get("action") == "recently_played":
                data = history.pop(0) if isinstance(history, list) and history else history or {"items":[], "next":None}
            elif name == "spotify_library":
                data = library or {"items":[], "total":0}
            else:
                data = {}
            return json.dumps({"ok":True,"data":data})
        return run
    from agent.plugins.spotify_runtime import registered_spotify_context
    context = registered_spotify_context()
    for name, record in context.tools.items():
        context.tools[name] = replace(record, handler=handler(name))
    registry = SpotifyCapabilityService(context=context).build_registry()
    integration = SpotifyCapabilityService(context=context)
    return MusicAgent(tool_registry=registry, integrations={"spotify":integration}, planner=planner or (lambda *_:{"operation":"clarify"}), skill_loader=lambda _:"Search once and play one URI."), registry, calls


@pytest.mark.parametrize("query,shuffle", [
    ("play the 1st song from the liked song playlist", False),
    ("play something from my liked playlist", True),
    ("play a random song from my liked songs playlist", True),
])
def test_screenshot_liked_collection_is_not_a_named_playlist(query, shuffle):
    agent, _, calls = fixture_agent(library={"items":[{"track":{"uri":"spotify:track:liked"}}], "total":1})
    response = agent.answer(query)
    assert response.status == "answered"
    assert calls[0][0] == "spotify_library"
    assert not any(name == "spotify_playlists" for name, _ in calls)
    assert ("spotify_playback", {"action":"set_shuffle", "shuffle":shuffle}) in calls


@pytest.mark.parametrize("query", ["play a podcasts from wtf", "play a podacts from nikil kmath"])
def test_podcast_request_never_searches_or_plays_music_tracks(query):
    agent, _, calls = fixture_agent()
    response = agent.answer(query)
    assert not any(name == "spotify_search" and args.get("types") == ["track"] for name, args in calls)
    assert not any(name == "spotify_playback" for name, _ in calls)
    assert response.status == "needs_fetch"


@pytest.mark.parametrize("query", ["skip the current song", "skip to the next song", "skip this", "go to the next track"])
def test_skip_variants_are_controls_and_never_song_searches(query):
    agent, _, calls = fixture_agent()
    assert agent.can_handle(query)
    response = agent.answer(query)
    assert response.summary == "Skipped to the next track."
    assert calls == [("spotify_playback", {"action":"next"})]


def test_podcast_show_is_selected_then_only_an_episode_uri_plays():
    shows = [{"id":"show1", "name":"WTF is with Nikhil Kamath", "uri":"spotify:show:show1"},
             {"id":"show2", "name":"WTF with Marc Maron Podcast", "uri":"spotify:show:show2"}]
    episodes = [{"name":"An unavailable episode", "uri":"spotify:episode:blocked", "is_playable":False},
                {"name":"Travel conversation", "uri":"spotify:episode:episode1", "is_playable":True}]
    agent, _, calls = fixture_agent(shows=shows, episodes=episodes)
    response = agent.answer("play a podcasts from wtf")
    assert response.status == "needs_fetch"
    assert not any(name == "spotify_playback" for name, _ in calls)
    context = agent.thread_context(response, {})
    assert agent.can_handle_with_context("Nikhil Kamath", context)
    selected = agent.answer_with_context("Nikhil Kamath", context)
    assert selected.status == "answered"
    assert "Travel conversation from WTF is with Nikhil Kamath" in selected.summary
    assert calls[-1] == ("spotify_playback", {"action":"play", "uris":["spotify:episode:episode1"]})
    assert not any(name == "spotify_search" and args["types"] == ["track"] for name,args in calls)


def test_misspelled_podcast_host_matches_actual_show_metadata():
    agent, _, calls = fixture_agent(shows=[{"id":"one", "name":"WTF is with Nikhil Kamath", "uri":"spotify:show:one"}],
                                    episodes=[{"name":"Episode", "uri":"spotify:episode:one"}])
    assert agent.answer("play a podacts from nikil kmath").status == "answered"
    assert calls[-1][1]["uris"] == ["spotify:episode:one"]


def test_podcast_planner_cannot_fall_back_to_song_operation():
    agent, _, calls = fixture_agent(planner=lambda *_:{"operation":"play_song", "query":"WTF"})
    assert agent.answer("put the WTF podcast on for me").status == "needs_fetch"
    assert calls == []


@pytest.mark.parametrize("query", ["play 🔥 playlist", "play ♨️ playlist", "play my 🔥"])
def test_emoji_playlist_names_keep_distinct_identity(query):
    playlists = [{"id":"fire", "name":"🔥", "uri":"spotify:playlist:fire"},
                 {"id":"heat", "name":"♨︎", "uri":"spotify:playlist:heat"}]
    agent, _, calls = fixture_agent(playlists=playlists)
    assert agent.answer(query).status == "answered"
    assert calls[-1][1]["context_uri"] == ("spotify:playlist:fire" if "🔥" in query else "spotify:playlist:heat")


def test_missing_personal_playlist_requires_link_instead_of_public_substitution():
    agent, _, calls = fixture_agent(playlists=[], public_playlists=[{"id":"rizz", "name":"Rizz mix 👅", "uri":"spotify:playlist:rizz"}])
    response = agent.answer("play the rizz mix playlist")
    assert response.status == "needs_fetch"
    assert "No saved playlist matched" in response.summary
    assert not any(name == "spotify_playback" for name, _ in calls)
    context = agent.thread_context(response, {})
    assert not response.structured_payload['choices']
    assert not any(name == 'spotify_search' for name,_ in calls)
    assert agent.can_handle_with_context("https://open.spotify.com/playlist/personal", context)
    selected = agent.answer_with_context("https://open.spotify.com/playlist/personal", context)
    assert selected.status == "answered"
    assert calls[-1] == ("spotify_playback", {"action":"play", "context_uri":"spotify:playlist:personal"})


def test_daily_mix_does_not_substitute_someone_elses_public_playlist():
    agent, _, calls = fixture_agent(playlists=[], public_playlists=[{"name":"Daily Mix 1", "uri":"spotify:playlist:other"}])
    response = agent.answer("play my daily mix playlist")
    assert response.status == "needs_fetch"
    assert "Spotify link" in response.summary
    assert calls == [("spotify_playlists", {"action":"list", "limit":50, "offset":0})]
    context = agent.thread_context(response, {})
    assert agent.can_handle_with_context("https://open.spotify.com/playlist/mine?si=123", context)


def test_playlist_link_resolves_id_and_preserves_first_track_offset():
    calls = []
    def invoke(name, payload):
        calls.append((name,payload))
        return {"id":"mine", "name":"Daily Mix 1", "uri":"spotify:playlist:mine"}
    result = SpotifyCapabilityService().execute(MusicPlan(operation="play_playlist", query="https://open.spotify.com/playlist/mine?si=123", position=1, shuffle=False), invoke)
    assert result == "Playing your linked Spotify playlist."
    assert not any(name == "spotify_playlists" for name,_ in calls)
    assert ("spotify_playback", {"action":"play", "context_uri":"spotify:playlist:mine", "offset":{"position":0}}) in calls


def test_personalized_playlist_link_plays_even_when_metadata_is_inaccessible():
    calls = []
    def invoke(name, payload):
        calls.append((name,payload))
        if name == "spotify_playlists":
            raise ValueError("Spotify request failed with status 404")
        return {}
    result = SpotifyCapabilityService().execute(MusicPlan(operation="play_playlist", query="https://open.spotify.com/playlist/personal"), invoke)
    assert "linked Spotify playlist" in result
    assert calls == [("spotify_playback", {"action":"play", "context_uri":"spotify:playlist:personal"})]


def test_supplied_playlist_link_is_bound_to_name_in_existing_thread_context():
    agent, _, calls = fixture_agent(playlists=[])
    missing = agent.answer("play my daily mix playlist")
    context = agent.thread_context(missing, {})
    response = agent.answer_with_context("https://open.spotify.com/playlist/personal", context)
    assert response.status == "answered"
    assert calls[-1] == ("spotify_playback", {"action":"play", "context_uri":"spotify:playlist:personal"})
    context = agent.thread_context(response, context)
    paused = agent.answer_with_context("pause", context)
    context = agent.thread_context(paused, context)
    calls.clear()
    replay = agent.answer_with_context("play my daily mix playlist", context)
    assert replay.status == "answered"
    assert calls == [("spotify_playback", {"action":"play", "context_uri":"spotify:playlist:personal"})]


def test_saved_playlist_lookup_paginates_past_old_500_limit():
    offsets = []
    def invoke(name, payload):
        if name != "spotify_playlists":
            return {}
        offset = payload["offset"]
        offsets.append(offset)
        return {"items":[{"id":str(offset), "name":"Target" if offset==550 else "Other", "uri":"spotify:playlist:"+str(offset)}], "next":"more" if offset<550 else None}
    SpotifyCapabilityService().execute(MusicPlan(operation="play_playlist", query="Target"), invoke)
    assert offsets[-1] == 550


def test_music_ui_context_prefix_keeps_actual_command():
    agent, _, calls = fixture_agent()
    message = "[Vellum UI context: the user is currently chatting in the Spotify view.]\n\nplay blinding lights"
    assert agent.can_handle(message)
    assert agent.answer(message).status == "answered"
    assert calls[-1][1]["uris"] == ["spotify:track:original"]


@pytest.mark.parametrize("query", ["play blinding lights", "blinding lights by the weekend on spotify", "play blinding lights on spotify"])
def test_screenshot_commands_play_one_resolved_track(query):
    agent, _, calls = fixture_agent()
    assert agent.can_handle(query)
    response = agent.answer(query)
    assert response.status == "answered"
    assert "Playing Blinding Lights" in response.summary
    assert [name for name, _ in calls] == ["spotify_search", "spotify_playback"]
    assert calls[-1][1] == {"action":"play", "uris":["spotify:track:original"]}


@pytest.mark.parametrize('message,expected', [
    ('play Blinding Lights', 'original'),
    ('play Blinding Light', 'original'),
    ('play Blinding Lights by Loi', 'cover'),
    ('play Blinding Lights - Major Lazer Remix', 'remix'),
])
def test_default_original_and_explicit_artist_or_remix_use_catalog_identity(message, expected):
    tracks = [
        {'name':'Blinding Lights', 'uri':'spotify:track:cover', 'artists':[{'name':'Loi'}],
         'album':{'name':'Blinding Lights', 'release_date':'2021-09-17'}},
        {'name':'Blinding Lights - Major Lazer Remix', 'uri':'spotify:track:remix', 'artists':[{'name':'The Weeknd'},{'name':'Major Lazer'}],
         'album':{'name':'Blinding Lights (Remix)', 'release_date':'2020-09-11'}},
        {'name':'Blinding Lights', 'uri':'spotify:track:original', 'artists':[{'name':'The Weeknd'}],
         'album':{'name':'After Hours', 'release_date':'2020-03-20'}},
    ]
    agent, _, calls = fixture_agent(tracks=tracks)
    result = agent.answer(message)
    assert result.status == 'answered', result.summary
    assert calls[-1][1]['uris'] == ['spotify:track:' + expected]


def test_unlabelled_cover_does_not_outrank_earlier_studio_release_and_remix_album_is_excluded():
    tracks = [
        {'name':'Example Song', 'uri':'spotify:track:alternate', 'artists':[{'name':'Remixer'}],
         'album':{'name':'Example Song Remixes', 'release_date':'1990-01-01'}},
        {'name':'Example Song', 'uri':'spotify:track:cover', 'artists':[{'name':'Cover Artist'}],
         'album':{'name':'Later Recording', 'release_date':'2024-01-01'}},
        {'name':'Example Song', 'uri':'spotify:track:original', 'artists':[{'name':'Original Artist'}],
         'album':{'name':'Studio Album', 'release_date':'2005-01-01'}},
    ]
    agent, _, calls = fixture_agent(tracks=tracks)
    result = agent.answer('play Example Song')
    assert result.status == 'answered' and 'Original Artist' in result.summary
    assert calls[-1][1]['uris'] == ['spotify:track:original']


def test_original_followup_uses_catalog_evidence_without_requiring_artist_again():
    tracks = [
        {'name':'Example Song', 'uri':'spotify:track:cover', 'artists':[{'name':'Cover Artist'}],
         'album':{'name':'Later Recording', 'release_date':'2024-01-01'}},
        {'name':'Example Song', 'uri':'spotify:track:original', 'artists':[{'name':'Original Artist'}],
         'album':{'name':'Studio Album', 'release_date':'2005-01-01'}},
    ]
    agent, _, calls = fixture_agent(tracks=tracks)
    context = agent.thread_context(agent.answer('play Example Song by Cover Artist'), {})
    result = agent.answer_with_context('play the original', context)
    assert result.status == 'answered', result.summary
    assert calls[-1][1]['uris'] == ['spotify:track:original']


def test_default_does_not_play_only_labelled_alternates_or_guess_tied_originals():
    for tracks in [
        [{'name':'Example Song', 'uri':'spotify:track:cover', 'artists':[{'name':'Other Artist'}],
          'album':{'name':'Cover Songs', 'release_date':'2020-01-01'}}],
        [{'name':'Example Song', 'uri':'spotify:track:'+key, 'artists':[{'name':key}],
          'album':{'name':'Studio Album', 'release_date':'2020'}} for key in ['first','second']],
    ]:
        agent, _, calls = fixture_agent(tracks=tracks)
        result = agent.answer('play Example Song')
        assert result.status == 'needs_fetch'
        assert not any(name == 'spotify_playback' for name, _ in calls)


@pytest.mark.parametrize('dates,expected', [
    (('2020-09-17', '2020-03-20'), 'answered'),
    (('2020', '2020-03-20'), 'needs_fetch'),
])
def test_original_release_comparison_respects_catalog_date_precision(dates, expected):
    tracks = [{'name':'Example Song','uri':'spotify:track:'+key,'artists':[{'name':key}],
               'album':{'name':'Studio Album','release_date':date}}
              for key,date in zip(['later','original'], dates)]
    agent, _, calls = fixture_agent(tracks=tracks)
    result = agent.answer('play Example Song')
    assert result.status == expected
    if expected == 'answered':
        assert calls[-1][1]['uris'] == ['spotify:track:original']
    else:
        assert not any(name == 'spotify_playback' for name, _ in calls)


@pytest.mark.parametrize('message', [
    'play a random song from any of my saved playlist',
    'play a random song from an of my saved playlist',
    'play a song from my saved playlist',
])
def test_latest_chat_random_saved_playlist_is_a_collection_not_a_playlist_name(message):
    agent, _, calls = fixture_agent(playlists=[{'id':'hindi','name':'Hindi','uri':'spotify:playlist:hindi'}])
    result = agent.answer(message)
    assert result.status == 'answered', result.summary
    assert any(name=='spotify_playlists' and args['action']=='list' for name,args in calls)
    assert any(name=='spotify_playback' and args.get('context_uri')=='spotify:playlist:hindi' for name,args in calls)


def test_latest_chat_playlist_typo_and_saved_playlist_count_are_music_intents():
    agent, _, calls = fixture_agent()
    assert agent.can_handle('how many playlist i have saved?')
    count = agent.answer('how many playlist i have saved?')
    assert count.status == 'answered' and '1 saved playlist' in count.summary
    played = agent.answer('play my hindi playlkist')
    assert played.status == 'answered', played.summary
    assert calls[-1][1]['context_uri'] == 'spotify:playlist:hindi'


def test_latest_chat_collaboration_credit_does_not_hide_original_song():
    tracks = [
        {'name':'One Right Now (with The Weeknd)','uri':'spotify:track:original',
         'artists':[{'name':'Post Malone'},{'name':'The Weeknd'}],
         'album':{'name':'One Right Now','release_date':'2021-11-05'}},
        {'name':'One Right Now','uri':'spotify:track:other',
         'artists':[{'name':'David Shannon'},{'name':'Frank Rivers'}],
         'album':{'name':'One Right Now','release_date':'2022-01-01'}},
    ]
    agent, _, calls = fixture_agent(tracks=tracks)
    result = agent.answer('play one right now')
    assert result.status == 'answered' and 'Post Malone' in result.summary
    assert calls[-1][1]['uris'] == ['spotify:track:original']


@pytest.mark.parametrize('artist',['Earth, Wind and Fire','Tyler, The Creator','The Weeknd'])
def test_with_credit_recognizes_punctuation_in_actual_artist_name(artist):
    tracks=[{'name':f'Example Song (with {artist})','uri':'spotify:track:original','artists':[{'name':'Lead Artist'},{'name':artist}]}]
    agent,_,calls=fixture_agent(tracks=tracks)
    result=agent.answer('play Example Song')
    assert result.status=='answered',result.summary
    assert calls[-1][1]['uris']==['spotify:track:original']


def test_with_suffix_is_not_removed_when_it_is_not_a_credited_artist():
    agent,_,calls=fixture_agent(tracks=[{'name':'Example Song (with feeling)','uri':'spotify:track:other','artists':[{'name':'Other Artist'}]}])
    result=agent.answer('play Example Song')
    assert result.status=='needs_fetch'
    assert not any(name=='spotify_playback' for name,_ in calls)


@pytest.mark.parametrize('message',['play the her loss album','play Her Loss album by Drake','play the album Her Loss'])
def test_album_title_before_album_word_never_becomes_track_search(message):
    agent, registry, calls = fixture_agent()
    original = registry.invoke
    observed = []
    def invoke(name,args,**kwargs):
        observed.append((name,dict(args)))
        if name=='spotify_search':
            assert args['types']==['album'], 'An album request must never search tracks'
            return {'ok':True,'data':{'albums':{'items':[{'name':'Her Loss','uri':'spotify:album:herloss','artists':[{'name':'Drake'},{'name':'21 Savage'}]}]}}}
        if name=='spotify_playback':
            return {'ok':True,'data':{'is_playing':True,'context':{'uri':'spotify:album:herloss'}}}
        return original(name,args,**kwargs)
    registry.invoke=invoke
    result=agent.answer(message)
    assert result.status=='answered' and 'Her Loss' in result.summary, result.summary
    assert any(name=='spotify_playback' and args.get('context_uri')=='spotify:album:herloss' for name,args in observed)


def test_ambiguous_album_and_wrong_collaborator_remain_album_choices_and_accept_artist_reply():
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('Album correction must not invoke the model'))
    calls=[]
    def invoke(name,args,**kwargs):
        calls.append((name,dict(args)))
        if name=='spotify_search':
            assert args['types']==['album']
            return {'ok':True,'data':{'albums':{'items':[
                {'name':'Her Loss','uri':'spotify:album:other','artists':[{'name':'Other Artist'}]},
                {'name':'Her Loss','uri':'spotify:album:drake','artists':[{'name':'Drake'},{'name':'21 Savage'}]},
            ]}}}
        return {'ok':True,'data':{'is_playing':True,'context':{'uri':'spotify:album:drake'}}}
    registry.invoke=invoke
    first=agent.answer('play the Her Loss album by Drake and Metro Boomin')
    assert first.status=='needs_fetch' and 'Drake, 21 Savage' in first.summary
    assert not any(name=='spotify_playback' for name,_ in calls)
    context=agent.thread_context(first,{})
    assert agent.can_handle_with_context('no from Drake',context)
    result=agent.answer_with_context('no from Drake',context)
    assert result.status=='answered' and 'Drake, 21 Savage' in result.summary
    assert [args['context_uri'] for _,args in calls if args.get('action')=='play']==['spotify:album:drake']


def test_latest_saved_album_correction_recovers_legacy_misclassified_song_context():
    import time
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('An album correction must not wait on a model'))
    calls=[]
    def invoke(name,args,**kwargs):
        calls.append((name,dict(args)))
        assert name=='spotify_search' and args['types']==['album']
        return {'ok':True,'data':{'albums':{'items':[{'name':'Her Loss','uri':'spotify:album:drake','artists':[{'name':'Drake'},{'name':'21 Savage'}]}]}}}
    registry.invoke=invoke
    old=MusicPlan(operation='play_song',query='her loss album').model_dump()
    context={'last_plan':old,'last_song_plan':old,'at':time.time()}
    assert agent.can_handle_with_context('no the album by drake and metro boomin',context)
    result=agent.answer_with_context('no the album by drake and metro boomin',context)
    assert result.status=='needs_fetch' and 'Drake, 21 Savage' in result.summary
    assert result.structured_payload['music_plan']['operation']=='play_album'
    assert len(calls)==1


def test_album_correction_recovers_when_artist_filtered_search_returns_nothing():
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('Album correction must not invoke the model'))
    calls=[]
    def invoke(name,args,**kwargs):
        calls.append((name,dict(args)))
        if name=='spotify_search':
            assert args['types']==['album']
            items=[] if 'metro boomin' in args['query'].casefold() else [
                {'name':'Her Loss','uri':'spotify:album:drake','artists':[{'name':'Drake'},{'name':'21 Savage'}]}]
            return {'ok':True,'data':{'albums':{'items':items}}}
        return {'ok':True,'data':{'is_playing':True,'context':{'uri':'spotify:album:drake'}}}
    registry.invoke=invoke
    first=agent.answer('play Her Loss album')
    context=agent.thread_context(first,{})
    calls.clear()
    result=agent.answer_with_context('no the album by drake and metro boomin',context)
    assert result.status=='needs_fetch' and 'Drake, 21 Savage' in result.summary,result.summary
    assert len(calls)==2
    assert all(name=='spotify_search' for name,_ in calls)
    assert calls[-1][1]['query']=='album:"Her Loss"'
    corrected=agent.answer_with_context('by Drake',agent.thread_context(result,context))
    assert corrected.status=='answered' and 'Drake, 21 Savage' in corrected.summary
    assert [args['context_uri'] for name,args in calls if name=='spotify_playback' and args.get('action')=='play']==['spotify:album:drake']


def test_saved_playlist_selection_never_uses_empty_library_or_public_search():
    agent,_,calls=fixture_agent(playlists=[])
    result=agent.answer('play a random song from my saved playlists')
    assert result.status=='needs_fetch'
    assert not any(name in {'spotify_search','spotify_playback'} for name,_ in calls)


def test_playlist_count_cannot_report_zero_when_api_failed():
    agent,registry,_=fixture_agent()
    registry.invoke=lambda *_args,**_kwargs:{'ok':False,'error':{'message':'Spotify temporarily unavailable'}}
    result=agent.answer('how many playlist i have saved?')
    assert result.status=='error' and 'unavailable' in result.summary
    assert '0 saved playlists' not in result.summary


def test_hindi_playlist_shuffle_uses_context_then_explicit_shuffle_setting():
    agent, _, calls = fixture_agent()
    response = agent.answer("from my Hindi playlist play a song in shuffle order")
    assert response.status == "answered"
    assert [name for name, _ in calls] == ["spotify_playlists", "spotify_playlists", "spotify_playback", "spotify_playback"]
    assert calls[-2][1]["context_uri"] == "spotify:playlist:hindi"
    assert 0 <= calls[-2][1]["offset"]["position"] < 4
    assert calls[-1][1] == {"action":"set_shuffle", "shuffle":True}


def test_indirect_request_is_locally_planned_and_schema_checked_before_tools():
    seen = []
    def planner(query, skill):
        seen.append((query, skill))
        return {"operation":"play_song", "query":"Blinding Lights"}
    agent, _, calls = fixture_agent(planner)
    response = agent.answer("Could you put Blinding Lights on for me using Spotify")
    assert response.status == "answered"
    assert seen
    bad, _, bad_calls = fixture_agent(lambda *_:{"operation":"delete_everything"})
    assert bad.answer("do something with spotify").status == "error"
    assert bad_calls == []


@pytest.mark.parametrize("action", ["save", "remove", "save_current", "remove_current"])
def test_spotify_tools_are_exclusive_to_specialist_and_mutations_require_confirmation(action):
    _, registry, calls = fixture_agent()
    with pytest.raises(ToolPermissionError):
        registry.invoke("spotify_search", {"query":"Blinding Lights"}, agent_name="XAgent")
    with pytest.raises(ToolPermissionError):
        registry.invoke("spotify_library", {"action":action, "kind":"tracks", "ids":["one"]}, agent_name="MusicAgent")
    assert calls == []


def test_specialist_profile_and_repeated_play_do_not_cache_side_effects(tmp_path):
    agent, _, calls = fixture_agent()
    catalog = AgentCatalog(profile_dir=tmp_path / "profiles", executors={"MusicAgent":agent})
    profile = catalog.get("MusicAgent")
    assert profile.skills.allow == ["spotify"]
    assert profile.memory.cache_first is False
    runtime = DelegationRuntime(agent_catalog=catalog, memory_orchestrator=None, audit_path=tmp_path / "audit.jsonl")
    for _ in range(2):
        result = runtime.delegate(DelegationRequest(agent_id="MusicAgent", task="play blinding lights", parent_thread_id="qa"))
        assert result.response.status == "answered"
    assert sum(name == "spotify_playback" for name, _ in calls) == 2
    assert "spotify" in catalog.specialist_skill_ids()


def test_discussion_and_other_platforms_are_not_music_commands():
    agent, _, _ = fixture_agent()
    for query in ("search X posts about Spotify", "explain how Spotify works", "play chess", "play the video on YouTube"):
        assert not agent.can_handle(query)


def test_other_music_services_can_supply_an_adapter_without_spotify_fallback():
    from agent.tools.registry import ToolRegistry
    class AppleIntegration:
        skill_id = "apple-music"
        def execute(self, plan, invoke):
            assert plan.provider == "apple_music"
            assert plan.query == "Blinding Lights"
            return "Apple Music playback requested."
    agent = MusicAgent(tool_registry=ToolRegistry(), integrations={"apple_music":AppleIntegration()}, skill_loader=lambda _:"")
    assert agent.answer("play Blinding Lights on Apple Music").summary == "Apple Music playback requested."
    assert agent.answer("play Blinding Lights on Spotify").status == "needs_fetch"


def test_music_intent_delegates_even_when_a_different_specialist_was_selected(tmp_path):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    from agent.agents.base import SpecialistResponse
    music, _, calls = fixture_agent()
    class SelectedX:
        def can_handle(self, query):
            return False
        def answer(self, query):
            return SpecialistResponse(agent="XAgent", status="answered", summary="Wrong specialist")
    state = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    state.set_active_agent("qa", "XAgent", selected=True)
    catalog = AgentCatalog(profile_dir=tmp_path / "profiles", executors={"XAgent":SelectedX(), "MusicAgent":music})
    runtime = DelegationRuntime(agent_catalog=catalog, memory_orchestrator=None, audit_path=tmp_path / "audit.jsonl")
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state, delegation_runtime=runtime)
    response = dispatcher.maybe_handle("play blinding lights", "qa")
    assert response.agent_name == "MusicAgent"
    assert "Playing Blinding Lights" in response.answer
    assert calls[-1][0] == "spotify_playback"
    assert state.get("qa").active_agent == "XAgent"
    assert state.get("qa").agent_selected is True


def test_music_results_are_returned_without_another_model_rewriting_them():
    from agent import api
    from agent.agents.live_dispatcher import LiveAgentResult
    for status in ("answered", "needs_fetch", "error", "blocked"):
        result = LiveAgentResult(handled=True, agent_name="MusicAgent", status=status, answer="Spotify paused.")
        assert api._should_passthrough_live_result(result)


def test_spotify_reads_do_not_become_automatic_knowledge_learning_sources():
    from unittest.mock import Mock
    from agent.knowledge.tool_observer import KnowledgeToolObserver
    from agent.tools.registry import CapabilityAccess, ToolInvocation
    core = Mock()
    KnowledgeToolObserver(core)(ToolInvocation(name="spotify_search", namespace="spotify", access=CapabilityAccess.READ,
        agent_name="MusicAgent", payload={"query":"private listening preference"}, result={"ok":True,"data":{}}))
    core.record_tool_result.assert_not_called()


def test_local_planner_refreshes_inventory_before_resolving_a_stale_default(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock, call
    from agent.llm import providers
    registry = Mock()
    registry.current_model.return_value = SimpleNamespace(id="ollama/gemma4:12b")
    monkeypatch.setattr(providers, "get_provider_registry", lambda: registry)
    model = Mock()
    model.invoke.return_value = SimpleNamespace(content='```json\n{"operation":"play_song","query":"Blinding Lights"}\n```')
    factory = Mock(return_value=model)
    plan = MusicPlan.model_validate(LocalMusicPlanner(model_factory=factory)("put Blinding Lights on for me", "Spotify procedure"))
    assert plan.query == "Blinding Lights"
    assert registry.mock_calls[:2] == [call.refresh_local_models(), call.current_model()]
    factory.assert_called_once_with("ollama/gemma4:12b")


def test_local_planner_does_not_send_music_requests_to_a_cloud_model():
    from unittest.mock import Mock
    factory = Mock()
    with pytest.raises(ValueError, match="local model"):
        LocalMusicPlanner(model_factory=factory, model_resolver=lambda:"openrouter/example")("play something", "")
    factory.assert_not_called()


@pytest.mark.parametrize("query", ["play the next song", "play next", "skip", "skip this song"])
def test_next_requests_never_search_for_a_song_title(query):
    agent, _, calls = fixture_agent()
    response = agent.answer(query)
    assert response.status == "answered"
    assert calls == [("spotify_playback", {"action":"next"})]
    assert "Skipped" in response.summary


def test_something_from_named_playlist_extracts_only_the_name():
    plan = MusicAgent._fast_plan("play something from my kannada playlist")
    assert plan.operation == "play_playlist"
    assert plan.query == "kannada"
    assert plan.shuffle is True


@pytest.mark.parametrize("query", ["play something from my liked songs", "soemthing from my liked songs"])
def test_liked_songs_is_a_library_request_not_a_playlist_name(query):
    agent, _, _ = fixture_agent()
    assert agent.can_handle(query)
    plan = agent._fast_plan(query)
    assert plan.operation == "play_liked"
    assert plan.shuffle is True


def test_ambiguous_ride_asks_for_artist_before_playing():
    tracks = [
        {"name":"The Ride", "uri":"spotify:track:drake", "artists":[{"name":"Drake"}]},
        {"name":"Ride", "uri":"spotify:track:pilots", "artists":[{"name":"Twenty One Pilots"}]},
    ]
    agent, _, calls = fixture_agent(tracks=tracks)
    response = agent.answer("play the ride")
    assert response.status == "needs_fetch"
    assert "Drake" in response.summary and "Twenty One Pilots" in response.summary
    assert all(name != "spotify_playback" for name, _ in calls)


@pytest.mark.parametrize("correction", ["from 21 on pilots", "Twenty One Pilots"])
def test_artist_correction_uses_thread_context_through_the_shared_dispatcher(tmp_path, correction):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    tracks = [
        {"name":"The Ride", "uri":"spotify:track:drake", "artists":[{"name":"Drake"}]},
        {"name":"Ride", "uri":"spotify:track:pilots", "artists":[{"name":"Twenty One Pilots"}]},
    ]
    music, _, calls = fixture_agent(tracks=tracks)
    catalog = AgentCatalog(profile_dir=tmp_path / "profiles", executors={"MusicAgent":music})
    state = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state)
    assert dispatcher.maybe_handle("play the ride", "music").status == "needs_fetch"
    result = dispatcher.maybe_handle(correction, "music")
    assert result.agent_name == "MusicAgent"
    assert result.answer == "Playing Ride by Twenty One Pilots."
    assert calls[-1] == ("spotify_playback", {"action":"play", "uris":["spotify:track:pilots"]})
    assert not music.can_handle_with_context("from 21 on pilots", state.get_specialist_context("another-thread", "MusicAgent"))


def test_kannada_playlist_matches_a_unique_decorated_name_and_randomizes_the_start():
    agent, _, calls = fixture_agent(playlists=[{"id":"kannada", "name":"Kannada Songs 🎧", "uri":"spotify:playlist:kannada"}])
    response = agent.answer("play something from my kannada playlist")
    assert response.summary == "Playing Kannada Songs 🎧 with shuffle on."
    play = next(args for name,args in calls if name == "spotify_playback")
    assert play["context_uri"] == "spotify:playlist:kannada"
    assert 0 <= play["offset"]["position"] < 4


def test_liked_songs_fetches_saved_tracks_and_plays_a_real_queue():
    tracks = [{"track":{"uri":f"spotify:track:liked{i}"}} for i in range(3)]
    agent, _, calls = fixture_agent(library={"items":tracks,"total":3})
    response = agent.answer("soemthing from my liked songs")
    assert response.summary == "Playing from your Liked Songs with shuffle on."
    assert calls[0] == ("spotify_library", {"action":"list", "kind":"tracks", "limit":50, "offset":0})
    assert set(calls[1][1]["uris"]) == {f"spotify:track:liked{i}" for i in range(3)}
    assert calls[2] == ("spotify_playback", {"action":"set_shuffle", "shuffle":True})
    assert all(name != "spotify_playlists" for name, _ in calls)


def test_explicit_artist_cannot_fall_back_to_a_different_artist():
    tracks = [{"name":"Ride", "uri":"spotify:track:wrong", "artists":[{"name":"Other artist"}]}]
    agent, _, calls = fixture_agent(tracks=tracks)
    assert "could not find" in agent.answer("play Ride by Twenty One Pilots").summary
    assert all(name != "spotify_playback" for name, _ in calls)


def test_create_playlist_previews_resolved_songs_and_waits_for_confirmation():
    agent, _, calls = fixture_agent()
    assert agent.can_handle('create a playlist called Night Drive with Blinding Lights by The Weeknd')
    response = agent.answer('create a playlist called Night Drive with Blinding Lights by The Weeknd')
    assert response.status == "needs_fetch"
    assert response.action_request["action"] == "music.create_playlist"
    assert response.action_request["payload"]["songs"][0]["uri"] == "spotify:track:original"
    assert "private" in response.summary and "Confirm" in response.summary
    assert [name for name, _ in calls] == ["spotify_search"]


@pytest.mark.parametrize("confirmation", ["confirm", "cancel"])
def test_playlist_creation_uses_the_same_pending_action_authority(tmp_path, confirmation):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    music, _, calls = fixture_agent()
    catalog = AgentCatalog(profile_dir=tmp_path / "profiles", executors={"MusicAgent":music})
    state = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state)
    preview = dispatcher.maybe_handle('create a playlist called Night Drive with Blinding Lights by The Weeknd', "music")
    assert "Confirm" in preview.answer
    result = dispatcher.maybe_handle(confirmation, "music")
    writes = [args for name,args in calls if name == "spotify_playlists"]
    if confirmation == "cancel":
        assert result.status == "blocked" and not writes
    else:
        assert result.status == "answered" and "Created private playlist Night Drive" in result.answer
        assert writes == [{"action":"create", "name":"Night Drive", "description":"", "public":False, "confirm":True},
                          {"action":"add_items", "playlist_id":"created", "uris":["spotify:track:original"], "confirm":True},
                          {"action":"get", "playlist_id":"created"},
                          {"action":"tracks", "playlist_id":"created", "limit":50}]
    repeated = dispatcher.delegation_runtime.delegate(DelegationRequest(agent_id="MusicAgent", task="confirm", parent_thread_id="music", confirm_pending_action=True))
    assert repeated.response.status == "blocked"
    assert [args for name,args in calls if name == "spotify_playlists"] == writes


def test_partial_playlist_creation_reports_the_created_playlist_without_replaying():
    from agent.contracts.music import MusicPlaylistCreateProposal
    service = SpotifyCapabilityService()
    calls = []
    def invoke(name, args):
        calls.append(args)
        if args["action"] == "create":
            return {"id":"created"}
        raise ValueError("network interruption")
    proposal = MusicPlaylistCreateProposal(provider="spotify", name="Night Drive", songs=[{"title":"Blinding Lights", "uri":"spotify:track:original"}])
    with pytest.raises(ValueError, match="Created Night Drive.*did not confirm"):
        service.create_playlist(proposal, invoke)
    assert len(calls) == 2
