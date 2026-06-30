class SpotifyError(RuntimeError):
    code = "spotify_error"


class SpotifyAuthError(SpotifyError):
    code = "spotify_auth_error"


class SpotifyPremiumRequired(SpotifyError):
    code = "premium_required"


class SpotifyNoActiveDevice(SpotifyError):
    code = "no_active_device"


class SpotifyRateLimited(SpotifyError):
    code = "rate_limited"

    def __init__(self, retry_after: int):
        super().__init__("Spotify rate limit reached")
        self.retry_after = retry_after
