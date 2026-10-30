"""Validated read-only intent for the existing YouTube account capabilities."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from agent.contracts.youtube_history import HistoryDayFilter, WEEKDAYS


class YoutubeNotificationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=20, ge=1, le=100)
    view: Literal["recent", "history"] = "recent"


class YoutubeReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["liked", "subscriptions", "history", "uploads", "notifications", "previous", "public", "clarify"]
    view: Literal["videos", "channels", "count", "link", "summary", "clarify"] = "videos"
    limit: int = Field(default=20, ge=1, le=100)
    creator: str = Field(default="", max_length=200)
    names_only: bool = False
    index: int | None = Field(default=None, ge=1, le=100)
    reference_kind: Literal["video", "channel", "item"] = "item"
    count_kind: Literal["videos", "channels"] = "videos"
    day_label: HistoryDayFilter = ""
    notification_view: Literal["recent", "history"] = "recent"

    @model_validator(mode="after")
    def validate_reference(self):
        if self.source == 'notifications' and self.day_label:
            raise ValueError('Notification reads support the recent inbox or retained history, not a date filter')
        if self.source in {'liked', 'subscriptions'} and self.limit > 50:
            raise ValueError('Liked-video and subscription lists support up to 50 entries per reply')
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
    if re.search(r"\b(?:youtube|yt)\b.*\bnotifications?\b|\bnotifications?\b.*\b(?:youtube|yt)\b", text):
        if re.search(r'\b(?:delete|clear|dismiss|mute|disable|unsubscribe|mark)\b', text):
            return YoutubeReadRequest(source='clarify', view='clarify')
        # Do not silently turn a constrained date request into a fresh inbox read.
        if re.search(r'\b(?:today|yesterday|week|month|year|before|after|between|' +
                     '|'.join(day.lower() for day in WEEKDAYS) + r')\b|\b\d{4}-\d{2}-\d{2}\b', text):
            return YoutubeReadRequest(source='clarify', view='clarify')
        history = bool(re.search(r'\b(?:history|older|old|all)\b|\balready read\b', text))
        return YoutubeReadRequest(source='notifications',
            notification_view='history' if history else 'recent',
            view='count' if re.search(r'\b(?:how many|count|number of)\b', text) else 'videos')
    upload = re.search(r"\bwhat\s+(?:did|has)\s+(.+?)\s+upload(?:ed)?\b", text) or re.search(
        r"\buploads?\s+(?:from|by)\s+(.+?)(?=\s+(?:today|yesterday|on\s+\d{4}-\d{2}-\d{2})\b|[?.!]|$)", text)
    if upload:
        iso = re.search(r'\b\d{4}-\d{2}-\d{2}\b',text)
        day = 'Yesterday' if re.search(r'\byesterday\b',text) else 'Today' if re.search(r'\btoday\b',text) else iso[0] if iso else ''
        if re.search(r'\b(?:week|month|year|between|before|after)\b',text):
            return YoutubeReadRequest(source='clarify',view='clarify')
        return YoutubeReadRequest(source='uploads',creator=upload[1].strip(' ?.!'),day_label=day)
    ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    reference = re.search(r"\b(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)?)\s+(?:video|channel|one|item)\b", text)
    if reference and re.search(r"\b(?:link|url)\b", text):
        word = reference[0].split()[0]
        index = ordinals.get(word) or int(re.match(r"\d+", word)[0])
        if not 1 <= index <= 100:
            return YoutubeReadRequest(source="clarify", view="clarify")
        kind = reference[0].split()[-1]
        return YoutubeReadRequest(source="previous", view="link", index=index,
            reference_kind=kind if kind in {"video", "channel"} else "item")
    liked = bool(re.search(r"\b(?:liked|like)\b", text) and re.search(r"\b(?:my|our|i|we)\b", text))
    subscribed = bool(re.search(r"\b(?:subscriptions?|subscribes?|subscribed|subscried)\b", text)
        and re.search(r"\b(?:my|our|i|we)\b", text))
    history = bool(re.search(r"\bwatch history\b|\brefresh\s+(?:my\s+|youtube\s+)?history\b", text) or
        re.search(r"\b(?:watched|watch|seen)\b", text) and re.search(r"\b(?:my|our|i|we)\b", text))
    if not liked and not subscribed and not history:
        return None
    source = "liked" if liked else "subscriptions" if subscribed else "history"
    creator = re.search(r'\bby\s+(.+?)(?=\s+(?:from|in)\s+my\s+(?:watch\s+)?history|[?.!]|$)', query, re.I) or re.search(
        r'\bfrom\s+(.+?)(?=\s+(?:from|in)\s+my\s+(?:watch\s+)?history|[?.!]|$)', query, re.I)
    creator_name = creator[1].strip() if creator and source == 'history' else ''
    if re.match(r'(?:my|our|videos?|entries|history|youtube|yt)\b', creator_name, re.I):
        creator_name = ''
    projection_text = text.replace(creator_name.casefold(), '') if creator_name else text
    count = bool(re.search(r"\b(?:how many|count|number of)\b", text))
    channels = source == "subscriptions" or bool(re.search(r"\b(?:channels?|creators?|uploaders?)\b", projection_text))
    iso_date = re.search(r'\b\d{4}-\d{2}-\d{2}\b', text)
    weekday = re.search(r'\b(last\s+)?(' + '|'.join(day.lower() for day in WEEKDAYS) + r')\b', text)
    day = 'Today' if re.search(r'\btoday\b',text) else 'Yesterday' if re.search(r'\byesterday\b',text) else \
        iso_date[0] if iso_date else ('Last ' if weekday[1] else '') + weekday[2].title() if weekday else ''
    if source == 'history' and re.search(r'\b(?:week|month|year|weekend|before|after|between)\b', text):
        return YoutubeReadRequest(source='clarify', view='clarify')
    quantity_text = text.replace(iso_date[0], '') if iso_date else text
    number = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|dozen)\b", quantity_text)
    words = dict(zip("one two three four five six seven eight nine ten dozen".split(), [1,2,3,4,5,6,7,8,9,10,12]))
    limit = int(number[1]) if number and number[1].isdigit() else words.get(number[1], 20) if number else (50 if source == "subscriptions" else 20)
    if not 1 <= limit <= (100 if source == 'history' else 50):
        return YoutubeReadRequest(source="clarify", view="clarify")
    names_only = bool(re.search(r"\b(?:name|names|only|just)\b", text))
    summary = source == 'history' and bool(re.search(r'\b(?:trends?|patterns?|analysis|analyse|analyze|summary|summarize|summarise|habits|insights?)\b', text))
    if source == 'history' and not number and re.search(r'\b(?:latest|last|most recent)\s+video\b', text):
        limit = 1
    return YoutubeReadRequest(source=source, view="count" if count else "summary" if summary else "channels" if channels else "videos",
        limit=limit, names_only=names_only, count_kind="channels" if channels else "videos",
        day_label=day if source == 'history' else '', creator=creator_name)
