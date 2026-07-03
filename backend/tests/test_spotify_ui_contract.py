from pathlib import Path


HTML_PATH = Path("design/Velllum/uploads/Vellum Default Re-designed.html")


def test_spotify_connection_ui_contract_is_present():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "const SpotifyAPI" in html
    assert "const SpotifyConnectModal" in html
    assert "vellum:spotify-oauth-complete" in html
    assert "http://127.0.0.1:8000/api/plugins/spotify/oauth/callback" in html
    assert "https://developer.spotify.com/dashboard" in html
    assert "Spotify Premium" in html


def test_global_spotify_player_contract_is_present():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "const SpotifyPlayer" in html
    assert "/plugins/spotify/player" in html
    assert "/plugins/spotify/player/action" in html
    assert "document.visibilityState" in html
    assert "spotify-player-pill" in html
    assert "spotify-player-panel" in html


def test_completed_spotify_tools_stop_glowing_and_refresh_the_player_immediately():
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "const stepIsActive = step =>" in html
    assert "stepIsActive(step)" in html
    assert "vellum:spotify-player-refresh" in html
    assert "window.addEventListener('vellum:spotify-player-refresh'" in html
