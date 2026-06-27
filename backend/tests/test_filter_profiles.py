import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "filter_profiles.py"


def _load():
    spec = importlib.util.spec_from_file_location("filter_profiles", SCRIPT_PATH)
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


# ---- aphorism profile (carries the prior 15 cases) ----

def test_aphorism_accepts_short_wisdom():
    fp = _load()
    assert fp.accepts("aphorism", _item()) is True

def test_aphorism_rejects_retweet():
    fp = _load()
    assert fp.accepts("aphorism", _item(isRetweet=True)) is False

def test_aphorism_rejects_reply():
    fp = _load()
    assert fp.accepts("aphorism", _item(isReply=True)) is False

def test_aphorism_rejects_quote_tweet():
    fp = _load()
    assert fp.accepts("aphorism", _item(isQuote=True)) is False

def test_aphorism_rejects_url():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="Read: https://example.com")) is False

def test_aphorism_rejects_media():
    fp = _load()
    assert fp.accepts("aphorism", _item(media=[{"type": "photo"}])) is False

def test_aphorism_rejects_mention_start():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="@bob hi.")) is False

def test_aphorism_rejects_multi_newline():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="One.\nTwo.\nThree.")) is False

def test_aphorism_rejects_over_280_chars():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="a" * 281)) is False

def test_aphorism_rejects_one_word():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="Yes.")) is False

def test_aphorism_rejects_61_words():
    fp = _load()
    assert fp.accepts("aphorism", _item(text=" ".join(["w"] * 61))) is False

def test_aphorism_rejects_4_sentences():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="One. Two. Three. Four.")) is False

def test_aphorism_accepts_3_sentences():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="Read. Think. Write.")) is True

def test_aphorism_accepts_three_words():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="Stay. Be. Become.")) is True

def test_aphorism_rejects_empty():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="")) is False


# ---- multiline_quote profile ----

def test_multiline_quote_accepts_couplet():
    fp = _load()
    text = "The wound is the place\nwhere the light enters you."
    assert fp.accepts("multiline_quote", _item(text=text)) is True

def test_multiline_quote_accepts_10_lines():
    fp = _load()
    text = "\n".join(["line one"] * 11)  # 11 lines = 10 newlines
    assert fp.accepts("multiline_quote", _item(text=text)) is True

def test_multiline_quote_rejects_11_newlines():
    fp = _load()
    text = "\n".join(["line"] * 12)  # 11 newlines
    assert fp.accepts("multiline_quote", _item(text=text)) is False

def test_multiline_quote_rejects_over_500_chars():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(text="a" * 501)) is False

def test_multiline_quote_rejects_url():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(text="Wisdom\nhttp://x.com/y")) is False

def test_multiline_quote_rejects_media():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(media=[{"type": "photo"}])) is False

def test_multiline_quote_rejects_retweet():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(isRetweet=True)) is False

def test_multiline_quote_rejects_too_short():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(text="So")) is False


# ---- original_tweet profile (Hormozi-style mini-essays) ----

def test_original_tweet_accepts_long_essay():
    fp = _load()
    text = ("Most people overestimate what they can do in a day\n"
            "and underestimate what they can do in a year.\n"
            "Stack small wins. Compound never fails. Win the decade by winning today.")
    assert fp.accepts("original_tweet", _item(text=text)) is True

def test_original_tweet_rejects_under_10_words():
    fp = _load()
    assert fp.accepts("original_tweet", _item(text="One two three four five six seven eight nine.")) is False

def test_original_tweet_rejects_url():
    fp = _load()
    assert fp.accepts("original_tweet", _item(text="long enough wisdom https://example.com extra words")) is False

def test_original_tweet_rejects_retweet():
    fp = _load()
    long = " ".join(["word"] * 20)
    assert fp.accepts("original_tweet", _item(text=long, isRetweet=True)) is False

def test_original_tweet_rejects_reply():
    fp = _load()
    long = " ".join(["word"] * 20)
    assert fp.accepts("original_tweet", _item(text=long, isReply=True)) is False

def test_original_tweet_rejects_media():
    fp = _load()
    long = " ".join(["word"] * 20)
    assert fp.accepts("original_tweet", _item(text=long, media=[{"type": "photo"}])) is False


# ---- registry ----

def test_unknown_profile_raises():
    fp = _load()
    import pytest
    with pytest.raises(KeyError):
        fp.accepts("nonexistent_profile", _item())

def test_profiles_registry_lists_three():
    fp = _load()
    assert set(fp.PROFILES.keys()) == {"aphorism", "multiline_quote", "original_tweet"}


# ---- cross-actor retweet/reply/quote detection ----

def test_retweet_detected_via_retweeted_tweet_object():
    """patient_discovery actor shape: presence of retweeted_tweet means RT."""
    fp = _load()
    item = _item(text="Some real wisdom here.", retweeted_tweet={"tweet_id": "999"})
    assert fp.accepts("aphorism", item) is False

def test_retweet_detected_via_text_rt_prefix():
    """patient_discovery returns the embedded RT @ text on retweets."""
    fp = _load()
    item = _item(text="RT @someone: Worth reading.")
    assert fp.accepts("aphorism", item) is False

def test_reply_detected_via_in_reply_to_status_id():
    fp = _load()
    item = _item(text="A thoughtful reply.", in_reply_to_status_id="12345")
    assert fp.accepts("aphorism", item) is False

def test_quote_detected_via_quoted_tweet_object():
    fp = _load()
    item = _item(text="My take on this.", quoted_tweet={"tweet_id": "999"})
    assert fp.accepts("aphorism", item) is False

def test_quote_detected_via_is_quote_status_camelcase():
    """xquik actor shape uses isQuoteStatus."""
    fp = _load()
    item = _item(text="My take here.", isQuoteStatus=True)
    assert fp.accepts("aphorism", item) is False
