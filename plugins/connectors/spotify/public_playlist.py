"""Read the exact public Spotify embed when its API withholds a song list.

No OAuth headers, cookies, preview URLs or audio cross this boundary. The
public view may be partial; never turn its visible row count into a verified
full playlist count. Original occurrences and playback positions are retained.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from html.parser import HTMLParser
import json
import re
from threading import RLock
import time
from urllib.parse import urlsplit

import httpx


class PublicPlaylistUnavailable(ValueError):
    pass


class _PageData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture=False
        self.parts=[]

    def handle_starttag(self, tag, attrs):
        attributes=dict(attrs)
        if tag=='script' and attributes.get('id')=='__NEXT_DATA__' and attributes.get('type')=='application/json':
            self.capture=True

    def handle_endtag(self, tag):
        if tag=='script':self.capture=False

    def handle_data(self, data):
        if self.capture:self.parts.append(data)


def parse_public_playlist(html, identity):
    if not re.fullmatch(r'[A-Za-z0-9]{22}',identity):raise PublicPlaylistUnavailable('Invalid playlist ID')
    parser=_PageData();parser.feed(html)
    try:
        data=json.loads(''.join(parser.parts))
        entity=data['props']['pageProps']['state']['data']['entity']
    except (ValueError,KeyError,TypeError) as exc:
        raise PublicPlaylistUnavailable('Spotify did not expose public playlist data') from exc
    if entity.get('type')!='playlist' or entity.get('uri')!='spotify:playlist:'+identity or str(entity.get('id') or identity)!=identity:
        raise PublicPlaylistUnavailable('Spotify returned a different collection')
    rows=entity.get('trackList')
    if not isinstance(rows,list) or not rows:raise PublicPlaylistUnavailable('No public song list')
    items=[]
    for position,row in enumerate(rows[:5000]):
        if not isinstance(row,dict):raise PublicPlaylistUnavailable('Unsupported public playlist entry')
        uri=str(row.get('uri') or '')
        valid=bool(re.fullmatch(r'spotify:track:[A-Za-z0-9]{22}',uri))
        name=str(row.get('title') or 'Unavailable track')[:500]
        subtitle=str(row.get('subtitle') or '').replace('\ufffd',' ').replace('\xa0',' ')
        duration=row.get('duration')
        items.append({'id':uri.rsplit(':',1)[-1] if valid else '', 'uri':uri if valid else '',
            'kind':'track','name':name,'artists':[name.strip() for name in subtitle.split(',') if name.strip()],
            'album':'','duration_ms':max(0,min(int(duration),86400000)) if isinstance(duration,(int,float)) else 0,
            'playable':valid,'position':position,
            'external_url':'https://open.spotify.com/track/'+uri.rsplit(':',1)[-1] if valid else ''})
    return items


_cache=OrderedDict()
_lock=RLock()


def cached_public_playlist(identity):
    with _lock:
        cached=_cache.get(identity)
        if not cached or cached[0]<=time.monotonic():
            _cache.pop(identity,None)
            return None
        _cache.move_to_end(identity)
        return [dict(row) for row in cached[1]]


def read_public_playlist(identity, *, transport=None):
    cached=cached_public_playlist(identity)
    if cached is not None:return cached
    if not re.fullmatch(r'[A-Za-z0-9]{22}',identity):raise PublicPlaylistUnavailable('Invalid playlist ID')
    try:
        # The URL is constructed from a verified ID and never follows redirects.
        # This client is deliberately independent of the authenticated API client.
        with httpx.Client(timeout=10,follow_redirects=False,trust_env=False,transport=transport) as client:
            with client.stream('GET','https://open.spotify.com/embed/playlist/'+identity,headers={'User-Agent':'Mozilla/5.0'}) as response:
                response.raise_for_status()
                content=bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content)>8*1024*1024:raise PublicPlaylistUnavailable('Public playlist is too large')
        rows=parse_public_playlist(bytes(content).decode('utf-8'),identity)
    except (httpx.HTTPError,UnicodeError,ValueError) as exc:
        raise PublicPlaylistUnavailable('The public song list is unavailable') from exc
    with _lock:
        _cache[identity]=(time.monotonic()+600,rows)
        _cache.move_to_end(identity)
        while len(_cache)>32:_cache.popitem(last=False)
    return [dict(row) for row in rows]


_artwork_cache=OrderedDict()
_artwork_inflight={}
_artwork_pool=None


def _read_track_artwork(identity, transport=None):
    """Read public image metadata only; never fetch previews or image bytes."""
    artwork=''
    try:
        with httpx.Client(timeout=6,follow_redirects=False,trust_env=False,transport=transport) as client:
            with client.stream('GET','https://open.spotify.com/oembed',
                    params={'url':'https://open.spotify.com/track/'+identity}) as response:
                response.raise_for_status()
                content=bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content)>64*1024:raise ValueError('Metadata response exceeds limit')
        data=json.loads(content)
        if not isinstance(data,dict):raise ValueError('Unsupported metadata response')
        candidate=str(data.get('thumbnail_url') or '')
        if len(candidate)>2048:raise ValueError('Unsupported image URL')
        url=urlsplit(candidate)
        if (url.scheme=='https' and url.hostname in {'i.scdn.co','image-cdn-ak.spotifycdn.com','image-cdn-fa.spotifycdn.com'}
                and not url.username and not url.password and url.port in {None,443}):
            artwork=candidate
    except (httpx.HTTPError,UnicodeError,ValueError,TypeError):
        pass
    result={'id':identity,'artwork_url':artwork}
    with _lock:
        _artwork_cache[identity]=(time.monotonic()+(3600 if artwork else 30),result)
        _artwork_cache.move_to_end(identity)
        while len(_artwork_cache)>2048:_artwork_cache.popitem(last=False)
    return result


def read_track_artworks(identities, *, transport=None, wait_seconds=None):
    """Viewport-requested, deduplicated metadata with at most four remote reads."""
    global _artwork_pool
    if not 1<=len(identities)<=20 or any(not re.fullmatch(r'[A-Za-z0-9]{22}',value) for value in identities):
        raise ValueError('Choose one to twenty exact Spotify track IDs')
    identities=list(dict.fromkeys(identities))
    pending,results={},{}
    with _lock:
        for identity,future in list(_artwork_inflight.items()):
            if future.done():_artwork_inflight.pop(identity,None)
        for identity in identities:
            cached=_artwork_cache.get(identity)
            if cached and cached[0]>time.monotonic():
                _artwork_cache.move_to_end(identity);results[identity]=dict(cached[1]);continue
            if identity not in _artwork_inflight:
                if _artwork_pool is None:_artwork_pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='spotify-image-metadata')
                _artwork_inflight[identity]=_artwork_pool.submit(_read_track_artwork,identity,transport)
            pending[identity]=_artwork_inflight[identity]
    try:
        if pending and wait_seconds is not None:wait(set(pending.values()),timeout=max(0,min(wait_seconds,.5)))
        for identity,future in pending.items():
            results[identity]=dict(future.result()) if wait_seconds is None or future.done() else {'id':identity,'artwork_url':'','pending':True}
    finally:
        with _lock:
            for identity,future in pending.items():
                if future.done() and _artwork_inflight.get(identity) is future:_artwork_inflight.pop(identity,None)
    return [results[identity] for identity in identities]
