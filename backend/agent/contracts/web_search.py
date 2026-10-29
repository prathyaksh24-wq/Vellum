"""Search-provider preferences contain no credentials."""
from typing import Literal
from pydantic import BaseModel, ConfigDict


class WebSearchSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['auto', 'serpapi', 'exa', 'tavily', 'brave', 'ddgs']


class WebSearchChoice(BaseModel):
    id: str
    name: str
    available: bool


class WebSearchSettings(BaseModel):
    selected: str
    active: str | None
    automatic_fallback: bool
    providers: list[WebSearchChoice]
