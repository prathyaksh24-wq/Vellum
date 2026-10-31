"""Local music contracts: playlist references and acquired audio remain distinct."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MusicSourceEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=500)
    artist: str = Field(default='', max_length=500)
    album: str = Field(default='', max_length=500)
    duration_ms: int = Field(default=0, ge=0, le=86400000)
    provider: Literal['local', 'spotify', 'apple_music', 'youtube'] = 'local'
    source_id: str = Field(default='', max_length=200)
    source_url: str = Field(default='', max_length=2048)


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

    @model_validator(mode='after')
    def source(self):
        if bool(self.url.strip()) == bool(self.entries):
            raise ValueError('Choose a source link or a playlist manifest.')
        return self


class MusicDownloadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entry_ids: list[str] = Field(min_length=1, max_length=500)
    source_url: str = Field(default='', max_length=2048)
    permission_confirmed: Literal[True]


class MusicFileImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_token: str = Field(pattern=r'^[a-f0-9]{32}$')
    entry_id: str = Field(default='', max_length=64)


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


class LocalMusicLibrary(BaseModel):
    collections: list[LocalMusicCollection] = Field(default_factory=list)
    jobs: list[LocalMusicJob] = Field(default_factory=list)
    player: LocalPlayerState
    downloader_available: bool
    discovery_available: bool


class MusicDiscoveryPage(BaseModel):
    items: list[MusicSourceEntry] = Field(default_factory=list)


class MusicAccountPlaylists(BaseModel):
    items: list[dict[str, str]] = Field(default_factory=list)
    note: str = ''
