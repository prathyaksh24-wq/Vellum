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
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
from mutagen import File as AudioFile

from agent.contracts.local_music import (LocalMusicCollection, LocalMusicEntry, LocalMusicJob,
    LocalMusicLibrary, LocalPlayerState, MusicSourceEntry, MusicImportRequest, LocalPlaybackRequest)

MAX_AUDIO_BYTES = 256 * 1024 * 1024
FORMATS = {'.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wav', '.webm'}
YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}


class MusicLibraryError(ValueError):
    pass


class _ApplePageData(HTMLParser):
    """Read one data script as HTML; this extracts JSON, never sanitizes markup."""
    def __init__(self):
        super().__init__()
        self.capture = False
        self.found = False
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
    except (ValueError, IndexError):
        pass
    raise MusicLibraryError('Use a full HTTPS YouTube, Spotify, or Apple Music song, album, or playlist link.')


def youtube_audio_url(value: str) -> str:
    provider, kind, url = source_link(value)
    if provider != 'youtube' or kind != 'track':
        raise MusicLibraryError('Choose an exact YouTube recording. Spotify and Apple links import track information, not subscription audio.')
    return url


class MusicSources:
    """External discovery boundary, replaceable without changing the library."""
    def run_tool(self, args: list[str], *, cancel: Event | None = None, timeout=120, output_root=None):
        if find_spec('yt_dlp') is None:
            raise MusicLibraryError('The optional music downloader is not installed. Import audio files or install scripts/music-requirements.txt.')
        command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-cache-dir',
            '--no-plugin-dirs', '--no-exec', '--js-runtimes', 'node', '--no-progress', '--socket-timeout', '20', '--retries', '2',
            '--extractor-retries', '2', *args]
        # Ignore inherited proxies/config/plugins. Never read browser cookies or
        # accept user-supplied flags, executables, templates or output paths.
        import os
        environment = {key:value for key,value in os.environ.items()
            if key.upper() not in {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','PYTHONPATH','PYTHONSTARTUP'}}
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, env=environment, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if cancel and cancel.wait(0.2):
                        raise MusicLibraryError('Download cancelled.')
                    if not cancel: time.sleep(0.2)
                    if time.monotonic() - started > timeout or output.tell() > 12 * 1024 * 1024:
                        raise MusicLibraryError('The source did not finish within the download limits. You can retry later.')
                    if output_root and any(file.is_file() and file.stat().st_size > MAX_AUDIO_BYTES for file in output_root.iterdir()):
                        raise MusicLibraryError('This recording exceeds the 256 MB file limit.')
                if process.returncode:
                    raise MusicLibraryError('The source could not be read. It may require sign-in, reject automated access, or be unavailable. No account cookies were used.')
                output.seek(0)
                return output.read(12 * 1024 * 1024 + 1).decode('utf-8')
            finally:
                if process.poll() is None: process.kill()
                process.wait(timeout=10)

    def resolve(self, value: str):
        provider, kind, url = source_link(value)
        if provider == 'spotify': return self.spotify(kind, url)
        if provider == 'apple_music': return self.apple(url)
        if kind == 'playlist':
            official = self.youtube_playlist(url)
            if official is not None: return official
        data = json.loads(self.run_tool(['--flat-playlist', '--skip-download', '--dump-single-json',
            '--playlist-end', '5000', '--', url]))
        raw = data.get('entries') if data.get('_type') == 'playlist' else [data]
        entries = []
        for row in raw or []:
            video = str(row.get('id') or '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video): continue
            entries.append(MusicSourceEntry(title=str(row.get('title') or 'Unavailable song')[:500],
                artist=str(row.get('artist') or row.get('uploader') or row.get('channel') or '')[:500],
                duration_ms=min(86400000, int((row.get('duration') or 0) * 1000)), provider='youtube',
                source_id=video, source_url='https://www.youtube.com/watch?v=' + video))
        total = data.get('playlist_count')
        complete = kind == 'track' or isinstance(total, int) and total == len(entries)
        return str(data.get('title') or 'YouTube playlist')[:200], entries, 'complete' if complete else 'unknown', 'Public playlist snapshot. Private, removed, or unlisted entries may be missing.'

    def youtube_playlist(self, url):
        """Read private playlist metadata only through the existing OAuth owner."""
        from agent.plugins.registry import get_plugin_registry
        from agent.plugins.youtube_runtime import youtube_client, youtube_status
        if not get_plugin_registry().is_enabled('youtube') or not youtube_status().get('connected'): return None
        identity = parse_qs(urlsplit(url).query)['list'][0]
        client = youtube_client()
        try:
            header = client._api_get('/playlists',params={'part':'snippet','id':identity})
            if not header.get('items'): return None
            title = str(header['items'][0].get('snippet',{}).get('title') or 'YouTube playlist')[:200]
            token,entries,total = '',[],None
            for _ in range(100):
                page = client._api_get('/playlistItems',params={'part':'snippet,contentDetails','playlistId':identity,'maxResults':50,**({'pageToken':token} if token else {})})
                for row in page.get('items',[]):
                    snippet,details = row.get('snippet') or {},row.get('contentDetails') or {}
                    video = str(details.get('videoId') or snippet.get('resourceId',{}).get('videoId') or '')
                    entries.append(MusicSourceEntry(title=str(snippet.get('title') or 'Unavailable song')[:500],
                        artist=str(snippet.get('videoOwnerChannelTitle') or '')[:500],provider='youtube',source_id=video,
                        source_url='https://www.youtube.com/watch?v='+video if re.fullmatch(r'[A-Za-z0-9_-]{11}',video) else ''))
                total = (page.get('pageInfo') or {}).get('totalResults')
                token = page.get('nextPageToken') or ''
                if not token: break
            return title,entries,'complete' if not token and total==len(entries) else 'partial','Playlist information imported through your connected YouTube account. Audio downloads use public access separately.'
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
            title=str(root.get('name') or 'Spotify playlist')[:200]
            return title,entries,'unknown','Public Spotify song-list snapshot. Supply owned audio files to play these songs locally.'
        return str(root.get('name') or 'Spotify playlist')[:200], entries, 'complete' if total == len(entries) else 'partial', 'Track information imported from Spotify. Supply owned audio files or choose a permitted recording for each song.'

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
        if not parser.found: raise MusicLibraryError('Apple Music did not expose this public playlist. Import a playlist manifest instead.')
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
        return title, songs[:5000], 'complete' if selected and len(songs)==1 else 'unknown', 'Apple public-page snapshot; playlist completeness could not be verified. This imports track information only.'

    def discover(self, query):
        if find_spec('ytmusicapi') is None:
            raise MusicLibraryError('Music search is optional. Paste an exact YouTube song link, or install scripts/music-requirements.txt.')
        from ytmusicapi import YTMusic
        # Public discovery only; no headers, credentials, cookies or OAuth reuse.
        client = YTMusic()
        rows = client.search(query, filter='songs', limit=8)
        return [MusicSourceEntry(title=str(row.get('title') or 'Untitled')[:500],
            artist=', '.join(a.get('name','') for a in row.get('artists') or [])[:500],
            provider='youtube', source_id=row['videoId'], source_url='https://www.youtube.com/watch?v='+row['videoId'])
            for row in rows[:8] if re.fullmatch(r'[A-Za-z0-9_-]{11}',str(row.get('videoId') or ''))]

    def download(self, url, directory, cancel):
        url = youtube_audio_url(url)
        self.run_tool(['--no-playlist', '--max-filesize', str(MAX_AUDIO_BYTES), '--max-downloads', '1',
            '-f', 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
            '--paths', str(directory), '-o', 'audio.%(ext)s', '--', url], cancel=cancel, timeout=600,output_root=directory)
        files = [file for file in directory.iterdir() if file.suffix.lower() in FORMATS and file.is_file()]
        if len(files) != 1: raise MusicLibraryError('The source did not return one supported audio file.')
        return files[0]


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
        self._start_worker, self._thread = start_worker, None
        self._enabled = enabled
        self._cover_cache = OrderedDict()
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
            row = db.execute('SELECT state FROM player WHERE id=1').fetchone()
            state = json.loads(row['state']) if row else LocalPlayerState().model_dump()
            state['playing'], state['observed'] = False, {}
            db.execute('INSERT OR REPLACE INTO player(id,state,owner,expires) VALUES(1,?,\'\',0)',(json.dumps(state),))
            db.execute("UPDATE jobs SET status='failed',error='Vellum stopped during this download. Retry to continue.' WHERE status='running'")

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
            if self._start_worker and (self._thread is None or not self._thread.is_alive()):
                self._thread = Thread(target=self._work, name='vellum-music-downloads', daemon=True)
                self._thread.start()
        self._wake.set()

    def snapshot(self):
        self._ensure_worker()
        with self.db() as db:
            collections = []
            for group in db.execute('SELECT * FROM collections ORDER BY rowid DESC').fetchall():
                entries = [self._entry(db,row) for row in db.execute('SELECT * FROM entries WHERE collection_id=? ORDER BY position',(group['id'],))]
                collections.append(LocalMusicCollection(**dict(group),entries=entries))
            jobs = [LocalMusicJob(**dict(row)) for row in db.execute('SELECT j.id,j.entry_id,j.status,j.error,json_extract(e.metadata,\'$.title\') title FROM jobs j JOIN entries e ON e.id=j.entry_id ORDER BY j.rowid DESC LIMIT 100')]
            return LocalMusicLibrary(collections=collections,jobs=jobs,player=self._player(db),
                downloader_available=find_spec('yt_dlp') is not None, discovery_available=find_spec('ytmusicapi') is not None)

    def _entry(self, db, row):
        asset = db.execute('SELECT * FROM assets WHERE id=?',(row['asset_id'],)).fetchone()
        available = bool(asset and (self.assets / (asset['id']+asset['suffix'])).is_file())
        return LocalMusicEntry(**json.loads(row['metadata']),id=row['id'],available=available,audio_source=asset['audio_source'] if asset else '',
            artwork_url='/api/music/local/artwork/'+row['id'] if available and self._embedded_cover(asset) else '')

    def _embedded_cover(self, asset):
        """Derived local artwork only; audio and playlist metadata stay unchanged."""
        identity=asset['id']
        with self._lock:
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
        self.asset_path(entry_id)
        with self.db() as db:
            asset=db.execute('SELECT a.* FROM entries e JOIN assets a ON a.id=e.asset_id WHERE e.id=?',(entry_id,)).fetchone()
            path=self._embedded_cover(asset)
        if not path:raise MusicLibraryError('This file has no supported embedded cover.')
        return path

    def import_playlist(self, request: MusicImportRequest):
        if request.url:
            title, entries, completeness, note = self.sources.resolve(request.url)
            url = source_link(request.url)[2]
        else:
            title, entries, completeness, note, url = request.name, request.entries, request.completeness, 'Imported track information. Missing audio can be supplied separately.', request.source_origin
        if not entries: raise MusicLibraryError('No readable songs were found. Nothing was added.')
        identity = uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO collections VALUES(?,?,?,?,?)',(identity,title,url,completeness,note))
            for position, entry in enumerate(entries[:5000]):
                db.execute('INSERT INTO entries VALUES(?,?,?,?,NULL)',(uuid4().hex,identity,position,entry.model_dump_json()))
        return {'changed':True,'collection_id':identity,'count':len(entries[:5000]),'completeness':completeness,
            '_message':f'Imported {len(entries[:5000])} track references. Audio availability is shown separately.'}

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
        if suffix not in FORMATS or len(content) > MAX_AUDIO_BYTES: raise MusicLibraryError('Unsupported audio file or file larger than 256 MB.')
        token = uuid4().hex
        path = self.staging / (token + suffix)
        try:
            path.write_bytes(content)
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
                db.execute("INSERT OR IGNORE INTO collections VALUES('imports','Imported files','','complete','Owned audio copied into your local music library.')")
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

    def enqueue(self, entry_ids, source_url=''):
        jobs = []
        if source_url:
            if len(entry_ids) != 1: raise MusicLibraryError('Choose one recording for one song at a time.')
            source_url = youtube_audio_url(source_url)
        with self.db() as db:
            selected = []
            for identity in dict.fromkeys(entry_ids):
                row = db.execute('SELECT * FROM entries WHERE id=?',(identity,)).fetchone()
                if not row: raise MusicLibraryError('A selected song no longer exists.')
                entry = self._entry(db,row)
                if entry.available: continue
                url = source_url or entry.source_url
                # Validate the entire batch before writing any jobs.
                selected.append((identity,youtube_audio_url(url)))
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
                db.execute("UPDATE jobs SET status='cancelled',error='' WHERE id=?",(job_id,))
                self._cancels.setdefault(job_id,Event()).set()
            elif operation == 'retry' and row['status'] in {'failed','cancelled'}:
                if db.execute("SELECT 1 FROM jobs WHERE entry_id=? AND status IN ('queued','running')",(row['entry_id'],)).fetchone():
                    raise MusicLibraryError('A download for this song is already in progress.')
                db.execute("UPDATE jobs SET status='queued',error='' WHERE id=?",(job_id,))
                self._cancels.pop(job_id,None)
            else: raise MusicLibraryError('This download has already changed. Refresh the library.')
        self._ensure_worker()
        return {'changed':True,'_message':'Download '+ ('cancelled.' if operation=='cancel' else 'queued for retry.')}

    def _work(self):
        while True:
            self._wake.wait(5)
            self._wake.clear()
            while self.process_next(): pass

    def process_next(self):
        if not self._enabled(): return False
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row: return False
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(row['id'],))
            cancel = self._cancels.setdefault(row['id'],DownloadCancellation(self._enabled))
        try:
            with tempfile.TemporaryDirectory(prefix='download-',dir=self.staging) as temporary:
                file = self.sources.download(row['url'],Path(temporary),cancel)
                with self.db() as db:
                    status = db.execute('SELECT status FROM jobs WHERE id=?',(row['id'],)).fetchone()[0]
                    if status == 'cancelled': return True
                    if cancel.is_set():
                        db.execute("UPDATE jobs SET status='failed',error='The music plugin was disabled during download. Enable it and retry.' WHERE id=?",(row['id'],))
                        return True
                    asset_id = self._commit_asset(db,file,row['url'])
                    db.execute('UPDATE entries SET asset_id=? WHERE id=?',(asset_id,row['entry_id']))
                    db.execute("UPDATE jobs SET status='complete',error='' WHERE id=?",(row['id'],))
        except Exception as exc:
            message = str(exc)[:300] if isinstance(exc,MusicLibraryError) else 'Download failed. Retry later or import an owned audio file.'
            with self.db() as db:
                db.execute("UPDATE jobs SET status='failed',error=? WHERE id=? AND status!='cancelled'",(message,row['id']))
        finally:
            with self._lock: self._cancels.pop(row['id'],None)
        return True

    def asset_path(self, identity):
        with self.db() as db:
            row = db.execute('SELECT a.* FROM entries e JOIN assets a ON a.id=e.asset_id WHERE e.id=?',(identity,)).fetchone()
            if not row: raise MusicLibraryError('This song has no local audio.')
            path = self.assets / (row['id'] + row['suffix'])
            if not path.is_file() or not path.resolve().is_relative_to(self.assets.resolve()):
                raise MusicLibraryError('This audio file is missing. Import it again.')
            return path

    def _player(self, db):
        row = db.execute('SELECT * FROM player WHERE id=1').fetchone()
        return LocalPlayerState(**{**json.loads(row['state']),'owner_available':bool(row['owner'] and row['expires']>time.time())})

    def player_state(self):
        with self.db() as db: return self._player(db)

    def playback(self, request: LocalPlaybackRequest):
        with self.db() as db:
            state = self._player(db)
            current = state.queue[state.index] if state.queue and state.index<len(state.queue) else ''
            if state.observed.get('entry_id') == current:
                state.seconds = state.observed.get('seconds',state.seconds)
            if request.action == 'play':
                if request.query:
                    key = request.query.strip().casefold()
                    groups = [row for row in self.snapshot().collections if row.name.casefold()==key]
                    songs = [entry for group in self.snapshot().collections for entry in group.entries
                        if entry.title.casefold()==key and entry.available]
                    choices = ([entry.id for entry in groups[0].entries if entry.available] if len(groups)==1 else
                        [songs[0].id] if not groups and len(songs)==1 else [])
                    if not choices: raise MusicLibraryError('No unique, playable local song or playlist matches that name. Select the recording in Music → Local library.')
                    request = request.model_copy(update={'entry_ids':choices,'position':0})
                if not request.entry_ids or request.position >= len(request.entry_ids): raise MusicLibraryError('Choose a local song to play.')
                for identity in request.entry_ids: self.asset_path(identity)
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
        return {'changed':True,'revision':state.revision,'_message':'Local playback command queued; the player reports whether it was applied.'}

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
