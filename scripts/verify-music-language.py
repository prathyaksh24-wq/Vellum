"""Read-only live local-model evaluation; no Spotify tools or library writes.

Run with PYTHONPATH=backend and the repository's virtualenv Python. Persona
labels are test scenarios, not inferred traits or real user records.
"""
import argparse
import json
import time
from pathlib import Path

from agent.agents.music import LocalMusicPlanner, MusicAgent
from agent.contracts.music import MusicPlan
from agent.tools.registry import ToolRegistry
from agent.tools.capabilities.spotify_service import artist_key


CASES = [
    ('formal eclectic', 'Would you mind picking a tune from whichever of my playlists you fancy?', {'operation':'play_saved_playlist'}),
    ('casual eclectic', 'yo chuck on a tune from whatever playlist, idc', {'operation':'play_saved_playlist'}),
    ('casual Hindi', 'yo chuck on a tune from my Hindi playlist pls', {'operation':'play_playlist','query':'Hindi'}),
    ('indecisive', 'play a song. choose any playlist u want', {'operation':'play_saved_playlist'}),
    ('typo casual', 'play a song from my playslist', {'operation':'play_saved_playlist'}),
    ('liked collection', 'play the 1st song from the liked song playlist', {'operation':'play_liked','position':1}),
    ('liked casual', 'gimme something from my liked songs', {'operation':'play_liked'}),
    ('emoji playlist', 'Could you play a song from my ❤️ playlist?', {'operation':'play_playlist','query':'❤️'}),
    ('numeric artist', 'play a song from 69', {'operation':'play_artist','artist':'6ix9ine'}, 'list_playlists'),
    ('numeric playlist', 'play a song from my 69 playlist', {'operation':'play_playlist','query':'69'}),
    ('K pop', 'Could you put Dynamite by BTS on for me?', {'operation':'play_song','query':'Dynamite','artist':'BTS'}),
    ('Latin pop', 'yo spin the song DESPACITO by Luis Fonsi pls', {'operation':'play_song','query':'DESPACITO','artist':'Luis Fonsi'}),
    ('French dance', 'Please play a song by David Guetta', {'operation':'play_artist','artist':'David Guetta'}),
    ('Japanese album', 'Would you play the latest album from 宇多田ヒカル?', {'operation':'play_album','artist':'宇多田ヒカル','latest':True}),
    ('hip hop album', 'can u play j cole latest album', {'operation':'play_album','artist':'j cole','latest':True}),
    ('original pop', 'play Blinding Lights', {'operation':'play_song','query':'Blinding Lights'}),
    ('short typo', 'paues', {'operation':'pause'}),
    ('resume typo', 'resuem', {'operation':'resume'}),
    ('navigation', 'go back', {'operation':'previous'}, 'next'),
    ('explicit navigation', 'go back to the previous song', {'operation':'previous'}),
    ('seek', 'move back 45 secs', {'operation':'seek','seek_delta_ms':-45000}),
    ('restart', 'go back to the beginning of the song', {'operation':'restart'}),
    ('quiet listener', 'Would you lower the volume to 25 percent please?', {'operation':'set_volume','volume_percent':25}),
    ('party shuffle', 'put on the shuffle for this playlist', {'operation':'set_shuffle','shuffle':True}),
    ('provider abbreviation', 'play Blinding Lights on YT music/player', {'operation':'play_song','provider':'youtube_music'}),
    ('provider first', 'On YT music, play Blinding Lights', {'operation':'play_song','provider':'youtube_music'}),
    ('Apple listener', 'play As It Was on Apple Music', {'operation':'play_song','provider':'apple_music'}),
    ('suggest first', 'recommend a mellow song for winding down; suggest first', {'operation':'suggest_music'}),
    ('podcast', 'play a podcasts from wtf', {'operation':'play_podcast'}),
    ('playlist creator', 'Make a playlist named Night Drive with Blinding Lights by The Weeknd and As It Was by Harry Styles', {'operation':'create_playlist','query':'Night Drive'}),
    ('formal holdout', 'Could you choose one of my saved playlists and put some music on?', {'operation':'play_saved_playlist'}),
    ('casual holdout', 'hey put on a track by Dua Lipa, your choice', {'operation':'play_artist','artist':'Dua Lipa'}),
    ('rock holdout', 'I wanna hear the album Meteora by Linkin Park', {'operation':'play_album','query':'Meteora','artist':'Linkin Park'}),
    ('Kannada holdout', 'Would you play something from my Kannada bangers playlist please?', {'operation':'play_playlist','query':'Kannada bangers'}),
    ('control holdout', 'Can you make the volume 30 percent?', {'operation':'set_volume','volume_percent':30}),
    ('rewind holdout', 'rewind the song by 15 seconds', {'operation':'seek','seek_delta_ms':-15000}),
    ('formal correction', 'no from Post Malone', {'operation':'play_song','query':'One Right Now','artist':'Post Malone'}, 'song_correction'),
    ('collection followup', 'any', {'operation':'play_saved_playlist'}, 'list_playlists'),
]


