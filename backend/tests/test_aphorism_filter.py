import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "aphorism_filter.py"


def _load():
    spec = importlib.util.spec_from_file_location("aphorism_filter", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _item(**overrides):
    base = {
        "text": "Play long-term games with long-term people.",
        "isRetweet": False,
        "isReply": False,
        "isQuote": False,
        "media": [],
    }
    base.update(overrides)
    return base


def test_short_standalone_wisdom_is_aphorism():
    af = _load()
    assert af.is_aphorism(_item()) is True


def test_retweet_rejected():
    af = _load()
    assert af.is_aphorism(_item(isRetweet=True)) is False


def test_reply_rejected():
    af = _load()
    assert af.is_aphorism(_item(isReply=True)) is False


def test_quote_tweet_rejected():
    af = _load()
    assert af.is_aphorism(_item(isQuote=True)) is False


def test_tweet_with_url_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="Listen here: https://example.com/podcast")) is False


def test_tweet_with_media_rejected():
    af = _load()
    assert af.is_aphorism(_item(media=[{"type": "photo", "url": "x"}])) is False


def test_starts_with_mention_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="@balajis good thread.")) is False


def test_podcast_toc_rejected_via_newlines():
    af = _load()
    text = "New podcast - Sell the Truth.\n00:00 Be Credible\n03:18 Yes, And\n04:31 Selfish Honesty"
    assert af.is_aphorism(_item(text=text)) is False


def test_long_tweet_over_max_chars_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="a" * 281)) is False


def test_one_word_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="Yes.")) is False


def test_sixty_one_words_rejected():
    af = _load()
    text = " ".join(["word"] * 61)
    assert af.is_aphorism(_item(text=text)) is False


def test_three_word_tweet_accepted():
    af = _load()
    assert af.is_aphorism(_item(text="Read, then write.")) is True


def test_four_sentences_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="One. Two. Three. Four.")) is False


def test_three_sentences_accepted():
    af = _load()
    assert af.is_aphorism(_item(text="Read. Think. Write.")) is True


def test_empty_text_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="")) is False
