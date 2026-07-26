from agent.profiles.models import builtin_profiles


def test_youtube_profile_allows_local_personal_context() -> None:
    profile = builtin_profiles()["YoutubeAgent"]

    assert "youtube.personal_context" in profile.tools.allow
