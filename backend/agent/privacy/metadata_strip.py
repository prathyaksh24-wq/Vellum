"""Strip Obsidian metadata before sending text across boundaries."""

import hashlib
import re


FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.S)
TAG_RE = re.compile(r"(?<!\w)#[A-Za-z0-9_/-]+")


def strip_metadata(text: str) -> str:
    value = FRONTMATTER_RE.sub("", text or "")
    return TAG_RE.sub("", value).strip()


def strip_obsidian_metadata(text: str, source_path: str | None = None) -> str:
    return strip_metadata(text)


def safe_chunk_id(source_path: str, chunk_index: int) -> str:
    raw = f"{source_path}:{chunk_index}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
