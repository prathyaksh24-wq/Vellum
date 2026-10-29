class SpotifyError(RuntimeError):
    code = "spotify_error"


class SpotifyAuthError(SpotifyError):
    code = "spotify_auth_error"


class SpotifyAPIError(SpotifyError):
    code = "spotify_api_error"


class SpotifyAccessDenied(SpotifyAPIError):
    code = "access_denied"


class SpotifyResourceUnavailable(SpotifyAPIError):
    code = "resource_unavailable"


class SpotifyPremiumRequired(SpotifyError):
    code = "premium_required"


class SpotifyNoActiveDevice(SpotifyError):
    code = "no_active_device"


class SpotifyRateLimited(SpotifyError):
    code = "rate_limited"

    def __init__(self, retry_after: int):
        super().__init__("Spotify rate limit reached")
        self.retry_after = retry_after
