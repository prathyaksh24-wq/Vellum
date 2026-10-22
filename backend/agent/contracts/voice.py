"""Public contracts for Vellum's local direct-audio voice transport."""

from __future__ import annotations

from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from agent.voice.dictation_models import LANGUAGE_CODES, validate_language


class VoiceCapabilities(BaseModel):
    """What the active voice provider can actually do in this release."""

    provider: str = "lfm2.5-audio"
    model: str = "LiquidAI/LFM2.5-Audio-1.5B"
    mode: Literal["direct_audio"] = "direct_audio"
    available: bool = False
    local: bool = True
    pause_to_reply: bool = True
    continuous_duplex: bool = False
    barge_in: bool = False
    automatic_turn_detection: bool = True
    input_transcription: bool = True
    tools: bool = False
    memory: bool = False
    cloud_audio: bool = False
    input_format: Literal["audio/wav"] = "audio/wav"
    output_format: Literal["pcm_s16le"] = "pcm_s16le"
    sample_rate_hz: int = 24_000
    languages: list[str] = Field(default_factory=lambda: ["en"])
    notes: list[str] = Field(default_factory=list)


class VoiceStatus(BaseModel):
    enabled: bool
    ready: bool
    state: Literal["disabled", "unavailable", "cold", "starting", "ready", "busy", "error"]
    detail: str = ""
    capabilities: VoiceCapabilities


class DictationStatus(BaseModel):
    enabled: bool
    available: bool
    ready: bool
    state: Literal["disabled", "unavailable", "cold", "starting", "ready", "busy", "error"]
    detail: str = ""
    model: str = "openai/whisper-large-v3-turbo"
    local: Literal[True] = True
    device: str = "auto"
    max_input_seconds: int = 300


class DictationTranscript(BaseModel):
    text: str
    language: str | None = None
    duration_seconds: float
    model: str = "openai/whisper-large-v3-turbo"
    local: Literal[True] = True
    device: str
    requested_language: str = "auto"
    history_id: str | None = None
    history_error: str | None = None


class DictationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = "auto"
    save_history: bool = Field(default=True,strict=True)
    dictionary: list[str] = Field(default_factory=list,max_length=100)
    hold_shortcut: str = Field(default='',max_length=50)
    toggle_shortcut: str = Field(default='Ctrl+Shift+D',max_length=50)

    @field_validator('dictionary')
    @classmethod
    def dictionary_phrases(cls,value):
        clean=[' '.join(phrase.split()) for phrase in value]
        if any(not phrase or len(phrase)>100 for phrase in clean):
            raise ValueError('Use up to 100 nonempty dictionary phrases, each up to 100 characters.')
        return list(dict((phrase.casefold(),phrase) for phrase in clean).values())

    @field_validator('hold_shortcut','toggle_shortcut')
    @classmethod
    def shortcut_chord(cls,value):
        if value and not re.fullmatch(r'(?:(?:Ctrl|Alt|Shift|Meta)\+)+(?:[A-Z0-9]|Space|F(?:[1-9]|1[0-2]))',value):
            raise ValueError('Use Ctrl, Alt or Meta plus a letter, number, Space or function key.')
        if value and not any(key+'+' in value for key in ('Ctrl','Alt','Meta')):
            raise ValueError('Include Ctrl, Alt or Meta in a dictation shortcut.')
        tokens=value.split('+')
        if len(tokens)!=len(set(tokens)):
            raise ValueError('Do not repeat a shortcut key.')
        if not value:
            return value
        value='+'.join([key for key in ('Ctrl','Alt','Shift','Meta') if key in tokens[:-1]]+[tokens[-1]])
        # Preserve editing, Vellum navigation, live voice and common OS commands.
        modifiers=set(tokens[:-1])
        key=tokens[-1]
        if (modifiers in ({'Ctrl'},{'Meta'}) and key in 'CVXAZSNWRFKU') or (modifiers in ({'Ctrl','Shift'},{'Meta','Shift'}) and key in 'VOHSILGKEMNFBPZ') or value in {'Alt+F4','Ctrl+Alt+Delete','Meta+L','Meta+D','Meta+E','Ctrl+Escape'}:
            raise ValueError('That shortcut is already used for another command.')
        return value

    @model_validator(mode='after')
    def distinct_shortcuts(self):
        if self.hold_shortcut and self.hold_shortcut==self.toggle_shortcut:
            raise ValueError('Choose different hold and single-tap shortcuts.')
        return self

    @field_validator("language")
    @classmethod
    def supported_language(cls, value: str) -> str:
        return validate_language(value)


class DictationPreferencesView(BaseModel):
    settings: DictationPreferences
    available_languages: list[str] = Field(default_factory=lambda:list(LANGUAGE_CODES))


class DictationHistoryEntry(BaseModel):
    id: str
    created_at: str
    text: str = Field(min_length=1, max_length=100_000)
    language: str | None = None
    requested_language: str = "auto"
    duration_seconds: float = Field(ge=0,le=300)
    model: str
    has_recording: bool = False


class DictationHistoryPage(DictationPreferencesView):
    items: list[DictationHistoryEntry] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 30
    language_counts: dict[str,int] = Field(default_factory=dict)


class DictationHistoryDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_id: str | None = Field(default=None,pattern=r"^[a-f0-9]{32}$")
    all: bool = Field(default=False,strict=True)

    @model_validator(mode="after")
    def exactly_one_target(self):
        if bool(self.entry_id) == self.all:
            raise ValueError("Choose one transcript or explicitly clear all history.")
        return self
