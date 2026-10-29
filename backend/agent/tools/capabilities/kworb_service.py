"""Read-only public music statistics through the canonical capability registry."""

from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
import re
from threading import RLock
import time
import unicodedata
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


class KworbRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['artist', 'artists', 'songs', 'albums', 'chart']
    artist: str = Field(default='', max_length=200)
    artist_id: str = Field(default='', pattern=r'^[A-Za-z0-9]*$', max_length=80)
    country: str = Field(default='global', max_length=80)
    period: Literal['daily', 'weekly'] = 'daily'
    limit: int = Field(default=10, ge=1, le=50)


def key(text):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                            if not unicodedata.combining(c)).split())


class _Document(HTMLParser):
    """Parse real table cells and links; never scrape HTML with regular expressions."""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.rows, self.links, self.text = [], [], []
        self.row = None
        self.cell = None
        self.anchor = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in {'td', 'th'} and self.row is not None:
            self.cell = {'text': [], 'links': []}
        elif tag == 'a':
            self.anchor = {'href': dict(attrs).get('href', ''), 'text': []}

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell['text'].append(data)
        if self.anchor is not None:
            self.anchor['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor is not None:
            link = {**self.anchor, 'text': ' '.join(''.join(self.anchor['text']).split())}
            self.links.append(link)
            if self.cell is not None:
                self.cell['links'].append(link)
            self.anchor = None
        elif tag in {'td', 'th'} and self.cell is not None:
            self.cell['text'] = ' '.join(''.join(self.cell['text']).split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


class KworbCapabilityService:
    BASE = 'https://kworb.net/spotify/'

    def __init__(self, *, fetch=None, clock=time.monotonic, ttl=21600):
        self.fetch = fetch or self._fetch
        self.clock, self.ttl = clock, ttl
        self._cache = OrderedDict()
        self._lock = RLock()

    @staticmethod
    def _fetch(url):
        # URLs are constructed from fixed paths or links on the known index.
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            with client.stream('GET', url, headers={'User-Agent': 'Vellum/1.0 (public music statistics)'}) as reply:
                reply.raise_for_status()
                data = bytearray()
                deadline = time.monotonic()+10
                for chunk in reply.iter_bytes():
                    if time.monotonic() > deadline:
                        raise ValueError('Kworb page reached its download time limit.')
                    data.extend(chunk)
                    if len(data) > 3_000_000:
                        raise ValueError('Kworb page exceeded the bounded download size.')
        return data.decode('utf-8', errors='replace')

    def _document(self, path):
        url = urljoin(self.BASE, path)
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'kworb.net' or not parsed.path.startswith('/spotify/'):
            raise ValueError('Unsupported statistics source.')
        with self._lock:
            cached = self._cache.get(url)
            if cached and self.clock()-cached[0] < self.ttl:
                self._cache.move_to_end(url)
                return cached[1], cached[2], url
            doc = _Document(self.fetch(url))
            captured = datetime.now(UTC).isoformat(timespec='seconds')
            self._cache[url] = (self.clock(), doc, captured)
            self._cache.move_to_end(url)
            while len(self._cache) > 16:
                self._cache.popitem(last=False)
            return doc, captured, url

    def build_registry(self):
        registry = ToolRegistry()
        registry.register(CapabilityRecord(name='music_kworb', namespace='music', access=CapabilityAccess.READ,
            allowed_agents=frozenset({'MusicAgent', 'VellumAgent'}), stream_label='Read Kworb music statistics',
            adapter=self.invoke, input_schema=KworbRequest.model_json_schema()))
        return registry

    def invoke(self, payload):
        request = KworbRequest.model_validate(payload)
        try:
            return {'ok': True, 'data': self.read(request)}
        except (ValueError, httpx.HTTPError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else 'Kworb is unavailable. No chart or count was guessed.'
            return {'ok': False, 'error': {'message': message}}

    @staticmethod
    def _id(href, kind):
        match = re.search(r'/'+kind+r'/([A-Za-z0-9]+)(?:[/?#]|$)', href)
        if match and urlparse(href).hostname == 'open.spotify.com':
            return match[1]
        mirror = re.fullmatch(r'(?:\.\./)?'+kind+r'/([A-Za-z0-9]+)\.html', href)
        return mirror[1] if mirror else ''

    @staticmethod
    def _date(doc):
        match = re.search(r'\b(20\d{2})/(\d{2})/(\d{2})\b', ' '.join(doc.text))
        return '-'.join(match.groups()) if match else ''

    def artists(self):
        doc, captured, url = self._document('listeners.html')
        rows = []
        for cells in doc.rows:
            if len(cells) < 6 or not cells[0]['text'].isdigit():
                continue
            link = next((a for a in cells[1]['links'] if re.fullmatch(r'(?:/spotify/)?artist/[A-Za-z0-9]+_songs\.html', a['href'])), None)
            if not link:
                continue
            artist_id = re.search(r'artist/([A-Za-z0-9]+)_songs', link['href'])[1]
            try:
                rows.append({'rank': int(cells[0]['text']), 'name': link['text'], 'artist_id': artist_id,
                    'listeners': int(cells[2]['text'].replace(',', '')), 'daily_change': cells[3]['text'],
                    'peak_rank': cells[4]['text'], 'peak_listeners': cells[5]['text']})
            except ValueError:
                continue
        if not rows:
            raise ValueError('Kworb did not expose a recognizable listener table.')
        return rows, captured, url

    def _artist(self, request):
        artists, captured, url = self.artists()
        exact = [a for a in artists if a['artist_id'] == request.artist_id] if request.artist_id else [a for a in artists if key(a['name']) == key(request.artist)]
        if len(exact) == 1:
            return exact[0], captured, url
        if request.artist and not request.artist_id:
            scored = sorted(((SequenceMatcher(None, key(request.artist), key(a['name'])).ratio(), a) for a in artists), key=lambda pair: pair[0], reverse=True)
            if scored[0][0] >= .82 and (len(scored) == 1 or scored[0][0]-scored[1][0] >= .12):
                return scored[0][1], captured, url
        raise ValueError('Kworb did not identify one artist. Give the exact artist name; its ranked list is not a complete Spotify catalog.')

    def read(self, request):
        if request.action == 'artists':
            rows, captured, url = self.artists()
            return {'items': deepcopy(rows[:request.limit]), 'source_url': url, 'fetched_at': captured, 'data_date': ''}
        if request.action == 'chart':
            index, _, _ = self._document('')
            countries = {'global': 'global'}
            for row in index.rows:
                for cell in row[1:]:
                    for link in cell['links']:
                        match = re.fullmatch(r'country/([a-z]{2}|global)_daily\.html', link['href'])
                        if match:
                            countries[key(row[0]['text'])] = match[1]
                            countries[match[1]] = match[1]
            aliases = {'worldwide': 'global', 'world': 'global', 'usa': 'us', 'uk': 'gb', 'united states of america': 'us'}
            wanted = aliases.get(key(request.country), key(request.country))
            country = countries.get(wanted)
            if not country:
                raise ValueError('Choose a country available in Kworb’s Spotify charts, or global.')
            doc, captured, url = self._document(f'country/{country}_{request.period}.html')
            rows = []
            for cells in doc.rows:
                if len(cells) < 3 or not cells[0]['text'].isdigit():
                    continue
                track = next((a for a in cells[2]['links'] if self._id(a['href'], 'track')), None)
                if track:
                    rows.append({'rank': int(cells[0]['text']), 'name': track['text'],
                        'uri': 'spotify:track:'+self._id(track['href'], 'track'), 'credits': cells[2]['text']})
            if not rows or not self._date(doc):
                raise ValueError('Kworb did not expose a dated chart with playable song links.')
            return {'items': rows[:request.limit], 'country': request.country, 'period': request.period,
                'data_date': self._date(doc), 'source_url': url, 'fetched_at': captured}
        artist, captured, url = self._artist(request)
        if request.action == 'artist':
            return {**artist, 'source_url': url, 'fetched_at': captured, 'data_date': ''}
        doc, captured, url = self._document(f"artist/{artist['artist_id']}_{request.action}.html")
        kind = 'album' if request.action == 'albums' else 'track'
        rows = []
        for cells in doc.rows:
            for cell in cells[:1]:
                link = next((a for a in cell['links'] if self._id(a['href'], kind)), None)
                if link:
                    rows.append({'name': link['text'], 'uri': 'spotify:'+kind+':'+self._id(link['href'], kind),
                        'streams': cells[1]['text'] if len(cells)>1 else '', 'daily': cells[2]['text'] if len(cells)>2 else ''})
        if not rows:
            raise ValueError('Kworb did not expose recognizable artist entries.')
        return {'artist': artist, 'items': rows[:request.limit], 'data_date': self._date(doc),
            'source_url': url, 'fetched_at': captured, 'ordering': 'streams', 'complete_catalog': False}
