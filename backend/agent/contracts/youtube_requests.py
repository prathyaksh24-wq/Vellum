"""Validated read-only intent for the existing YouTube account capabilities."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class YoutubeReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["liked", "subscriptions", "previous", "public", "clarify"]
    view: Literal["videos", "channels", "count", "link", "summary", "clarify"] = "videos"
    limit: int = Field(default=20, ge=1, le=50)
    creator: str = Field(default="", max_length=200)
    names_only: bool = False
    index: int | None = Field(default=None, ge=1, le=50)
    reference_kind: Literal["video", "channel", "item"] = "item"
    count_kind: Literal["videos", "channels"] = "videos"

    @model_validator(mode="after")
    def validate_reference(self):
        if self.view == "link" and (self.source != "previous" or self.index is None):
            raise ValueError("A link reference requires the displayed list and an item number")
        if self.source == "previous" and self.view != "link":
            raise ValueError("Previous output currently supports verified item links")
        if self.source == "subscriptions" and self.view == "videos":
            raise ValueError("Subscriptions contain channels, not videos")
        return self


def clear_read_request(query: str) -> YoutubeReadRequest | None:
    """Compatibility parser for unambiguous reads when no model planner is supplied."""
    text = " ".join(query.casefold().split())
    ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    reference = re.search(r"\b(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)?)\s+(?:video|channel|one|item)\b", text)
    if reference and re.search(r"\b(?:link|url)\b", text):
        word = reference[0].split()[0]
        index = ordinals.get(word) or int(re.match(r"\d+", word)[0])
        if not 1 <= index <= 50:
            return YoutubeReadRequest(source="clarify", view="clarify")
        kind = reference[0].split()[-1]
        return YoutubeReadRequest(source="previous", view="link", index=index,
            reference_kind=kind if kind in {"video", "channel"} else "item")
    liked = bool(re.search(r"\b(?:liked|like)\b", text) and re.search(r"\b(?:my|our|i|we)\b", text))
    subscribed = bool(re.search(r"\b(?:subscriptions?|subscribes?|subscribed|subscried)\b", text)
        and re.search(r"\b(?:my|our|i|we)\b", text))
    if not liked and not subscribed:
        return None
    source = "liked" if liked else "subscriptions"
    count = bool(re.search(r"\b(?:how many|count|number of)\b", text))
    channels = source == "subscriptions" or bool(re.search(r"\b(?:channels?|creators?|uploaders?)\b", text))
    number = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|dozen)\b", text)
    words = dict(zip("one two three four five six seven eight nine ten dozen".split(), [1,2,3,4,5,6,7,8,9,10,12]))
    limit = int(number[1]) if number and number[1].isdigit() else words.get(number[1], 20) if number else (50 if source == "subscriptions" else 20)
    if not 1 <= limit <= 50:
        return YoutubeReadRequest(source="clarify", view="clarify")
    names_only = bool(re.search(r"\b(?:name|names|only|just)\b", text))
    return YoutubeReadRequest(source=source, view="count" if count else "channels" if channels else "videos",
        limit=limit, names_only=names_only, count_kind="channels" if channels else "videos")
