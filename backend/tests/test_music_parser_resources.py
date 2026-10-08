"""Untrusted music wording cannot monopolize the chat parsing thread."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent.agents.music import MusicAgent, music_provider_request


def test_repeated_whitespace_and_prefixes_finish_without_regex_backtracking():
    # A subprocess bounds a regression: a vulnerable regex must fail the test,
    # rather than hang the entire backend suite. Imports precede the timer.
    code = r'''
from time import perf_counter
from agent.agents.music import MusicAgent, music_provider_request
from agent.api import _requests_fresh_public_data
from pydantic import ValidationError

padding = " " * 24000
cases = [
    (music_provider_request, padding + "!"),
    (music_provider_request, "play Song" + "\t" * 24000 + "!"),
    (MusicAgent._history_plan, "what " + padding + "played!"),
    (MusicAgent._history_plan, "what songs played by " + padding + "!"),
    (MusicAgent._history_plan, "what " * 24000 + "did i play"),
    (MusicAgent._history_plan, "what songs played by " + "from " * 24000 + "!"),
    (MusicAgent._language_request, "put " + padding + "! music"),
    (MusicAgent._language_request, "bro " * 24000 + "! music"),
    (MusicAgent._language_request, "put " * 24000 + "! music"),
    (MusicAgent._kworb_plan, "show " + padding + "! charts"),
    (MusicAgent._kworb_plan, "show a" + padding + "! songs"),
    (MusicAgent._kworb_plan, "show charts from " + "from " * 24000 + "!"),
    (MusicAgent._kworb_plan, "show " + "find a" * 24000 + "!"),
    (MusicAgent._fast_plan, "create playlist named Test with " + padding + "!"),
    (MusicAgent._fast_plan, "latest a" + padding + "!"),
    (MusicAgent._fast_plan, "play a" + padding + "! album"),
    (MusicAgent._fast_plan, "set volume to 20" + padding + "!"),
    (MusicAgent._fast_plan, "latest " + "latest a" * 24000 + "!"),
    (MusicAgent._fast_plan, "play " + "play a" * 24000 + "!"),
    (MusicAgent._compound_clauses, "play Song and " + "also " * 24000 + "!"),
    (MusicAgent._compound_clauses, "play Song" + " and nope" * 24000),
    (_requests_fresh_public_data, "play it" + padding + "!"),
]
for parser, text in cases:
    started = perf_counter()
    try:
        parser(text)
    except ValidationError:
        # Existing typed-plan limits may reject enormous artist/country names.
        # Rejection must be fast too; no truncation or relaxed schema is needed.
        pass
    elapsed = perf_counter() - started
    assert elapsed < 1, (parser.__name__, elapsed)
print("all adversarial parsing cases completed")
'''
    backend = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": backend},
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "all adversarial parsing cases completed" in result.stdout


def test_provider_suffix_preserves_title_and_accepts_unicode_whitespace():
    assert music_provider_request('play "A  B"\t on\u2003Spotify please') == (
        'play "A  B"', 'spotify', True,
    )


@pytest.mark.parametrize('text', [
    'what\tDrake\u2003songs did I play today?',
    'what songs did I play by\tDrake today?',
])
def test_history_artist_delimiters_preserve_normal_requests(text):
    plan = MusicAgent._history_plan(text)
    assert plan.operation == 'listening_history'
    assert plan.artist == 'Drake'
    assert plan.history_period == 'today'


def test_spaced_and_quoted_compound_commands_preserve_titles():
    clauses = MusicAgent._compound_clauses('play "Earth, Wind and Fire" and also please pause')
    assert clauses == ['play "Earth, Wind and Fire"', 'please pause']


def test_create_playlist_retains_comma_and_and_separators():
    plan = MusicAgent._fast_plan('create playlist named Mix with One by A,Two by B and Three by C')
    assert [song.model_dump() for song in plan.songs] == [
        {'title': 'One', 'artist': 'A'},
        {'title': 'Two', 'artist': 'B'},
        {'title': 'Three', 'artist': 'C'},
    ]


@pytest.mark.parametrize('suffix', ['20', '20%', '20 percent', '20 please', '20% please', '20 percent please'])
def test_absolute_volume_keeps_units_and_polite_suffix(suffix):
    plan = MusicAgent._fast_plan('set volume to ' + suffix)
    assert plan.operation == 'set_volume'
    assert plan.volume_percent == 20
