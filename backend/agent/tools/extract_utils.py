"""Shared helpers for the Hermes-style ``web_extract_pages`` tool.

Port of Hermes' ``tools/web_tools.py`` extract pipeline pieces: URL
normalization, secret-in-URL blocking, base64-image placeholder
conversion, and head+tail truncate-and-store for pages over the char
budget. Deterministic — no LLM involvement.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlsplit

from agent.tools.url_safety import normalize_url_for_request, sensitive_query_param_name

logger = logging.getLogger(__name__)

DEFAULT_EXTRACT_CHAR_LIMIT = 15000
MAX_STORED_TEXT_CHARS = 200_000

# Recognizable vendor key / credential shapes. Belt-and-suspenders next to
# ``sensitive_query_param_name``, which catches opaque credential-named params.
_SECRET_IN_URL_RE = re.compile(
    r"(?:"
    r"sk-[A-Za-z0-9]{16,}|"              # OpenAI-style keys
    r"ghp_[A-Za-z0-9]{20,}|"             # GitHub PAT
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"     # Slack tokens
    r"AIza[0-9A-Za-z_-]{20,}|"           # Google API keys
    r"AKIA[0-9A-Z]{16}|"                 # AWS access key ids
    r"Bearer [A-Za-z0-9._~+/=-]{16,}|"   # Bearer tokens
    r"(?:api[_-]?key|apikey|auth[_-]?token|access[_-]?token|password|passwd|secret)"
    r"[=:][A-Za-z0-9._~+/=-]{6,}"
    r")",
    re.IGNORECASE,
)


def blocked_url_reason(url: str) -> Optional[str]:
    """Return an error message when ``url`` carries secrets, else None.

    URL-decodes first so percent-encoded secrets (``%73k-`` = ``sk-``) are
    caught. Applies to both the raw and normalized forms.
    """
    if _SECRET_IN_URL_RE.search(url) or _SECRET_IN_URL_RE.search(unquote(url)):
        return (
            "Blocked: URL contains what appears to be an API key or token. "
            "Secrets must not be sent in URLs."
        )
    sensitive = sensitive_query_param_name(url)
    if sensitive:
        return (
            "Blocked: URL contains a credential-like query parameter "
            f"({sensitive}). Web extract backends are third-party readers; "
            "remove the sensitive query parameter or fetch the page locally."
        )
    return None


def normalize_extract_url(item: Any) -> Optional[str]:
    """Accept a URL string or an object with a string ``url``/``href`` field."""
    if isinstance(item, str):
        return normalize_url_for_request(item.strip()) or None
    if isinstance(item, dict):
        value = item.get("url") or item.get("href")
        if isinstance(value, str) and value.strip():
            return normalize_url_for_request(value.strip())
    return None


def convert_base64_images_to_links(text: str) -> str:
    """Replace inline base64 image blobs with labeled placeholders.

    base64 image payloads are token bombs (a single inline PNG can be tens
    of thousands of characters), so raw bytes are never sent to the model.
    Real (http/https) markdown image links are left untouched.
    """
    def _md_repl(m: "re.Match[str]") -> str:
        alt = (m.group("alt") or "").strip()
        return f"[IMAGE: {alt}]" if alt else "[IMAGE]"

    md_b64 = re.compile(
        r"!\[(?P<alt>[^\]]*)\]\(\s*data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)"
    )
    out = md_b64.sub(_md_repl, text)
    out = re.sub(r"\(\s*data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)", "[IMAGE]", out)
    out = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[IMAGE]", out)
    return out


def store_full_text(url: str, content: str, cache_dir: Path) -> Optional[str]:
    """Write the full extracted page to ``cache_dir``; return its absolute path.

    Best-effort storage — truncated content is still returned to the model
    even if the write fails. The stored copy is bounded so a pathologically
    large page cannot write unbounded bytes to disk.
    """
    try:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        host = (urlsplit(url).hostname or "page").replace(":", "_")
        slug = re.sub(r"[^A-Za-z0-9._-]", "-", host)[:60].strip("-") or "page"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        path = cache_dir / f"{slug}-{digest}.md"
        if len(content) > MAX_STORED_TEXT_CHARS:
            content = (
                content[:MAX_STORED_TEXT_CHARS]
                + f"\n\n[... stored copy truncated at {MAX_STORED_TEXT_CHARS:,} chars "
                f"of {len(content):,}; re-extract a more specific URL for the rest ...]"
            )
        path.write_text(content, encoding="utf-8")
        return str(path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to store full web_extract text for %s: %s", url, exc)
        return None


def truncate_with_footer(
    content: str,
    url: str,
    char_limit: int,
    cache_dir: Path,
) -> tuple[str, bool]:
    """Return ``(model_text, was_truncated)`` for one page's clean content.

    Pages at or under ``char_limit`` are returned whole. Larger pages get a
    head+tail window (~75% head / ~25% tail) cut on a markdown line boundary
    where possible, plus an explicit footer telling the model exactly how
    much it is seeing, where the full text is stored, and which read_file
    call pages in the omitted middle.
    """
    if len(content) <= char_limit:
        return content, False

    head_budget = int(char_limit * 0.75)
    tail_budget = char_limit - head_budget

    head = content[:head_budget]
    tail = content[-tail_budget:]
    nl = head.rfind("\n")
    if nl > head_budget * 0.5:
        head = head[:nl]
    nl = tail.find("\n")
    if 0 <= nl < tail_budget * 0.5:
        tail = tail[nl + 1:]

    total = len(content)
    stored_path = store_full_text(url, content, cache_dir)

    footer_lines = [
        "",
        "─" * 8 + " [TRUNCATED] " + "─" * 8,
        f"Showing {len(head):,} chars (head) + {len(tail):,} chars (tail) "
        f"of {total:,} total clean characters.",
    ]
    if stored_path:
        middle_start_line = head.count("\n") + 2
        footer_lines.append(f"Full text saved to: {stored_path}")
        footer_lines.append(
            f'To read the omitted middle: read_file path="{stored_path}" '
            f"offset={middle_start_line} limit=200  (the file is the complete page; "
            f"raise/lower offset to page through it)."
        )
    else:
        footer_lines.append(
            "Full text could not be stored; re-run web_extract_pages on a more "
            "specific URL or use browser_navigate for the complete page."
        )
    footer_lines.append("─" * 29)

    model_text = head + "\n\n[... middle omitted — see footer ...]\n\n" + tail
    model_text += "\n" + "\n".join(footer_lines)
    return model_text, True
