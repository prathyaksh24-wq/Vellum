from agent.tui.cli import PHRASES, main


def test_phrases_dict_has_brand_voice_entries():
    expected_keys = {
        "set", "filed", "out", "withheld", "unreachable",
        "nothing_library", "not_configured",
        "landing_setup", "path_quick", "path_full",
        "confirm_yes", "confirm_no", "cancelled",
    }
    assert expected_keys.issubset(PHRASES.keys())


def test_phrases_never_contain_emoji_or_exclamation():
    for key, value in PHRASES.items():
        assert "!" not in value, f"{key} contains '!'"
        for char in value:
            assert ord(char) < 128 or char in "─│·", f"{key} contains non-ascii '{char}'"


def test_main_is_callable():
    assert callable(main)
