class GoogleCalendarError(RuntimeError):
    """Base error for the Google Calendar connector."""


class GoogleCalendarAuthError(GoogleCalendarError):
    """Google Calendar authorization is missing or invalid."""


class GoogleCalendarAPIError(GoogleCalendarError):
    """Google Calendar returned an unavailable or invalid response."""
