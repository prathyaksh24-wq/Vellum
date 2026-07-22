"""Typed, content-free errors for the YouTube connector."""


class YouTubeError(RuntimeError):
    code = "youtube_error"


class YouTubeAuthError(YouTubeError):
    code = "youtube_auth_error"


class YouTubeAPIError(YouTubeError):
    code = "youtube_api_error"
