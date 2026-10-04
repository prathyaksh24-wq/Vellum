"""Provider-neutral, validated music intent used by the shared specialist runtime."""

import re
from typing import Callable, Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator


def match_music_control(text: str) -> str | None:
    """Recognize whole control phrases before interpreting any song title."""
    next_track = r"(?:(?:play|go\s+to|skip\s+to)\s+)?(?:the\s+)?next(?:\s+(?:song|track))?|skip(?:\s+(?:this|(?:(?:the\s+)?current)|the))?(?:\s+(?:song|track))?"
    previous = r"(?:(?:play|go\s+to)\s+)?(?:the\s+)?previous(?:\s+(?:song|track))?"
    if re.fullmatch(next_track, text, re.I):
        return "next"
    if re.fullmatch(previous, text, re.I):
        return "previous"
    control = re.fullmatch(r"(pause|resume|stop)(?:\s+(?:the\s+)?(?:song|track|music|spotify))?", text, re.I)
    if control:
        return "pause" if control[1].casefold() == "stop" else control[1].casefold()
    return None


class MusicSongRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(default="", max_length=200)


class MusicPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["play_song", "play_album", "play_playlist", "play_liked", "play_podcast", "play_episode", "create_playlist", "curate_playlist", "seek", "pause", "resume", "next", "previous", "set_shuffle", "set_volume", "adjust_volume", "set_repeat", "save_current", "remove_current", "check_current", "current", "clarify"]
    provider: str = Field(default="spotify", max_length=80, pattern=r"^[a-z][a-z0-9_\-]*$")
    query: str = Field(default="", max_length=500)
    artist: str = Field(default="", max_length=200)
    songs: list[MusicSongRequest] = Field(default_factory=list, max_length=50)
    version: Literal["unspecified", "original"] = "unspecified"
    description: str = Field(default="", max_length=300)
    shuffle: bool | None = None
    position: int | None = Field(default=None, ge=1, le=100000)
    source_uri: str = Field(default="", max_length=200)
    latest: bool = False
    track_uri: str = Field(default='', max_length=200, pattern=r'^(?:spotify:track:[A-Za-z0-9]+)?$')
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    seek_delta_ms: int | None = Field(default=None, ge=-86400000, le=86400000)
    volume_delta_percent: int | None = Field(default=None, ge=-100, le=100)
    repeat_state: Literal["track", "context", "off"] | None = None
    collection: Literal['liked', 'playlist'] = 'liked'
    track_query: str = Field(default='', max_length=200)

    @model_validator(mode="after")
    def required_arguments(self):
        if self.operation == 'play_album' and not (self.artist.strip() if self.latest else self.query.strip()):
            raise ValueError('An artist is required for the latest album, or supply an album title')
        if self.operation in {"play_song", "play_playlist", "play_podcast", "play_episode", "create_playlist"} and not self.query.strip():
            raise ValueError("A song or playlist name is required")
        if self.operation == "create_playlist" and not self.songs:
            raise ValueError("Supply the songs for the new playlist")
        if self.operation == "set_shuffle" and self.shuffle is None:
            raise ValueError("Choose whether shuffle is on or off")
        if self.operation == "set_volume" and self.volume_percent is None:
            raise ValueError("A volume from 0 to 100 is required")
        if self.operation == "seek" and self.seek_delta_ms is None:
            raise ValueError("A seek interval is required")
        if self.operation == "adjust_volume" and self.volume_delta_percent is None:
            raise ValueError("A volume change is required")
        if self.operation == "set_repeat" and self.repeat_state is None:
            raise ValueError("A repeat mode is required")
        return self


class ResolvedMusicSong(MusicSongRequest):
    uri: str = Field(min_length=1, max_length=200)


class MusicPlaylistCreateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=80, pattern=r"^[a-z][a-z0-9_\-]*$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    songs: list[ResolvedMusicSong] = Field(min_length=1, max_length=50)


class MusicCollectionChangeProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['save', 'remove']
    collection: Literal['liked', 'playlist']
    track_uri: str = Field(pattern=r'^spotify:track:[A-Za-z0-9]+$')
    track_title: str = Field(min_length=1, max_length=200)
    playlist_id: str = Field(default='', max_length=160, pattern=r'^[A-Za-z0-9]*$')
    playlist_name: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def playlist_target(self):
        if self.collection=='playlist' and (not self.playlist_id or not self.playlist_name):
            raise ValueError('An exact playlist is required')
        return self


class MusicIntegration(Protocol):
    skill_id: str

    def execute(self, plan: MusicPlan, invoke: Callable[[str, dict], dict]) -> str:
        """Execute normalized intent using only the permissioned capability invoker."""
        ...


class MusicChoiceRequired(ValueError):
    """A provider found multiple valid matches; no playback has happened."""

    def __init__(self, message: str, choices: list[dict]):
        super().__init__(message)
        self.choices = choices[:5]
        self.song_index: int | None = None
