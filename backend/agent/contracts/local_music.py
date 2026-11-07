"""Local music contracts: playlist references and acquired audio remain distinct."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlsplit


class MusicSourceEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=500)
    artist: str = Field(default='', max_length=500)
    album: str = Field(default='', max_length=500)
    duration_ms: int = Field(default=0, ge=0, le=86400000)
    provider: Literal['local', 'spotify', 'apple_music', 'youtube','amazon_music','jiosaavn','soundcloud','bandcamp'] = 'local'
    source_id: str = Field(default='', max_length=200)
    source_url: str = Field(default='', max_length=2048)
    thumbnail_url: str = Field(default='',max_length=2048)

    @field_validator('thumbnail_url')
    @classmethod
    def public_thumbnail(cls,value):
        if not value:return value
        parsed=urlsplit(value)
        host=(parsed.hostname or '').lower()
        domains=('ytimg.com','mzstatic.com','saavncdn.com','sndcdn.com','bcbits.com','media-amazon.com','googleusercontent.com','scdn.co')
        if parsed.scheme!='https' or parsed.username or parsed.password or not any(host==domain or host.endswith('.'+domain) for domain in domains):
            raise ValueError('Choose artwork from the music provider.')
        return value


class LocalMusicEntry(MusicSourceEntry):
    artwork_url: str = ''
    id: str
    available: bool = False
    audio_source: str = ''


class LocalMusicCollection(BaseModel):
    id: str
    name: str
    source_url: str = ''
    completeness: Literal['complete', 'partial', 'unknown'] = 'complete'
    note: str = ''
    entries: list[LocalMusicEntry] = Field(default_factory=list)


class MusicImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(default='', max_length=2048)
    name: str = Field(default='Imported playlist', min_length=1, max_length=200)
    entries: list[MusicSourceEntry] = Field(default_factory=list, max_length=5000)
    completeness: Literal['complete', 'partial', 'unknown'] = 'unknown'
    source_origin: str = Field(default='', max_length=2048)
    download_mp3: bool = False
    auto_import: bool = False
    permission_confirmed: Literal[True] | None = None
    pending_import_id: str = Field(default='', max_length=64)

    @model_validator(mode='after')
    def source(self):
        if sum(map(bool, (self.url.strip(), self.entries, self.pending_import_id))) != 1:
            raise ValueError('Choose a source link or a playlist manifest.')
        if self.download_mp3 and not self.url.strip():
            raise ValueError('Choose a song or playlist link to convert.')
        if self.auto_import and not self.download_mp3:
            raise ValueError('Automatic import requires MP3 downloads.')
        return self


class MusicDownloadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entry_ids: list[str] = Field(default_factory=list, max_length=500)
    collection_id: str = Field(default='', max_length=64)
    source_url: str = Field(default='', max_length=2048)
    permission_confirmed: Literal[True] | None = None

    @model_validator(mode='after')
    def target(self):
        if bool(self.entry_ids) == bool(self.collection_id):
            raise ValueError('Choose songs or a playlist to download.')
        if self.collection_id and self.source_url:
            raise ValueError('A recording link can only be supplied for one song.')
        return self


class MusicFileImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_token: str = Field(pattern=r'^[a-f0-9]{32}$')
    entry_id: str = Field(default='', max_length=64)


class MusicRemoveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    collection_id: str = Field(default='', max_length=64)
    entry_id: str = Field(default='', max_length=64)

    @model_validator(mode='after')
    def target(self):
        if bool(self.collection_id) == bool(self.entry_id):
            raise ValueError('Choose one playlist or one song to remove.')
        return self


class MusicRefreshRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    collection_id: str = Field(min_length=1,max_length=64)


class MusicJobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    operation: Literal['cancel', 'retry']


class LocalPlaybackRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['play', 'pause', 'resume', 'next', 'previous', 'seek', 'volume', 'shuffle', 'repeat']
    entry_ids: list[str] = Field(default_factory=list, max_length=5000)
    query: str = Field(default='', max_length=500)
    position: int = Field(default=0, ge=0, le=4999)
    seconds: float = Field(default=0, ge=0, le=86400, allow_inf_nan=False)
    volume: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    enabled: bool = False
    repeat: Literal['off', 'all', 'one'] = 'off'


class LocalPlayerReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner_id: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    revision: int = Field(ge=0)
    entry_id: str = Field(default='', max_length=64)
    playing: bool = False
    seconds: float = Field(default=0, ge=0, le=86400, allow_inf_nan=False)
    duration: float = Field(default=0, ge=0, le=86400, allow_inf_nan=False)
    error: str = Field(default='', max_length=300)


class LocalPlayerState(BaseModel):
    revision: int = 0
    queue: list[str] = Field(default_factory=list)
    index: int = 0
    playing: bool = False
    seconds: float = 0
    volume: float = 0.7
    shuffle: bool = False
    repeat: Literal['off', 'all', 'one'] = 'off'
    observed: dict = Field(default_factory=dict)
    owner_available: bool = False


class LocalMusicJob(BaseModel):
    id: str
    entry_id: str
    title: str
    status: Literal['queued', 'running', 'complete', 'failed', 'cancelled']
    error: str = ''
    stage: Literal['', 'finding', 'downloading', 'converting'] = ''
    progress: int | None = Field(default=None, ge=0, le=100)


class LocalMusicLibrary(BaseModel):
    collections: list[LocalMusicCollection] = Field(default_factory=list)
    pending_imports: list[LocalMusicCollection] = Field(default_factory=list)
    jobs: list[LocalMusicJob] = Field(default_factory=list)
    player: LocalPlayerState
    downloader_available: bool
    discovery_available: bool
    mp3_available: bool = False


class MusicDiscoveryPage(BaseModel):
    items: list[MusicSourceEntry] = Field(default_factory=list)


class MusicAccountPlaylists(BaseModel):
    items: list[dict[str, str]] = Field(default_factory=list)
    note: str = ''