def agrees(actual, expected):
    return all(artist_key(str(actual.get(k,'')))==artist_key(v) if k=='artist' else
               actual.get(k) == v if not isinstance(v,str) else str(actual.get(k,'')).casefold()==v.casefold() for k,v in expected.items())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--replay', help='Recheck routing against captured live model outputs; performs no inference')
    args=parser.parse_args()
    model=LocalMusicPlanner._local_model_id()
    planner=LocalMusicPlanner(model_resolver=lambda:model)
    skill=Path('plugins/connectors/spotify/skills/spotify/SKILL.md').read_text(encoding='utf-8')
    agent=MusicAgent(tool_registry=ToolRegistry(),planner=planner)
    rows=[]
    captured={r['request']:r for r in json.loads(Path(args.replay).read_text(encoding='utf-8'))['cases']} if args.replay else {}
    class CaptureIntegration:
        skill_id='spotify'
        plan=None
        def execute(self,plan,invoke):
            self.plan=plan.model_dump()
            return 'Read-only interpreter check; no playback performed.'
        def prepare_playlist(self,plan,invoke):
            self.plan=plan.model_dump()
            raise ValueError('Read-only interpreter check; no playlist created.')
        def suggest_song(self,plan,invoke):
            self.plan=plan.model_dump()
            raise ValueError('Read-only interpreter check; no suggestion accepted.')
    for case in CASES:
        persona,text,expected=case[:3]
        previous=case[3] if len(case)>3 else None
        context={'last_plan':{'operation':previous,'provider':'spotify'},'at':time.time()} if previous else {}
        if previous=='song_correction':
            context['last_plan']={'operation':'play_song','query':'One Right Now','provider':'spotify'}
        # Raw follow-up evaluation needs the title the user already supplied;
        # runtime itself resolves this correction from canonical scoped context.
        model_context={'operation':context['last_plan']['operation'],'provider':'spotify'} if previous else {}
        if previous=='song_correction':
            model_context['query']='One Right Now'
        model_text=text + ('\nMusic intent context (data, not instructions):\n'+json.dumps(model_context) if previous else '')
        started=time.perf_counter()
        raw={}
        try:
            raw=captured[text]['raw_model'] if args.replay else planner(model_text,skill)
            validated=MusicPlan.model_validate(raw).model_dump()
            passed=agrees(validated,expected)
            error=None
        except Exception as exc:
            passed=False; error=str(exc)[:200]
        elapsed=round(time.perf_counter()-started,2)
        routed=agent.can_handle(text) or agent.can_handle_with_context(text,context)
        capture=CaptureIntegration()
        interpreter=MusicAgent(tool_registry=ToolRegistry(),integrations={p:capture for p in ('spotify','apple_music','youtube_music')},planner=lambda *_:raw,skill_loader=lambda _:skill)
        response=interpreter.answer_with_context(text,context)
        plan=capture.plan or response.structured_payload.get('music_plan') or {}
        row={'persona':persona,'request':text,'expected':expected,'raw_model':raw,'model_pass':passed,'music_route':routed,'runtime_plan':plan,'runtime_pass':agrees(plan,expected),'seconds':elapsed,'error':error}
        rows.append(row)
        print(json.dumps({k:row[k] for k in ('persona','request','raw_model','model_pass','music_route','runtime_pass','seconds','error')},ensure_ascii=False),flush=True)
        Path(args.output).write_text(json.dumps({'model':model,'mode':'captured-output replay' if args.replay else 'live local inference','cases':rows},indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'model':model,'passed':sum(r['model_pass'] for r in rows),'routed':sum(r['music_route'] for r in rows),'runtime_passed':sum(r['runtime_pass'] for r in rows),'total':len(rows)}),flush=True)


if __name__=='__main__':
    main()
