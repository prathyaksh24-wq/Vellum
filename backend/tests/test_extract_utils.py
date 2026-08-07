from pathlib import Path

from agent.tools.extract_utils import (
    blocked_url_reason,
    convert_base64_images_to_links,
    normalize_extract_url,
    truncate_with_footer,
)


def test_truncate_keeps_short_content_whole(tmp_path):
    content = "short page content"
    text, truncated = truncate_with_footer(content, "https://example.com/a", 15000, tmp_path)

    assert truncated is False
    assert text == content


def test_truncate_head_tail_footer_and_stored_file(tmp_path):
    content = "line one\n" + ("word " * 3000)
    text, truncated = truncate_with_footer(content, "https://example.com/big", 2000, tmp_path)

    assert truncated is True
    assert "[TRUNCATED]" in text
    assert "Full text saved to:" in text
    assert "read_file" in text
    stored = list(tmp_path.iterdir())
    assert len(stored) == 1
    assert stored[0].read_text(encoding="utf-8") == content


def test_convert_base64_images_to_links():
    text = (
        "![alt text](data:image/png;base64,AAAAAA==) after\n"
        "plain (data:image/jpeg;base64,BBBB) middle\n"
        "bare data:image/gif;base64,CCCC end\n"
        "![real](https://example.com/img.png) kept"
    )
    converted = convert_base64_images_to_links(text)

    assert "[IMAGE: alt text]" in converted
    assert "data:image/png" not in converted
    assert "data:image/jpeg" not in converted
    assert "data:image/gif" not in converted
    assert "https://example.com/img.png" in converted


def test_blocked_url_reason_catches_key_shapes():
    assert blocked_url_reason("https://example.com/watch?v=sk-abcdef1234567890xyz") is not None
    assert blocked_url_reason("https://example.com/?api_key=secretvalue12345") is not None
    assert blocked_url_reason("https://example.com/?access_token=abc123") is not None
    assert blocked_url_reason("https://example.com/plain?q=hello") is None


def test_normalize_extract_url_shapes():
    assert normalize_extract_url("  https://example.com/a  ") == "https://example.com/a"
    assert normalize_extract_url({"url": "https://example.com/b"}) == "https://example.com/b"
    assert normalize_extract_url({"href": "https://example.com/c"}) == "https://example.com/c"
    assert normalize_extract_url(42) is None
    assert normalize_extract_url({"url": ""}) is None
