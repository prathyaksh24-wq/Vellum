"""Canonical local music owner. No browser sessions, subscription caches or DRM keys.

Playlist occurrences survive independently of audio assets. Acquisitions are
durable, bounded jobs; only verified files enter the content-addressed library.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections import OrderedDict
import base64
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
from importlib.util import find_spec
import json
import os
from pathlib import Path
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event, RLock, Thread
import time
import unicodedata
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
from mutagen import File as AudioFile
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1

from agent.contracts.local_music import (LocalMusicCollection, LocalMusicEntry, LocalMusicJob,
    LocalMusicLibrary, LocalPlayerState, MusicSourceEntry, MusicImportRequest, LocalPlaybackRequest)

MAX_AUDIO_BYTES = 256 * 1024 * 1024
FORMATS = {'.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wav', '.webm'}
IMPORT_FORMATS = FORMATS | {'.aif','.aiff','.wma','.ape','.wv','.mp4','.m4b','.alac'}
YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}
AMAZON_HOSTS = {'music.amazon.'+suffix for suffix in ('com','in','co.uk','de','fr','it','es','co.jp','ca','com.au','com.br','com.mx')}


class MusicLibraryError(ValueError):
    pass


def ffmpeg_path():
    if find_spec('imageio_ffmpeg') is not None:
        from imageio_ffmpeg import get_ffmpeg_exe
        try:
            return get_ffmpeg_exe()
        except RuntimeError:
            pass
    return shutil.which('ffmpeg')


class _ApplePageData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = False
        self.capture = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and not self.found and dict(attrs).get('id') == 'serialized-server-data':
            self.capture = self.found = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)


class _CatalogPageData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture=False
        self.parts=[]
        self.blocks=[]

    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('type')=='application/ld+json':
            self.capture=True
            self.parts=[]

    def handle_data(self,data):
        if self.capture:self.parts.append(data)

    def handle_endtag(self,tag):
        if tag=='script' and self.capture:
            self.blocks.append(''.join(self.parts))
            self.capture=False


class DownloadCancellation(Event):
    """An acquisition loses authority as soon as its plugin is disabled."""
    def __init__(self, enabled):
        super().__init__()
        self.enabled = enabled

    def is_set(self): return super().is_set() or not self.enabled()
    def wait(self, timeout=None): return super().wait(timeout) or not self.enabled()


def source_link(value: str) -> tuple[str, str, str]:
    """Canonical provider identities; never pass arbitrary URL/options to a tool."""
    try:
        url = urlsplit(value.strip())
        if url.scheme != 'https' or url.username or url.password or url.port not in {None, 443}:
            raise ValueError()
        host = (url.hostname or '').lower()
        parts = url.path.strip('/').split('/')
        query = parse_qs(url.query)
        if host in YOUTUBE_HOSTS:
            playlist = (query.get('list') or [''])[0]
            video = parts[0] if host.endswith('youtu.be') else (query.get('v') or [''])[0]
            if playlist and re.fullmatch(r'[A-Za-z0-9_-]{10,100}', playlist):
                return 'youtube', 'playlist', 'https://www.youtube.com/playlist?list=' + playlist
            if re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
                return 'youtube', 'track', 'https://www.youtube.com/watch?v=' + video
        if host == 'open.spotify.com':
            if parts[0].startswith('intl-'): parts = parts[1:]
            if len(parts) == 2 and parts[0] in {'track', 'playlist', 'album'} and re.fullmatch(r'[A-Za-z0-9]{22}', parts[1]):
                return 'spotify', parts[0], 'https://open.spotify.com/' + '/'.join(parts)
        if host == 'music.apple.com' and len(parts) >= 3 and parts[1] in {'playlist', 'album', 'song'}:
            if re.fullmatch(r'[A-Za-z0-9.\-]+', parts[-1]):
                return 'apple_music', 'track' if parts[1] == 'song' else parts[1], value.strip()
        if host in AMAZON_HOSTS and len(parts)==2 and parts[0] in {'tracks','albums','playlists'} and re.fullmatch(r'[A-Za-z0-9_-]{5,100}',parts[1]):
            track=(query.get('trackAsin') or [''])[0]
            if track and re.fullmatch(r'[A-Z0-9]{10}',track):
                return 'amazon_music','track','https://'+host+'/tracks/'+track
            return 'amazon_music',{'tracks':'track','albums':'album','playlists':'playlist'}[parts[0]],'https://'+host+url.path
        if host in {'jiosaavn.com','www.jiosaavn.com','saavn.com','www.saavn.com'} and len(parts)>=3:
            kind='track' if parts[0]=='song' or parts[:2]==['s','song'] else 'album' if parts[0]=='album' else 'playlist' if parts[0]=='featured' or parts[:2]==['s','playlist'] else ''
            if kind:return 'jiosaavn',kind,'https://www.jiosaavn.com/'+ '/'.join(parts)
        if host in {'soundcloud.com','www.soundcloud.com'} and len(parts)>=2:
            return 'soundcloud','playlist' if 'sets' in parts else 'track','https://soundcloud.com/'+ '/'.join(parts)
        if host.endswith('.bandcamp.com') and len(parts)==2 and parts[0] in {'track','album'}:
            return 'bandcamp',parts[0],'https://'+host+'/'+ '/'.join(parts)
    except (ValueError, IndexError):
        pass
    raise MusicLibraryError('Use a full HTTPS music link from YouTube, Spotify, Apple Music, Amazon Music, JioSaavn, SoundCloud or Bandcamp.')


def youtube_audio_url(value: str) -> str:
    provider, kind, url = source_link(value)
    if provider != 'youtube' or kind != 'track':
        raise MusicLibraryError('Choose an exact YouTube recording. Spotify and Apple links import track information, not subscription audio.')
    return url


def downloadable_audio_url(value: str) -> str:
    provider,kind,url=source_link(value)
    if provider not in {'youtube','jiosaavn','soundcloud','bandcamp'} or kind!='track':
        raise MusicLibraryError('Choose an exact publicly downloadable recording.')
    return url


class MusicSources:
    """External discovery boundary, replaceable without changing the library."""
    def music_playlist(self, url):
        if find_spec('ytmusicapi') is None: return None
        from ytmusicapi import YTMusic
        identity = parse_qs(urlsplit(url).query)['list'][0]
        try:
            page = YTMusic().get_playlist(identity,limit=5000)
        except Exception:
            return None
        entries = []
        for row in (page.get('tracks') or [])[:5000]:
            video = str(row.get('videoId') or '')
            entries.append(MusicSourceEntry(title=str(row.get('title') or 'Unavailable song')[:500],
                artist=', '.join(artist.get('name','') for artist in row.get('artists') or [])[:500],
                album=str((row.get('album') or {}).get('name') or '')[:500],
                duration_ms=min(86400000,max(0,int(row.get('duration_seconds') or 0)*1000)),
                provider='youtube',source_id=video[:200],
                source_url='https://www.youtube.com/watch?v='+video if re.fullmatch(r'[A-Za-z0-9_-]{11}',video) else ''))
        total = page.get('trackCount')
        if not entries or not isinstance(total,int) or total != len(entries):
            return None
        return str(page.get('title') or 'YouTube Music playlist')[:200],entries,'complete','Full public song list read from YouTube Music.'

    def run_tool(self, args: list[str], *, cancel: Event | None = None, timeout=120, output_root=None, on_output=None):
        if find_spec('yt_dlp') is None:
            raise MusicLibraryError('The optional music downloader is not installed. Import audio files or install scripts/music-requirements.txt.')
        command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-cache-dir',
            '--no-plugin-dirs', '--no-exec', '--js-runtimes', 'node', '--no-progress', '--socket-timeout', '20', '--retries', '2',
            '--extractor-retries', '2', *args]
        # Ignore inherited proxies/config/plugins. Never read browser cookies or
        # accept user-supplied flags, executables, templates or output paths.
        environment = {key:value for key,value in os.environ.items()
            if key.upper() not in {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','PYTHONPATH','PYTHONSTARTUP'}}
        return self._run_process(command, cancel=cancel, timeout=timeout, output_root=output_root,
            on_output=on_output, environment=environment,
            failure='The recording could not be downloaded. It may require sign-in or be unavailable.')

    def _run_process(self, command, *, cancel, timeout, output_root, failure, on_output=None, environment=None):
        if cancel and cancel.is_set():
            raise MusicLibraryError('Download cancelled.')
        output_limit = 12 * 1024 * 1024
        with tempfile.TemporaryDirectory(prefix='vellum-music-tool-') as temporary:
            log = Path(temporary) / 'stdout'
            with log.open('wb') as output, log.open('rb') as reader:
                process = subprocess.Popen(command, stdout=output, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL, env=environment, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                started = time.monotonic()
                remainder = b''
                try:
                    while True:
                        if cancel and cancel.is_set():
                            raise MusicLibraryError('Download cancelled.')
                        if time.monotonic() - started > timeout or log.stat().st_size > output_limit:
                            raise MusicLibraryError('The recording exceeded the processing limits. You can retry.')
                        if output_root and any(file.is_file() and file.stat().st_size > MAX_AUDIO_BYTES for file in output_root.iterdir()):
                            raise MusicLibraryError('This recording exceeds the 256 MB file limit.')
                        if on_output:
                            lines = (remainder + reader.read(65536)).split(b'\n')
                            remainder = lines.pop()
                            for line in lines:
                                on_output(line.strip())
                        if process.poll() is not None:
                            break
                        if cancel: cancel.wait(0.2)
                        else: time.sleep(0.2)
                    if process.returncode:
                        raise MusicLibraryError(failure)
                    if on_output:
                        return ''
                    return reader.read(output_limit + 1).decode('utf-8')
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)

    def resolve(self, value: str):
        provider, kind, url = source_link(value)
        if provider == 'spotify': return self.spotify(kind, url)
        if provider == 'apple_music': return self.apple(url)
        if provider == 'amazon_music': return self.amazon(url)
        if provider in {'jiosaavn','soundcloud','bandcamp'}: return self.public_catalog(provider,kind,url)
        if kind == 'playlist':
            identity = parse_qs(urlsplit(url).query)['list'][0]
            music = self.music_playlist(url)
            if music is not None: return music
            official = self.youtube_playlist(url)
            if official is not None and official[2] == 'complete': return official
        else:
            official = None
        try:
            data = json.loads(self.run_tool(['--flat-playlist', '--skip-download', '--dump-single-json',
                '--playlist-end', '5000', '--', url], timeout=45 if official else 120))
        except Exception:
            if official is not None: return official
            raise
        raw = data.get('entries') if data.get('_type') == 'playlist' else [data]
        entries = []
        for row in raw or []:
            if not isinstance(row, dict):
                continue
            video = str(row.get('id') or '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video): continue
            entries.append(MusicSourceEntry(title=str(row.get('title') or 'Unavailable song')[:500],
                artist=str(row.get('artist') or row.get('uploader') or row.get('channel') or '')[:500],
                duration_ms=min(86400000, int((row.get('duration') or 0) * 1000)), provider='youtube',
                source_id=video, source_url='https://www.youtube.com/watch?v=' + video))
        total = data.get('playlist_count')
        complete = kind == 'track' or isinstance(total, int) and total == len(entries)
        if official is not None and len(official[1]) >= len(entries):
            return official
        return str(data.get('title') or 'YouTube playlist')[:200], entries, 'complete' if complete else 'unknown', 'Public playlist snapshot. Private, removed, or unlisted entries may be missing.'

    def youtube_playlist(self, url):
        """Read private playlist metadata only through the existing OAuth owner."""
        from agent.plugins.registry import get_plugin_registry
        from agent.plugins.youtube_runtime import youtube_client, youtube_status
        if not get_plugin_registry().is_enabled('youtube') or not youtube_status().get('connected'): return None
        identity = parse_qs(urlsplit(url).query)['list'][0]
        client = youtube_client()
        try:
            header = client._api_get('/playlists',params={'part':'snippet,contentDetails','id':identity})
            item = (header.get('items') or [{}])[0]
            title = str(item.get('snippet',{}).get('title') or 'YouTube playlist')[:200]
            token,entries,total = '',[],item.get('contentDetails',{}).get('itemCount')
            seen_tokens = set()
            for _ in range(100):
                page = client._api_get('/playlistItems',params={'part':'snippet,contentDetails','playlistId':identity,'maxResults':50,**({'pageToken':token} if token else {})})
                for row in page.get('items',[]):
                    snippet,details = row.get('snippet') or {},row.get('contentDetails') or {}
                    video = str(details.get('videoId') or snippet.get('resourceId',{}).get('videoId') or '')
                    entries.append(MusicSourceEntry(title=str(snippet.get('title') or 'Unavailable song')[:500],
                        artist=str(snippet.get('videoOwnerChannelTitle') or '')[:500],provider='youtube',source_id=video,
                        source_url='https://www.youtube.com/watch?v='+video if re.fullmatch(r'[A-Za-z0-9_-]{11}',video) else ''))
                reported = (page.get('pageInfo') or {}).get('totalResults')
                if reported:
                    total = max(total or 0,reported)
                token = page.get('nextPageToken') or ''
                if not token or token in seen_tokens: break
                seen_tokens.add(token)
            if not entries: return None
            complete = not token and total == len(entries)
            note = 'Playlist information imported through your connected YouTube account.'
            if not complete:
                note = f'YouTube exposed {len(entries)} songs. The full playlist could not be verified.'
                if identity.startswith('RD'):
                    note += ' Personalized mixes can differ from the queue shown in YouTube Music. A saved playlist link can expose the full list.'
            return title,entries,'complete' if complete else 'partial',note
        except Exception:
            # Public fallback must still identify itself as an unverified snapshot.
            return None

    def spotify(self, kind, url):
        from agent.plugins.registry import get_plugin_registry
        from agent.plugins.spotify_runtime import spotify_client, spotify_catalog_query_gate
        if not get_plugin_registry().is_enabled('spotify'):
            raise MusicLibraryError('Enable and connect Spotify to import its playlist information.')
        _query, blocked = spotify_catalog_query_gate(url)
        if blocked: raise MusicLibraryError('This source link could not be shared with Spotify.')
        client, identity = spotify_client(), url.rsplit('/', 1)[1]
        root={}
        try:
            root = client.request('GET', f'/{"tracks" if kind == "track" else kind + "s"}/{identity}')
            if kind == 'track': raw, total = [root], 1
            else:
                raw, total, offset = [], None, 0
                endpoint = f'/{kind}s/{identity}/' + ('items' if kind == 'playlist' else 'tracks')
                while True:
                    page = client.request('GET', endpoint, params={'limit':50, 'offset':offset})
                    rows = page.get('items') or []
                    raw.extend((row.get('item') or row.get('track') or {}) if kind == 'playlist' else row for row in rows)
                    total = page.get('total')
                    if not page.get('next') or not rows or len(raw) >= 5000: break
                    offset += len(rows)
            entries = [MusicSourceEntry(title=str(row.get('name') or 'Unavailable song')[:500],
                artist=', '.join(a.get('name', '') for a in row.get('artists') or [])[:500],
                album=str((row.get('album') or {}).get('name') or '')[:500], provider='spotify',
                source_id=str(row.get('id') or '')[:200], duration_ms=min(86400000,int(row.get('duration_ms') or 0)),
                source_url=str((row.get('external_urls') or {}).get('spotify') or '')[:2048]) for row in raw[:5000]]
        except Exception as exc:
            if kind!='playlist' or getattr(exc,'code','') not in {'access_denied','resource_unavailable'}:raise
            from agent.plugins.spotify_runtime import spotify_public_playlist
            try: rows=spotify_public_playlist.read_public_playlist(identity)
            except spotify_public_playlist.PublicPlaylistUnavailable as unavailable:raise MusicLibraryError('Spotify did not expose this playlist. Import a playlist manifest or add your audio files.') from unavailable
            entries=[MusicSourceEntry(title=row['name'],artist=', '.join(row.get('artists') or []),
                album=row.get('album') or '',duration_ms=row.get('duration_ms') or 0,provider='spotify',
                source_id=row.get('id') or '',source_url=row.get('external_url') or '') for row in rows]
            title=str(root.get('name') or spotify_public_playlist.cached_public_playlist_name(identity) or 'Spotify playlist')[:200]
            return title,entries,'unknown','Public Spotify playlist. The source may omit some tracks.'
        return str(root.get('name') or 'Spotify playlist')[:200], entries, 'complete' if total == len(entries) else 'partial', 'Track information imported from Spotify.'

    def apple(self, url):
        # Fixed public host; redirects are rejected rather than used as a proxy.
        with httpx.Client(timeout=25, trust_env=False, follow_redirects=False) as client:
            with client.stream('GET', url, headers={'User-Agent':'Mozilla/5.0'}) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 8 * 1024 * 1024: raise MusicLibraryError('This Apple Music page is too large to import.')
                    chunks.append(chunk)
        page = b''.join(chunks).decode('utf-8')
        parser = _ApplePageData()
        parser.feed(page)
        if not parser.found:
            raise MusicLibraryError('Apple Music did not expose this public playlist.')
        payload = json.loads(''.join(parser.parts))
        songs, title = [], 'Apple Music playlist'
        def walk(node, depth=0):
            nonlocal title
            if depth > 60: return
            if isinstance(node, list):
                for child in node: walk(child, depth + 1)
            elif isinstance(node, dict):
                desc = node.get('contentDescriptor') or {}
                if desc.get('kind') in {'album','playlist'} and isinstance(node.get('title'),str): title = node['title'][:200]
                if desc.get('kind') == 'song' and isinstance(node.get('title'),str) and isinstance(node.get('artistName'),str):
                    songs.append(MusicSourceEntry(title=node['title'][:500],artist=node['artistName'][:500],provider='apple_music',
                        source_id=str((desc.get('identifiers') or {}).get('storeAdamID') or '')[:200],
                        source_url=str(desc.get('url') or '')[:2048]))
                    return
                for child in node.values(): walk(child, depth + 1)
        walk(payload)
        selected = (parse_qs(urlsplit(url).query).get('i') or [''])[0]
        if '/song/' in urlsplit(url).path: selected = urlsplit(url).path.rsplit('/',1)[-1]
        if selected: songs = [row for row in songs if row.source_id == selected][:1]
        if selected and songs:
            title = songs[0].title[:200]
        return title, songs[:5000], 'complete' if selected and len(songs)==1 else 'unknown', 'Apple public-page snapshot; playlist completeness could not be verified. This imports track information only.'

    def public_catalog(self, provider, kind, url):
        data=json.loads(self.run_tool(['--flat-playlist','--skip-download','--dump-single-json','--playlist-end','5000','--',url]))
        raw=data.get('entries') if data.get('_type')=='playlist' else [data]
        entries=[]
        for row in raw or []:
            if not isinstance(row,dict):continue
            candidate=row.get('webpage_url') or row.get('url') or (url if kind=='track' else '')
            try:
                source_provider,source_kind,recording=source_link(str(candidate))
            except MusicLibraryError:
                continue
            if source_provider!=provider or source_kind!='track':continue
            try:thumbnail=MusicSourceEntry.public_thumbnail(str(row.get('thumbnail') or ''))
            except ValueError:thumbnail=''
            entries.append(MusicSourceEntry(title=str(row.get('track') or row.get('title') or 'Untitled song')[:500],
                artist=str(row.get('artist') or ', '.join(row.get('artists') or []) or row.get('uploader') or '')[:500],
                album=str(row.get('album') or '')[:500],duration_ms=min(86400000,max(0,int((row.get('duration') or 0)*1000))),
                provider=provider,source_id=str(row.get('id') or '')[:200],source_url=recording,thumbnail_url=thumbnail))
        total=data.get('playlist_count',len(raw or []))
        complete=kind=='track' or len(entries)==total and len(entries)<5000
        return str(data.get('title') or 'Imported music')[:200],entries,'complete' if complete else 'partial','Public music catalog.'

    def amazon(self, url):
        parser=_CatalogPageData()
        with httpx.Client(timeout=20,trust_env=False,follow_redirects=False) as client:
            with client.stream('GET',url,headers={'User-Agent':'Mozilla/5.0'}) as response:
                response.raise_for_status()
                size,chunks=0,[]
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>8*1024*1024:raise MusicLibraryError('This music page is too large to import.')
                    chunks.append(chunk)
        parser.feed(b''.join(chunks).decode('utf-8'))
        songs,title,total=[], 'Amazon Music',None
        def walk(node,depth=0):
            nonlocal title,total
            if depth>60:return
            if isinstance(node,list):
                for item in node:walk(item,depth+1)
            elif isinstance(node,dict):
                kind=node.get('@type')
                if kind in ('MusicAlbum','MusicPlaylist'):
                    title=str(node.get('name') or title)[:200]
                    if isinstance(node.get('numTracks'),int):total=node['numTracks']
                if kind=='MusicRecording' and node.get('name'):
                    raw_artists=node.get('byArtist') or []
                    if isinstance(raw_artists,dict):raw_artists=[raw_artists]
                    artist=', '.join(str(item.get('name') or '') for item in raw_artists if isinstance(item,dict))
                    recording=str(node.get('url') or '')
                    try:
                        provider,source_kind,recording=source_link(recording)
                        if provider!='amazon_music' or source_kind!='track':recording=''
                    except MusicLibraryError:recording=''
                    album=node.get('inAlbum') or {}
                    songs.append(MusicSourceEntry(title=str(node['name'])[:500],artist=artist[:500],
                        album=str(album.get('name') or '')[:500] if isinstance(album,dict) else '',
                        provider='amazon_music',source_url=recording))
                    return
                for item in node.values():walk(item,depth+1)
        for block in parser.blocks:
            try:walk(json.loads(block))
            except ValueError:continue
        if not songs:
            raise MusicLibraryError('Amazon Music did not expose a public song list for this link. Import a playlist file or your audio files.')
        return title,songs[:5000],'complete' if total==len(songs) else 'unknown','Public Amazon Music catalog metadata.'

    def discover(self, query):
        if find_spec('ytmusicapi') is None:
            raise MusicLibraryError('Music search is optional. Paste an exact YouTube song link, or install scripts/music-requirements.txt.')
        from ytmusicapi import YTMusic
        # Public discovery only; no headers, credentials, cookies or OAuth reuse.
        client = YTMusic()
        rows = client.search(query, filter='songs', limit=8)
        return [MusicSourceEntry(title=str(row.get('title') or 'Untitled')[:500],
            artist=', '.join(a.get('name','') for a in row.get('artists') or [])[:500],
            album=str((row.get('album') or {}).get('name') or '')[:500],
            duration_ms=min(86400000, max(0, int((row.get('duration_seconds') or 0) * 1000))),
            provider='youtube', source_id=row['videoId'], source_url='https://www.youtube.com/watch?v='+row['videoId'])
            for row in rows[:8] if row.get('isAvailable') is not False and re.fullmatch(r'[A-Za-z0-9_-]{11}',str(row.get('videoId') or ''))]

    def find_recording(self, entry):
        """Resolve a catalog entry by song, artist and available version metadata."""
        def normalized(value):
            return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())

        if not entry.artist.strip():
            raise MusicLibraryError('The playlist did not provide enough information to find this recording.')
        candidates = self.discover((entry.title + ' ' + entry.artist)[:200])
        matches = {candidate.source_url: candidate for candidate in candidates
                   if normalized(candidate.title) == normalized(entry.title)
                   and normalized(candidate.artist) == normalized(entry.artist)
                   and (not entry.duration_ms or candidate.duration_ms
                        and abs(candidate.duration_ms - entry.duration_ms) <= 3500)}
        album_matches = [item for item in matches.values()
                         if entry.album and normalized(item.album) == normalized(entry.album)]
        recordings = album_matches or list(matches.values())
        if len(recordings) != 1:
            raise MusicLibraryError('A single matching recording could not be verified.')
        return youtube_audio_url(recordings[0].source_url)

    def download(self, url, directory, cancel, *, on_output=None):
        url = downloadable_audio_url(url)
        progress_args = ['--write-thumbnail', '--progress', '--newline', '--progress-template',
            'download:vellum-bytes:%(progress.downloaded_bytes)s:%(progress.total_bytes,progress.total_bytes_estimate)s'] if on_output else []
        self.run_tool(['--no-playlist', '--max-filesize', str(MAX_AUDIO_BYTES),
            '-f', 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
            *progress_args, '--paths', str(directory), '-o', 'audio.%(ext)s', '--', url],
            cancel=cancel, timeout=600, output_root=directory, on_output=on_output)
        files = [file for file in directory.iterdir() if file.suffix.lower() in FORMATS and file.is_file()]
        if len(files) != 1: raise MusicLibraryError('The source did not return one supported audio file.')
        return files[0]

    def download_mp3(self, url, directory, cancel, entry, update):
        converter = ffmpeg_path()
        if not converter:
            raise MusicLibraryError('MP3 conversion needs FFmpeg. Install the optional music tools.')

        def download_progress(line):
            fields = line.split(b':')
            if len(fields) == 3 and fields[0] == b'vellum-bytes' and fields[1].isdigit() and fields[2].isdigit():
                if len(fields[1]) <= 18 and len(fields[2]) <= 18 and int(fields[2]):
                    update('downloading', min(100, int(fields[1]) * 100 // int(fields[2])))

        update('downloading')
        source = self.download(url, directory, cancel, on_output=download_progress)
        output = directory / 'converted.mp3'
        audio = AudioFile(source) if source.suffix.lower() != '.webm' else None
        duration_us = int(audio.info.length * 1000000) if audio and audio.info else entry.duration_ms * 1000

        def conversion_progress(line):
            key, _, value = line.partition(b'=')
            if duration_us > 0 and key == b'out_time_us' and len(value) <= 18 and value.isdigit():
                update('converting', min(99, int(value) * 100 // duration_us))

        update('converting')
        self._run_process([converter, '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-protocol_whitelist', 'file', '-format_whitelist', 'mov,matroska,webm,mp3,flac,wav,ogg,aac',
            '-i', str(source), '-map', '0:a:0', '-map_metadata', '-1', '-codec:a', 'libmp3lame',
            '-q:a', '2', '-progress', 'pipe:1', '-nostats', str(output)],
            cancel=cancel, timeout=180, output_root=directory, on_output=conversion_progress,
            failure='Vellum could not convert this recording into an MP3.')
        tags = ID3()
        tags.add(TIT2(encoding=3, text=entry.title))
        if entry.artist:
            tags.add(TPE1(encoding=3, text=entry.artist))
        if entry.album:
            tags.add(TALB(encoding=3, text=entry.album))
        for suffix, mime in (('.jpg', 'image/jpeg'), ('.jpeg', 'image/jpeg'), ('.png', 'image/png'), ('.webp', 'image/webp')):
            thumbnail = directory / ('audio' + suffix)
            if thumbnail.is_file() and 0 < thumbnail.stat().st_size <= 4 * 1024 * 1024:
                tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=thumbnail.read_bytes()))
                break
        tags.save(output, v2_version=3)
        return output


class MusicLibrary:
    def __init__(self, root: Path, *, sources=None, start_worker=True, enabled=lambda:True):
        self.root, self.sources = Path(root), sources or MusicSources()
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets = self.root / 'audio'
        self.assets.mkdir(exist_ok=True)
        self.covers = self.root / 'artwork'
        self.covers.mkdir(exist_ok=True)
        self.staging = self.root / 'staging'
        self.staging.mkdir(exist_ok=True)
        self._lock, self._wake, self._cancels = RLock(), Event(), {}
        self._start_worker, self._threads = start_worker, []
        self._stopped = Event()
        self._enabled = enabled
        self._cover_cache = OrderedDict()
        self._cover_lock = RLock()
        # Interrupted subprocess files belong only to this library's staging
        # directory. Never traverse symlinks or remove user-selected originals.
        for partial in self.staging.glob('download-*'):
            if partial.is_dir() and not partial.is_symlink() and partial.resolve().parent == self.staging.resolve():
                shutil.rmtree(partial)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS collections(id TEXT PRIMARY KEY,name TEXT NOT NULL,source_url TEXT,completeness TEXT,note TEXT);
                CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,suffix TEXT NOT NULL,audio_source TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,collection_id TEXT NOT NULL,position INTEGER NOT NULL,metadata TEXT NOT NULL,asset_id TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,entry_id TEXT NOT NULL,url TEXT NOT NULL,status TEXT NOT NULL,error TEXT NOT NULL DEFAULT '');
                CREATE UNIQUE INDEX IF NOT EXISTS active_acquisition ON jobs(entry_id) WHERE status IN ('queued','running');
                CREATE TABLE IF NOT EXISTS stages(id TEXT PRIMARY KEY,suffix TEXT NOT NULL,metadata TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS player(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL,owner TEXT NOT NULL DEFAULT '',expires REAL NOT NULL DEFAULT 0);
            ''')
            for table, columns in (
                ('collections', {'pending_import': 'INTEGER NOT NULL DEFAULT 0','auto_import':'INTEGER NOT NULL DEFAULT 0'}),
                ('jobs', {'mp3': 'INTEGER NOT NULL DEFAULT 0', 'stage': "TEXT NOT NULL DEFAULT ''", 'progress': 'INTEGER'}),
            ):
                existing = {column['name'] for column in db.execute(f'PRAGMA table_info({table})')}
                for name, definition in columns.items():
                    if name not in existing:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            row = db.execute('SELECT state FROM player WHERE id=1').fetchone()
            state = json.loads(row['state']) if row else LocalPlayerState().model_dump()
            state['playing'], state['observed'] = False, {}
            db.execute('INSERT OR REPLACE INTO player(id,state,owner,expires) VALUES(1,?,\'\',0)',(json.dumps(state),))
            db.execute("UPDATE jobs SET status='failed',stage='',progress=NULL,error='Vellum stopped during this download. Retry to continue.' WHERE status='running'")

    @contextmanager
    def db(self):
        with self._lock:
            db = sqlite3.connect(self.root / 'library.sqlite3', timeout=15)
            db.row_factory = sqlite3.Row
            try:
                with db: yield db
            finally: db.close()

    def _ensure_worker(self):
        with self._lock:
            if self._stopped.is_set(): return
            self._threads = [thread for thread in self._threads if thread.is_alive()]
            if self._start_worker:
                for index in range(len(self._threads),3):
                    thread = Thread(target=self._work, name=f'vellum-music-download-{index}', daemon=True)
                    self._threads.append(thread)
                    thread.start()
        self._wake.set()

    def close(self):
        self._stopped.set()
        with self._lock:
            for cancel in self._cancels.values(): cancel.set()
        self._wake.set()
        for thread in self._threads: thread.join(timeout=2)

    def snapshot(self):
        self._ensure_worker()
        with self.db() as db:
            groups = db.execute('SELECT * FROM collections ORDER BY rowid DESC').fetchall()
            rows = db.execute('SELECT * FROM entries ORDER BY collection_id,position').fetchall()
            assets = {row['id']: row for row in db.execute('SELECT * FROM assets')}
            jobs = db.execute("""
                SELECT j.id, j.entry_id, j.status, j.error, j.stage, j.progress,
                       json_extract(e.metadata, '$.title') AS title
                FROM jobs j JOIN entries e ON e.id = j.entry_id
                WHERE j.rowid IN (SELECT max(rowid) FROM jobs GROUP BY entry_id)
                ORDER BY j.rowid DESC
            """).fetchall()
            player = self._player(db)
        entries_by_group = {}
        for row in rows:
            entry = self._project_entry(row, assets.get(row['asset_id']), artwork=True)
            entries_by_group.setdefault(row['collection_id'], []).append(entry)
        collections, pending_imports = [], []
        for group in groups:
            target = pending_imports if group['pending_import'] else collections
            target.append(LocalMusicCollection(**dict(group), entries=entries_by_group.get(group['id'], [])))
        downloader = find_spec('yt_dlp') is not None
        return LocalMusicLibrary(collections=collections, pending_imports=pending_imports,
            jobs=[LocalMusicJob(**dict(row)) for row in jobs], player=player,
            downloader_available=downloader, discovery_available=find_spec('ytmusicapi') is not None,
            mp3_available=downloader and bool(ffmpeg_path()))

    def _entry(self, db, row):
        asset = db.execute('SELECT * FROM assets WHERE id=?',(row['asset_id'],)).fetchone()
        return self._project_entry(row, asset)

    def entry(self, identity):
        with self.db() as db:
            row = db.execute('''SELECT e.* FROM entries e JOIN collections c ON c.id=e.collection_id
                WHERE e.id=? AND c.pending_import=0''', (identity,)).fetchone()
            if row is None:
                raise MusicLibraryError('This song is no longer in your library.')
            asset = db.execute('SELECT * FROM assets WHERE id=?', (row['asset_id'],)).fetchone()
        return self._project_entry(row, asset, artwork=True)

    def _project_entry(self, row, asset, *, artwork=False):
        available = bool(asset and (self.assets / (asset['id']+asset['suffix'])).is_file())
        metadata = json.loads(row['metadata'])
        cover = ''
        if artwork and available and self._embedded_cover(asset):
            cover = '/api/music/local/artwork/'+row['id']
        elif metadata.get('provider') == 'youtube' and re.fullmatch(r'[A-Za-z0-9_-]{11}',metadata.get('source_id','')):
            cover = 'https://i.ytimg.com/vi/'+metadata['source_id']+'/hqdefault.jpg'
        elif metadata.get('thumbnail_url'):
            cover = metadata['thumbnail_url']
        return LocalMusicEntry(**metadata,id=row['id'],available=available,audio_source=asset['audio_source'] if asset else '',artwork_url=cover)

    def _embedded_cover(self, asset):
        """Derived local artwork only; audio and playlist metadata stay unchanged."""
        identity=asset['id']
        with self._cover_lock:
            if identity in self._cover_cache:
                self._cover_cache.move_to_end(identity)
                return self._cover_cache[identity]
            for suffix in ('.png','.jpg','.webp'):
                existing=self.covers/(identity+suffix)
                if existing.is_file() and existing.resolve().is_relative_to(self.covers.resolve()):return existing
            missing=self.covers/(identity+'.none')
            if missing.is_file():return None
            result=None
            file=self.assets/(identity+asset['suffix'])
            if not file.is_file() or not file.resolve().is_relative_to(self.assets.resolve()):return None
            try:
                audio=AudioFile(file, easy=False)
                tags=getattr(audio,'tags',None) or {}
                pictures=[picture.data for picture in getattr(audio,'pictures',[])[:8]]
                if hasattr(tags,'getall'):pictures.extend(frame.data for frame in tags.getall('APIC')[:8])
                pictures.extend((tags.get('covr') or [])[:8])
                for encoded in (tags.get('metadata_block_picture') or [])[:8]:
                    if isinstance(encoded,str) and len(encoded)<=6*1024*1024:
                        from mutagen.flac import Picture
                        pictures.append(Picture(base64.b64decode(encoded,validate=True)).data)
                for data in pictures:
                    if not isinstance(data,bytes) or not 0<len(data)<=4*1024*1024:continue
                    suffix='.png' if data.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg' if data.startswith(b'\xff\xd8\xff') else '.webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else ''
                    if not suffix:continue
                    target=self.covers/(identity+suffix)
                    if not target.exists():
                        temporary=self.covers/(uuid4().hex+'.part')
                        try:temporary.write_bytes(data);temporary.replace(target)
                        finally:temporary.unlink(missing_ok=True)
                    if target.resolve().is_relative_to(self.covers.resolve()):result=target
                    break
            except Exception:
                # Missing/malformed cover art must never invalidate playable audio.
                pass
            if result is None:
                try:missing.touch(exist_ok=True)
                except OSError:pass
            self._cover_cache[identity]=result
            while len(self._cover_cache)>256:self._cover_cache.popitem(last=False)
            return result

    def artwork_path(self, entry_id):
        with self.db() as db:
            asset=db.execute('SELECT a.* FROM entries e JOIN assets a ON a.id=e.asset_id WHERE e.id=?',(entry_id,)).fetchone()
            if asset is None: raise MusicLibraryError('This song has no downloaded artwork yet.')
        path=self._embedded_cover(asset)
        if not path:raise MusicLibraryError('This file has no supported embedded cover.')
        return path

    def import_playlist(self, request: MusicImportRequest):
        if request.pending_import_id:
            return self.finish_import(request.pending_import_id)
        if request.url:
            url = source_link(request.url)[2]
            if request.download_mp3:
                self.require_mp3_tools()
            title, entries, completeness, note = self.sources.resolve(url)
            provider,kind,_ = source_link(url)
            if request.download_mp3 and provider=='youtube' and kind=='playlist' and parse_qs(urlsplit(url).query)['list'][0].startswith('RD') and completeness!='complete':
                raise MusicLibraryError("YouTube did not expose this mix's full song list. Save the mix as a regular playlist and paste that playlist's share link.")
        else:
            title, entries, completeness, note, url = request.name, request.entries, request.completeness, 'Imported track information. Missing audio can be supplied separately.', request.source_origin
        if not entries: raise MusicLibraryError('No readable songs were found. Nothing was added.')
        identity = uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO collections(id,name,source_url,completeness,note,pending_import,auto_import) VALUES(?,?,?,?,?,?,?)',
                       (identity, title, url, completeness, note, request.download_mp3,request.auto_import))
            for position, entry in enumerate(entries[:5000]):
                entry_id = uuid4().hex
                db.execute('INSERT INTO entries VALUES(?,?,?,?,NULL)',(entry_id,identity,position,entry.model_dump_json()))
                if request.download_mp3:
                    self._queue_mp3(db, entry_id, entry)
        if request.download_mp3:
            self._ensure_worker()
            return {'changed': True, 'collection_id': identity, 'name': title, 'count': len(entries[:5000]),
                    '_message': f'Preparing MP3s for {title}.'}
        return {'changed':True,'collection_id':identity,'count':len(entries[:5000]),'completeness':completeness,
            '_message':f'Imported {len(entries[:5000])} track references. Audio availability is shown separately.'}

    def finish_import(self, identity):
        with self.db() as db:
            collection = db.execute('SELECT name,pending_import FROM collections WHERE id=?', (identity,)).fetchone()
            if not collection:
                raise MusicLibraryError('This playlist could not be found.')
            if not collection['pending_import']:
                return {'changed': False, 'collection_id': identity, '_message': 'This playlist is already in your library.'}
            if db.execute("""SELECT 1 FROM jobs JOIN entries ON entries.id=jobs.entry_id
                           WHERE collection_id=? AND status IN ('queued','running')""", (identity,)).fetchone():
                raise MusicLibraryError('Wait for the playlist downloads to finish.')
            rows = db.execute('SELECT * FROM entries WHERE collection_id=?', (identity,)).fetchall()
            count = sum(self._entry(db, row).available for row in rows)
            if not count:
                raise MusicLibraryError('This playlist has no playable downloads yet.')
            db.execute('UPDATE collections SET pending_import=0 WHERE id=?', (identity,))
        return {'changed': True, 'collection_id': identity, 'count': count,
                '_message': f'Imported {collection["name"]} with {count} playable songs.'}

    def refresh_playlist(self, identity):
        with self.db() as db:
            group = db.execute('SELECT * FROM collections WHERE id=?',(identity,)).fetchone()
            if group is None or not group['source_url']:
                raise MusicLibraryError('Choose a playlist imported from a link.')
            url = group['source_url']
        title, entries, completeness, note = self.sources.resolve(url)
        if not entries:
            raise MusicLibraryError('The source did not expose any songs. Try again later.')
        with self.db() as db:
            if not db.execute('SELECT 1 FROM collections WHERE id=?',(identity,)).fetchone():
                raise MusicLibraryError('This playlist was removed while its songs were loading.')
            rows = db.execute('SELECT * FROM entries WHERE collection_id=? ORDER BY position',(identity,)).fetchall()
            counts = {}
            for row in rows:
                entry = MusicSourceEntry.model_validate_json(row['metadata'])
                key = (entry.provider,entry.source_id or entry.source_url or (entry.title,entry.artist,entry.album))
                counts[key] = counts.get(key,0)+1
            added, seen = 0,{}
            position = max((row['position'] for row in rows),default=-1)+1
            for entry in entries[:5000]:
                key = (entry.provider,entry.source_id or entry.source_url or (entry.title,entry.artist,entry.album))
                seen[key] = seen.get(key,0)+1
                if seen[key] <= counts.get(key,0): continue
                db.execute('INSERT INTO entries VALUES(?,?,?,?,NULL)',(uuid4().hex,identity,position+added,entry.model_dump_json()))
                added += 1
            if sum(counts.values())+added != len(entries):
                completeness = 'partial'
            name = group['name'] if title == 'YouTube playlist' else title
            db.execute('UPDATE collections SET name=?,completeness=?,note=? WHERE id=?',(name,completeness,note,identity))
        return {'changed':True,'added':added,'_message':f'Playlist refreshed. {added} new songs found.'}

    def _inspect_audio(self, file: Path):
        suffix = file.suffix.lower()
        if suffix not in FORMATS or file.stat().st_size > MAX_AUDIO_BYTES or not file.stat().st_size:
            raise MusicLibraryError('Choose an audio file up to 256 MB: MP3, FLAC, M4A, AAC, Ogg, Opus, WAV or WebM.')
        try:
            # Mutagen does not parse WebM. Verify its EBML container signature;
            # actual decoding readiness is measured by the native audio element.
            if suffix == '.webm':
                with file.open('rb') as handle:
                    header = handle.read(65536)
                    if not header.startswith(b'\x1aE\xdf\xa3') or b'webm' not in header or not any(codec in header for codec in (b'A_OPUS',b'A_VORBIS')):
                        raise ValueError()
                return MusicSourceEntry(title=file.stem)
            audio = AudioFile(file, easy=True)
            if audio is None or not audio.info or not 0 < audio.info.length <= 86400: raise ValueError()
            # Encrypted Apple subscription tracks must not enter the local player.
            if getattr(audio.info,'codec','') in {'drms','drmi'}: raise ValueError()
            tags = audio.tags or {}
            def tag(key):
                value = tags.get(key) or ['']
                return str(value[0] if isinstance(value,list) else value)[:500]
            return MusicSourceEntry(title=tag('title') or file.stem[:500],artist=tag('artist'),album=tag('album'),duration_ms=int(audio.info.length*1000))
        except Exception as exc:
            raise MusicLibraryError('This file could not be read as unprotected audio. Supply an owned, DRM-free audio file.') from exc

    def stage_file(self, filename: str, content: bytes):
        suffix = Path(filename).suffix.lower()
        if suffix not in IMPORT_FORMATS or len(content) > MAX_AUDIO_BYTES: raise MusicLibraryError('Unsupported audio file or file larger than 256 MB.')
        token = uuid4().hex
        path = self.staging / (token + suffix)
        original = path
        try:
            path.write_bytes(content)
            alac = False
            if suffix == '.m4a':
                try:
                    audio=AudioFile(path)
                    alac=getattr(getattr(audio,'info',None),'codec','')=='alac'
                except Exception:
                    pass
            if suffix not in FORMATS or alac:
                converter=ffmpeg_path()
                if not converter:
                    raise MusicLibraryError('Install the music conversion tools to import this audio format.')
                path=path.with_suffix('.flac')
                MusicSources()._run_process([converter,'-nostdin','-hide_banner','-loglevel','error',
                    '-protocol_whitelist','file','-format_whitelist','mov,aiff,asf,ape,wv',
                    '-i',str(original),'-map','0:a:0','-map_metadata','0','-c:a','flac',str(path)],
                    cancel=None,timeout=180,output_root=self.staging,failure='This audio file could not be converted for the player.')
                original.unlink(missing_ok=True)
                suffix='.flac'
            metadata = self._inspect_audio(path)
            if metadata.title == path.stem: metadata.title = Path(filename.replace('\\','/')).stem[:500] or 'Imported audio'
            with self.db() as db:
                for old in db.execute('SELECT * FROM stages WHERE created<?',(time.time()-3600,)).fetchall():
                    (self.staging / (old['id']+old['suffix'])).unlink(missing_ok=True)
                    db.execute('DELETE FROM stages WHERE id=?',(old['id'],))
                db.execute('INSERT INTO stages VALUES(?,?,?,?)',(token,suffix,metadata.model_dump_json(),time.time()))
            return token
        except Exception:
            path.unlink(missing_ok=True)
            original.unlink(missing_ok=True)
            raise

    def import_file(self, token, entry_id=''):
        with self.db() as db:
            stage = db.execute('SELECT * FROM stages WHERE id=?',(token,)).fetchone()
            if not stage: raise MusicLibraryError('Select this audio file again; its import expired.')
            if entry_id and not db.execute('SELECT id FROM entries WHERE id=?',(entry_id,)).fetchone():
                raise MusicLibraryError('This playlist song no longer exists.')
            file = self.staging / (token + stage['suffix'])
            asset_id = self._commit_asset(db,file,'User-selected audio file')
            if not entry_id:
                existing = db.execute("SELECT id FROM entries WHERE collection_id='imports' AND asset_id=?",(asset_id,)).fetchone()
                entry_id = existing['id'] if existing else uuid4().hex
                db.execute("""INSERT OR IGNORE INTO collections(id,name,source_url,completeness,note)
                           VALUES('imports','Imported files','','complete','Audio imported from your device.')""")
                if not existing:
                    position = db.execute("SELECT count(*) FROM entries WHERE collection_id='imports'").fetchone()[0]
                    db.execute('INSERT INTO entries VALUES(?,?,?,?,?)',(entry_id,'imports',position,stage['metadata'],asset_id))
            db.execute('UPDATE entries SET asset_id=? WHERE id=?',(asset_id,entry_id))
            db.execute('DELETE FROM stages WHERE id=?',(token,))
        file.unlink(missing_ok=True)
        return {'changed':True,'entry_id':entry_id,'_message':'Audio added to your local music library.'}

    def _commit_asset(self, db, file, source):
        self._inspect_audio(file)
        with file.open('rb') as handle:
            digest = hashlib.file_digest(handle,'sha256').hexdigest()
        suffix = file.suffix.lower()
        target = self.assets / (digest+suffix)
        if not target.exists():
            temporary = self.assets / (uuid4().hex + '.part')
            try:
                shutil.copyfile(file,temporary)
                temporary.replace(target)
            finally: temporary.unlink(missing_ok=True)
        db.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?)',(digest,suffix,source))
        return digest

    @staticmethod
    def require_mp3_tools():
        if find_spec('yt_dlp') is None or not ffmpeg_path():
            raise MusicLibraryError('Install the optional music tools to download and convert MP3s.')

    def _queue_mp3(self, db, identity, entry):
        prior = db.execute("SELECT id FROM jobs WHERE entry_id=? AND status IN ('queued','running')", (identity,)).fetchone()
        if prior:
            return prior['id']
        url = ''
        status, error = 'queued', ''
        if entry.provider in {'youtube','jiosaavn','soundcloud','bandcamp'}:
            try:
                url = downloadable_audio_url(entry.source_url)
            except MusicLibraryError:
                status, error = 'failed', 'The playlist did not provide a playable recording link.'
        elif entry.provider not in {'spotify', 'apple_music','amazon_music'}:
            status, error = 'failed', 'This song has no supported download source.'
        identity_job = uuid4().hex
        db.execute('INSERT INTO jobs(id,entry_id,url,status,error,mp3) VALUES(?,?,?,?,?,1)',
                   (identity_job, identity, url, status, error))
        return identity_job

    def enqueue(self, entry_ids, source_url='', *, collection_id=''):
        jobs = []
        if collection_id:
            self.require_mp3_tools()
            with self.db() as db:
                if not db.execute('SELECT 1 FROM collections WHERE id=?', (collection_id,)).fetchone():
                    raise MusicLibraryError('This playlist could not be found.')
                rows = db.execute('SELECT * FROM entries WHERE collection_id=? ORDER BY position', (collection_id,)).fetchall()
                for row in rows:
                    entry = self._entry(db, row)
                    if not entry.available and entry.provider!='local':
                        jobs.append(self._queue_mp3(db, entry.id, entry))
            self._ensure_worker()
            return {'changed': bool(jobs), 'job_ids': jobs,
                    '_message': 'MP3 jobs added to Downloads.' if jobs else 'No songs in this playlist need MP3 downloads.'}
        if source_url:
            if len(entry_ids) != 1: raise MusicLibraryError('Choose one recording for one song at a time.')
            source_url = downloadable_audio_url(source_url)
        with self.db() as db:
            selected = []
            for identity in dict.fromkeys(entry_ids):
                row = db.execute('SELECT * FROM entries WHERE id=?',(identity,)).fetchone()
                if not row: raise MusicLibraryError('A selected song no longer exists.')
                entry = self._entry(db,row)
                if entry.available: continue
                url = source_url or entry.source_url
                # Validate the entire batch before writing any jobs.
                selected.append((identity,downloadable_audio_url(url)))
            for identity,url in selected:
                prior = db.execute("SELECT id FROM jobs WHERE entry_id=? AND status IN ('queued','running')",(identity,)).fetchone()
                if prior: jobs.append(prior['id']); continue
                job_id = uuid4().hex
                db.execute("INSERT INTO jobs(id,entry_id,url,status) VALUES(?,?,?,'queued')",(job_id,identity,url))
                jobs.append(job_id)
        self._ensure_worker()
        return {'changed':bool(jobs),'job_ids':jobs,'_message':'Downloads queued. Each song becomes playable after its audio file has been verified.'}

    def manage_job(self, job_id, operation):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row: raise MusicLibraryError('Download not found.')
            if operation == 'cancel' and row['status'] in {'queued','running'}:
                db.execute("UPDATE jobs SET status='cancelled',stage='',progress=NULL,error='' WHERE id=?",(job_id,))
                if job_id in self._cancels:
                    self._cancels[job_id].set()
            elif operation == 'retry' and row['status'] in {'failed','cancelled'}:
                if job_id in self._cancels:
                    raise MusicLibraryError('This download is still stopping. Retry in a moment.')
                if db.execute("SELECT 1 FROM jobs WHERE entry_id=? AND status IN ('queued','running')",(row['entry_id'],)).fetchone():
                    raise MusicLibraryError('A download for this song is already in progress.')
                db.execute("UPDATE jobs SET status='queued',stage='',progress=NULL,error='' WHERE id=?",(job_id,))
            else: raise MusicLibraryError('This download has already changed. Refresh the library.')
        self._ensure_worker()
        return {'changed':True,'_message':'Download '+ ('cancelled.' if operation=='cancel' else 'queued for retry.')}

    def _work(self):
        while not self._stopped.is_set():
            self._wake.wait(5)
            self._wake.clear()
            while not self._stopped.is_set() and self.process_next(): pass

    def process_next(self):
        if not self._enabled(): return False
        with self.db() as db:
            if self._stopped.is_set(): return False
            row = db.execute("""SELECT jobs.*, entries.metadata FROM jobs JOIN entries ON entries.id=jobs.entry_id
                             WHERE status='queued' ORDER BY jobs.rowid LIMIT 1""").fetchone()
            if not row: return False
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(row['id'],))
            cancel = self._cancels.setdefault(row['id'],DownloadCancellation(self._enabled))
        try:
            with tempfile.TemporaryDirectory(prefix='download-',dir=self.staging) as temporary:
                url = row['url']
                if row['mp3']:
                    entry = MusicSourceEntry.model_validate_json(row['metadata'])
                    last_progress = None

                    def update(stage, progress=None):
                        nonlocal last_progress
                        value = (stage, progress)
                        if value == last_progress:
                            return
                        last_progress = value
                        with self.db() as db:
                            db.execute("UPDATE jobs SET stage=?,progress=? WHERE id=? AND status='running'",
                                       (stage, progress, row['id']))

                    if not url:
                        update('finding')
                        url = self.sources.find_recording(entry)
                    file = self.sources.download_mp3(url, Path(temporary), cancel, entry, update)
                    if file.suffix.lower() != '.mp3':
                        raise MusicLibraryError('The converter did not produce an MP3.')
                else:
                    file = self.sources.download(url, Path(temporary), cancel)
                with self.db() as db:
                    latest = db.execute('SELECT status FROM jobs WHERE id=?',(row['id'],)).fetchone()
                    if latest is None or latest['status'] == 'cancelled': return True
                    if cancel.is_set():
                        db.execute("UPDATE jobs SET status='failed',stage='',progress=NULL,error='The music plugin was disabled during download. Enable it and retry.' WHERE id=?",(row['id'],))
                        return True
                    asset_id = self._commit_asset(db, file, url)
                    if row['mp3']:
                        entry.duration_ms = self._inspect_audio(file).duration_ms
                        db.execute('UPDATE entries SET asset_id=?,metadata=? WHERE id=?',
                                   (asset_id, entry.model_dump_json(), row['entry_id']))
                    else:
                        db.execute('UPDATE entries SET asset_id=? WHERE id=?', (asset_id, row['entry_id']))
                    db.execute("UPDATE jobs SET status='complete',stage='',progress=100,error='' WHERE id=?",(row['id'],))
                    collection=db.execute('SELECT collection_id FROM entries WHERE id=?',(row['entry_id'],)).fetchone()
                    if collection:
                        identity=collection['collection_id']
                        waiting=db.execute("""SELECT 1 FROM entries e LEFT JOIN assets a ON a.id=e.asset_id
                            WHERE e.collection_id=? AND a.id IS NULL LIMIT 1""",(identity,)).fetchone()
                        if not waiting:
                            db.execute('UPDATE collections SET pending_import=0,auto_import=0 WHERE id=? AND auto_import=1',(identity,))
        except Exception as exc:
            message = str(exc)[:300] if isinstance(exc,MusicLibraryError) else 'Download failed. Retry later or import an owned audio file.'
            with self.db() as db:
                db.execute("UPDATE jobs SET status='failed',stage='',progress=NULL,error=? WHERE id=? AND status!='cancelled'",(message,row['id']))
        finally:
            with self._lock: self._cancels.pop(row['id'],None)
        return True

    def remove(self, collection_id='', entry_id=''):
        if bool(collection_id) == bool(entry_id):
            raise MusicLibraryError('Choose one playlist or one song to remove.')
        with self.db() as db:
            if collection_id:
                rows = db.execute('SELECT * FROM entries WHERE collection_id=?',(collection_id,)).fetchall()
                exists = db.execute('SELECT 1 FROM collections WHERE id=?',(collection_id,)).fetchone()
            else:
                rows = db.execute('SELECT * FROM entries WHERE id=?',(entry_id,)).fetchall()
                exists = bool(rows)
            if not exists:
                return {'changed':False,'_message':'This item has already been removed.'}
            identities = {row['id'] for row in rows}
            assets = {row['asset_id'] for row in rows if row['asset_id']}
            for identity in identities:
                for job in db.execute('SELECT id FROM jobs WHERE entry_id=?',(identity,)):
                    cancel = self._cancels.get(job['id'])
                    if cancel:
                        cancel.set()
                db.execute('DELETE FROM jobs WHERE entry_id=?',(identity,))
                db.execute('DELETE FROM entries WHERE id=?',(identity,))
            if collection_id:
                db.execute('DELETE FROM collections WHERE id=?',(collection_id,))
            state = self._player(db)
            queue = [identity for identity in state.queue if identity not in identities]
            if queue != state.queue or state.observed.get('entry_id') in identities:
                current = state.queue[state.index] if state.index < len(state.queue) else ''
                position = sum(identity not in identities for identity in state.queue[:state.index])
                state.queue = queue
                state.index = min(position,max(0,len(queue)-1))
                state.playing = state.playing and bool(queue)
                if current in identities or not queue:
                    state.seconds,state.observed = 0,{}
                state.revision += 1
                db.execute('UPDATE player SET state=? WHERE id=1',(state.model_dump_json(),))
        self._remove_unused_assets(assets)
        return {'changed':True,'_message':'Playlist removed.' if collection_id else 'Song removed from your playlist.'}

    def _remove_unused_assets(self, identities):
        # Shared recordings stay available to other playlists. Only library-owned
        # paths are eligible for cleanup, after the reference deletion commits.
        with self._cover_lock, self.db() as db:
            for identity in identities:
                if db.execute('SELECT 1 FROM entries WHERE asset_id=?',(identity,)).fetchone():
                    continue
                asset = db.execute('SELECT suffix FROM assets WHERE id=?',(identity,)).fetchone()
                if asset is None:
                    continue
                try:
                    (self.assets/(identity+asset['suffix'])).unlink(missing_ok=True)
                    for suffix in ('.png','.jpg','.webp','.none'):
                        (self.covers/(identity+suffix)).unlink(missing_ok=True)
                except OSError:
                    # Windows may still have the currently playing file open.
                    # Retain its asset record so a subsequent cleanup can retry.
                    continue
                self._cover_cache.pop(identity,None)
                db.execute('DELETE FROM assets WHERE id=?',(identity,))

    def asset_path(self, identity):
        with self.db() as db:
            row = db.execute("""SELECT a.* FROM entries e JOIN assets a ON a.id=e.asset_id
                             JOIN collections c ON c.id=e.collection_id WHERE e.id=? AND c.pending_import=0""",
                             (identity,)).fetchone()
        if not row: raise MusicLibraryError('This song has no local audio.')
        return self._asset_file(row['id'], row['suffix'])

    def _asset_file(self, identity, suffix):
        path = self.assets / (identity + suffix)
        if not path.is_file() or not path.resolve().is_relative_to(self.assets.resolve()):
            raise MusicLibraryError('This audio file is missing. Import it again.')
        return path

    def _validate_play_queue(self, db, identities):
        unique = list(dict.fromkeys(identities))
        assets = set()
        for offset in range(0, len(unique), 500):
            batch = unique[offset:offset+500]
            placeholders = ','.join('?' for _ in batch)
            rows = db.execute(f'''SELECT a.id, a.suffix FROM entries e
                JOIN assets a ON a.id=e.asset_id JOIN collections c ON c.id=e.collection_id
                WHERE c.pending_import=0 AND e.id IN ({placeholders})''', batch).fetchall()
            if len(rows) != len(batch):
                raise MusicLibraryError('A selected song has no local audio.')
            assets.update((row['id'], row['suffix']) for row in rows)
        for identity, suffix in assets:
            self._asset_file(identity, suffix)

    @staticmethod
    def _play_query_key(query):
        key = query.strip().casefold()
        if len(key) >= 2 and (key[0], key[-1]) in {('"', '"'), ("'", "'"), ('“', '”'), ('‘', '’')}:
            return key[1:-1].strip()
        return key

    def _matching_playlists(self, db, query):
        key = self._play_query_key(query)
        without_prefix = key.removeprefix('my ').removeprefix('the ')
        rows = db.execute('SELECT id,name FROM collections WHERE pending_import=0').fetchall()
        for candidate in dict.fromkeys((key, without_prefix, key.removesuffix(' playlist'), without_prefix.removesuffix(' playlist'))):
            matches = [row['id'] for row in rows if row['name'].casefold() == candidate]
            if matches:
                return matches
        return []

    def _resolve_play_query(self, db, query):
        groups = self._matching_playlists(db, query)
        if len(groups) == 1:
            return [row['id'] for row in db.execute('''SELECT e.id, a.id AS asset, a.suffix FROM entries e
                JOIN assets a ON a.id=e.asset_id WHERE e.collection_id=? ORDER BY e.position LIMIT 5000''', groups)
                if (self.assets / (row['asset'] + row['suffix'])).is_file()]
        if groups:
            return []
        key = self._play_query_key(query)
        recordings = {}
        for row in db.execute('''SELECT e.id, a.id AS asset, a.suffix, json_extract(e.metadata,'$.title') AS title
                FROM entries e JOIN assets a ON a.id=e.asset_id
                JOIN collections c ON c.id=e.collection_id WHERE c.pending_import=0 ORDER BY e.rowid'''):
            if (row['title'] or '').casefold() == key and (self.assets / (row['asset'] + row['suffix'])).is_file():
                recordings.setdefault(row['asset'], row['id'])
        return list(recordings.values()) if len(recordings) == 1 else []

    def has_playlist(self, name):
        with self.db() as db:
            return bool(self._matching_playlists(db, name))

    def list_playlists(self):
        with self.db() as db:
            total = db.execute('SELECT count(*) FROM collections WHERE pending_import=0').fetchone()[0]
            rows = db.execute('''SELECT c.name, count(e.id) AS song_count FROM collections c
                LEFT JOIN entries e ON e.collection_id=c.id WHERE c.pending_import=0
                GROUP BY c.id ORDER BY c.name COLLATE NOCASE, c.id LIMIT 50''').fetchall()
        items = [dict(row) for row in rows]
        if not items:
            message = 'Your Local Music library has no saved playlists yet.'
        else:
            visible = [f"{row['name']} ({row['song_count']} songs)" for row in items[:20]]
            message = 'Your Local Music playlists are ' + ', '.join(visible) + '.'
            if total > len(visible):
                message += f' Open Local Music to see all {total} playlists.'
        return {'changed': False, 'playlists': items, 'total': total, '_message': message}

    def _pick_playable_song(self, db):
        rows = db.execute('''SELECT e.id, a.id AS asset, a.suffix, json_extract(e.metadata,'$.title') AS title
            FROM entries e JOIN assets a ON a.id=e.asset_id
            JOIN collections c ON c.id=e.collection_id WHERE c.pending_import=0 ORDER BY random()''')
        for row in rows:
            try:
                self._asset_file(row['asset'], row['suffix'])
            except MusicLibraryError:
                continue
            return row['id'], row['title']
        raise MusicLibraryError('Local Music has no playable songs yet. Import audio or finish downloading a playlist first.')

    def _player(self, db):
        row = db.execute('SELECT * FROM player WHERE id=1').fetchone()
        return LocalPlayerState(**{**json.loads(row['state']),'owner_available':bool(row['owner'] and row['expires']>time.time())})

    def player_state(self):
        with self.db() as db: return self._player(db)

    def playback(self, request: LocalPlaybackRequest):
        message = 'Local playback command queued; the player reports whether it was applied.'
        with self.db() as db:
            state = self._player(db)
            if request.expected_revision is not None and (request.expected_revision != state.revision or not state.playing):
                return {'changed':False,'revision':state.revision,'_message':'The local queue has already moved on or paused.'}
            current = state.queue[state.index] if state.queue and state.index<len(state.queue) else ''
            if state.observed.get('entry_id') == current:
                state.seconds = state.observed.get('seconds',state.seconds)
            if request.action == 'play':
                if request.pick_any:
                    identity, title = self._pick_playable_song(db)
                    request = request.model_copy(update={'entry_ids':[identity]})
                    message = f'Queued “{title}” from Local Music.'
                elif request.query:
                    choices = self._resolve_play_query(db, request.query)
                    if not choices: raise MusicLibraryError('No unique, playable local song or playlist matches that name. Select the recording in Music → Local library.')
                    request = request.model_copy(update={'entry_ids':choices,'position':0})
                    message = f'Queued {request.query} from Local Music.'
                if not request.entry_ids or request.position >= len(request.entry_ids): raise MusicLibraryError('Choose a local song to play.')
                self._validate_play_queue(db, request.entry_ids)
                state.queue,state.index,state.seconds,state.playing = request.entry_ids,request.position,0,True
            elif request.action == 'pause': state.playing = False
            elif request.action == 'resume':
                if not state.queue: raise MusicLibraryError('Choose a local song first.')
                self.asset_path(state.queue[state.index]); state.playing = True
                if state.observed.get('duration',0) and state.seconds >= state.observed['duration']-0.2: state.seconds = 0
            elif request.action in {'next','previous'}:
                if not state.queue: raise MusicLibraryError('The local queue is empty.')
                state.index = (random.SystemRandom().randrange(len(state.queue)) if state.shuffle else (state.index+(1 if request.action=='next' else -1))%len(state.queue))
                state.seconds = 0
            elif request.action == 'seek': state.seconds = request.seconds
            elif request.action == 'volume': state.volume = request.volume
            elif request.action == 'shuffle': state.shuffle = request.enabled
            elif request.action == 'repeat': state.repeat = request.repeat
            state.revision += 1
            db.execute('UPDATE player SET state=? WHERE id=1',(state.model_dump_json(),))
        return {'changed':True,'revision':state.revision,'_message':message}

    def report(self, report):
        with self.db() as db:
            row = db.execute('SELECT * FROM player WHERE id=1').fetchone()
            if row['owner'] and row['owner'] != report.owner_id and row['expires']>time.time():
                return {'accepted':False,'player':self._player(db).model_dump()}
            state = self._player(db)
            if report.revision == state.revision:
                state.observed = {'entry_id':report.entry_id,'playing':report.playing,'seconds':report.seconds,
                    'duration':report.duration,'error':report.error,'at':time.time()}
            db.execute('UPDATE player SET state=?,owner=?,expires=? WHERE id=1',(state.model_dump_json(),report.owner_id,time.time()+8))
            return {'accepted':True,'player':state.model_dump()}

    def export(self, collection_id):
        group = next((row for row in self.snapshot().collections if row.id == collection_id),None)
        if group is None: raise MusicLibraryError('Playlist not found.')
        return {'version':1,'name':group.name,'source_url':group.source_url,'completeness':group.completeness,
            'entries':[MusicSourceEntry(**{key:value for key,value in row.model_dump().items() if key in MusicSourceEntry.model_fields}).model_dump() for row in group.entries]}


@lru_cache(maxsize=1)
def get_music_library():
    from agent.config import REPO_ROOT
    from agent.plugins.registry import get_plugin_registry
    return MusicLibrary(REPO_ROOT / 'data' / 'music',enabled=lambda:get_plugin_registry().is_enabled('local_music'))
