"""Small, provider-resolved cards for the Music view. Never expose credentials."""

from typing import Literal
from pydantic import BaseModel, Field


class MusicCard(BaseModel):
    id: str
    uri: str = ''
    kind: Literal['track', 'album', 'artist', 'playlist']
    name: str
    artists: list[str] = Field(default_factory=list)
    artwork_url: str = ''
    album: str = ''
    external_url: str = ''
    playable: bool = True
    duration_ms: int = 0
    position: int | None = None
    linked: bool = False
    description: str = ''
    owner_id: str = ''
    editable: bool = False


class MusicCardPage(BaseModel):
    provider: Literal['spotify'] = 'spotify'
    items: list[MusicCard] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    next_offset: int | None = None
    source: Literal['api','public_embed'] = 'api'
    completeness: Literal['complete','partial','unknown'] = 'complete'
    note: str = ''


class MusicTrackArtwork(BaseModel):
    pending: bool = False
    id: str = Field(pattern=r'^[A-Za-z0-9]{22}$')
    artwork_url: str = ''


class MusicTrackArtworkPage(BaseModel):
    items: list[MusicTrackArtwork] = Field(default_factory=list)


def public_playlist_page(rows: list[dict], offset: int, limit: int) -> MusicCardPage:
    return MusicCardPage(items=[MusicCard(**row) for row in rows[offset:offset+limit]],total=len(rows),offset=offset,
        next_offset=offset+limit if offset+limit<len(rows) else None,source='public_embed',completeness='unknown',
        note='Songs shown by Spotify’s public playlist view. This view may omit songs; the complete playlist count could not be verified. Playback still uses your Spotify account.')


def music_card(item: dict, kind: str) -> MusicCard:
    album = item.get('album') or {}
    images = item.get('images') or album.get('images') or []
    names = [a.get('name', '') for a in item.get('artists', []) if a.get('name')]
    return MusicCard(id=str(item.get('id') or ''), uri=item.get('uri') or '', kind=kind,
        name=item.get('name') or 'Untitled', artists=names,
        artwork_url=images[0].get('url', '') if images else '', album=album.get('name') or '',
        external_url=(item.get('external_urls') or {}).get('spotify') or '',
        playable=bool(item.get('uri')) and item.get('is_playable') is not False and not item.get('is_local', False),
        duration_ms=item.get('duration_ms') or 0, linked=item.get('linked') is True,
        description=item.get('description') or '', owner_id=(item.get('owner') or {}).get('id') or '')


def music_card_page(page: dict, kind: str, offset: int, *, unwrap: str = '') -> MusicCardPage:
    raw = page.get('items') or []
    items = [music_card(row.get(unwrap) or {}, kind) if unwrap else music_card(row, kind)
             for row in raw if isinstance(row, dict) and (not unwrap or row.get(unwrap))]
    return MusicCardPage(items=items, total=page.get('total') or 0, offset=offset,
        next_offset=offset + len(raw) if page.get('next') and raw else None)


def music_track_page(page: dict, offset: int, *, playlist: bool = False) -> MusicCardPage:
    """Retain source positions, duplicates and unavailable entries for exact selection."""
    raw = page.get('items') or []
    items = []
    for index, row in enumerate(raw):
        item = (row.get('item') or row.get('track') or {}) if playlist else (row or {})
        if not isinstance(item, dict):
            item = {}
        card = music_card(item, 'track')
        if item.get('type') == 'episode':
            # This song browser preserves the position without presenting an episode as a song.
            card.playable = False
        card.position = offset + index
        if not item:
            card.name = 'Unavailable track'
        items.append(card)
    return MusicCardPage(items=items, total=page.get('total') or 0, offset=offset,
        next_offset=offset + len(raw) if page.get('next') and raw else None)
