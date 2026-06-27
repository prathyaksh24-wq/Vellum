#!/usr/bin/env python3
"""Import a single EPUB book into the Vellum Obsidian vault."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from ebooklib import ITEM_DOCUMENT, epub
from markdownify import markdownify as md


# ---------------- text helpers ----------------

def slugify(text: str, max_words: int | None = None) -> str:
    value = (text or "").lower().strip()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    value = re.sub(r"[\s-]+", "-", value).strip("-")
    if not value:
        return "untitled"
    if max_words:
        value = "-".join(value.split("-")[:max_words]) or "untitled"
    return value


def yaml_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


PAGE_NOISE_PATTERNS = (
    re.compile(r"^\s*loc\.?\s*\d+\s*$", re.I),
    re.compile(r"^\s*location\s*\d+\s*$", re.I),
    re.compile(r"^\s*page\s*\d+\s*$", re.I),
    re.compile(r"^\s*p\.\s*\d+\s*$", re.I),
    re.compile(r"^\s*\d+\s*$"),
)
INLINE_NOISE_PATTERN = re.compile(r"\b(?:loc(?:ation)?\.?|p\.|page)\s*\d+\b", re.I)


# ---------------- HTML cleaning ----------------

def _strip_visual_elements(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(["img", "svg", "figure", "picture", "audio", "video", "iframe", "nav"]):
        tag.decompose()


def _strip_footnote_anchors(soup: BeautifulSoup) -> None:
    for sup in soup.find_all("sup"):
        sup.decompose()
    for anchor in soup.find_all("a"):
        epub_type = (anchor.get("epub:type") or anchor.get("type") or "").lower()
        role = (anchor.get("role") or "").lower()
        cls = " ".join(anchor.get("class") or []).lower()
        if "noteref" in epub_type or "doc-noteref" in role or "footnote" in cls:
            anchor.decompose()


def _handle_footnote_blocks(soup: BeautifulSoup) -> None:
    for note in soup.find_all(["aside", "div"]):
        epub_type = (note.get("epub:type") or note.get("type") or "").lower()
        role = (note.get("role") or "").lower()
        cls = " ".join(note.get("class") or []).lower()
        is_note = (
            "footnote" in epub_type
            or "doc-footnote" in role
            or "endnote" in epub_type
            or "footnote" in cls
            or "endnote" in cls
        )
        if not is_note:
            continue
        text = note.get_text(" ", strip=True)
        prev = note.find_previous_sibling()
        if 0 < len(text) < 200 and prev is not None and prev.name == "p":
            note.replace_with(soup.new_string(f" ({text})"))
        else:
            note.decompose()


DROPCAP_CLASSES = ("dropcap", "drop-cap", "initial", "firstletter", "first-letter")
WRAPPER_TAGS = {"section", "article", "div", "main", "header", "body", "html"}
HEADING_TAGS = ("h1", "h2", "h3", "h4")
CONTENT_TAGS = ("p", "blockquote", "ul", "ol", "table", "pre", "li")


def _unwrap_dropcap_spans(soup: BeautifulSoup) -> None:
    for span in soup.find_all("span"):
        cls = " ".join(span.get("class") or []).lower()
        if any(k in cls for k in DROPCAP_CLASSES):
            span.unwrap()


def _merge_dropcap_em(soup: BeautifulSoup) -> None:
    """Merge a single-letter <em>/<i> with the immediately following <em>/<i> sibling."""
    for em in list(soup.find_all(["em", "i"])):
        if em.get_text("", strip=True) and len(em.get_text("", strip=True)) != 1:
            continue
        nxt = em.next_sibling
        while isinstance(nxt, str) and not nxt.strip():
            nxt = nxt.next_sibling
        if nxt is not None and getattr(nxt, "name", None) in ("em", "i"):
            for child in list(nxt.contents):
                em.append(child)
            nxt.decompose()


def _pick_chapter_heading(soup: BeautifulSoup) -> str | None:
    """Pick the longest of the leading h1/h2/h3 headings before any substantive prose."""
    body = soup.body or soup
    leading: list[str] = []
    for el in body.find_all(True):
        name = el.name or ""
        if name in WRAPPER_TAGS:
            continue
        if name in HEADING_TAGS:
            text = el.get_text(" ", strip=True)
            if text:
                leading.append(text)
        elif name in CONTENT_TAGS:
            text = el.get_text(" ", strip=True)
            if text:
                break
    if not leading:
        return None
    return max(leading, key=len)


def html_to_clean_markdown(html: str) -> tuple[str, str | None]:
    """Return (cleaned_markdown_body, picked_heading_or_none)."""
    html = re.sub(r"<\?xml[^?]*\?>", "", html, flags=re.IGNORECASE)
    soup = BeautifulSoup(html, "html.parser")
    _strip_visual_elements(soup)
    _strip_footnote_anchors(soup)
    _handle_footnote_blocks(soup)
    _unwrap_dropcap_spans(soup)
    _merge_dropcap_em(soup)
    heading = _pick_chapter_heading(soup)

    markdown = md(str(soup), heading_style="ATX", bullets="-")

    # Strip URL part from any link, keep the visible text (does not touch [[wikilinks]]).
    markdown = re.sub(r"(?<!\[)\[([^\]]*)\]\([^)]*\)", r"\1", markdown)
    markdown = INLINE_NOISE_PATTERN.sub("", markdown)

    cleaned: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if any(p.match(stripped) for p in PAGE_NOISE_PATTERNS):
            continue
        cleaned.append(stripped)

    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, heading


# ---------------- EPUB parsing ----------------

def get_book_metadata(book: epub.EpubBook) -> tuple[str, str]:
    title_meta = book.get_metadata("DC", "title")
    creator_meta = book.get_metadata("DC", "creator")
    title = title_meta[0][0].strip() if title_meta else ""
    author = creator_meta[0][0].strip() if creator_meta else ""
    return title, author


def get_spine_items(book: epub.EpubBook):
    for entry in book.spine:
        idref = entry[0] if isinstance(entry, (tuple, list)) else entry
        item = book.get_item_with_id(idref)
        if item is not None and item.get_type() == ITEM_DOCUMENT:
            yield item


# ---------------- writing ----------------

def write_chapter(
    folder: Path,
    chapter_number: int,
    chapter_slug: str,
    folder_slug: str,
    author: str,
    chapter_label: str,
    body: str,
) -> Path:
    fm = (
        f"---\n"
        f"type: book-chapter\n"
        f'book: "[[{folder_slug}/_book]]"\n'
        f'author: "{yaml_escape(author)}"\n'
        f'chapter: "{yaml_escape(chapter_label)}"\n'
        f"chapter_number: {chapter_number}\n"
        f"---\n\n"
    )
    path = folder / f"{chapter_number:02d}-{chapter_slug}.md"
    path.write_text(fm + body + "\n", encoding="utf-8")
    return path


def write_book_card(
    folder: Path,
    title: str,
    author: str,
    chapters: list[tuple[int, str]],
) -> Path:
    today = date.today().isoformat()
    chapter_lines = "\n".join(f"- [[{idx:02d}-{slug}]]" for idx, slug in chapters)
    content = (
        f"---\n"
        f"type: book-card\n"
        f'title: "{yaml_escape(title)}"\n'
        f'author: "{yaml_escape(author)}"\n'
        f"imported: {today}\n"
        f"tags: []\n"
        f"---\n\n"
        f"# {title}\n"
        f"## by {author}\n\n"
        f"*— write one or two lines here about why this book matters to you. —*\n\n"
        f"## chapters\n\n"
        f"{chapter_lines}\n"
    )
    path = folder / "_book.md"
    path.write_text(content, encoding="utf-8")
    return path


INDEX_HEADER = (
    "---\n"
    "type: book-index\n"
    "---\n\n"
    "# Library\n\n"
    "A list of books read.\n\n"
    "## books\n\n"
)


def update_index(books_dir: Path, folder_slug: str, title: str, author: str) -> bool:
    index_path = books_dir / "_index.md"
    line = f"- [[{folder_slug}/_book|{title}]] · *{author}*"
    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
        if f"{folder_slug}/_book" in existing:
            return False
        if not existing.endswith("\n"):
            existing += "\n"
        index_path.write_text(existing + line + "\n", encoding="utf-8")
        return True
    index_path.write_text(INDEX_HEADER + line + "\n", encoding="utf-8")
    return True


# ---------------- main ----------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Import an EPUB book into the Vellum Obsidian vault.")
    parser.add_argument("--epub", required=True, help="path to a single .epub file")
    parser.add_argument("--vault", default=None, help="vault path (defaults to OBSIDIAN_VAULT_PATH)")
    parser.add_argument("--title", default=None, help="override extracted title")
    parser.add_argument("--author", default=None, help="override extracted author")
    args = parser.parse_args()

    load_dotenv()
    vault_raw = args.vault or os.getenv("OBSIDIAN_VAULT_PATH", "")
    if not vault_raw:
        print("error: no vault path provided and OBSIDIAN_VAULT_PATH is not set in .env", file=sys.stderr)
        return 1
    vault_path = Path(vault_raw).expanduser().resolve()
    if not vault_path.exists() or not vault_path.is_dir():
        print(f"error: vault path does not exist or is not a directory: {vault_path}", file=sys.stderr)
        return 1

    epub_path = Path(args.epub).expanduser().resolve()
    if not epub_path.exists() or not epub_path.is_file():
        print(f"error: epub file not found: {epub_path}", file=sys.stderr)
        return 1

    print(f"Reading EPUB: {epub_path.name}")
    try:
        book = epub.read_epub(str(epub_path))
    except Exception as exc:
        print(f"error: could not read EPUB: {exc}", file=sys.stderr)
        return 1

    extracted_title, extracted_author = get_book_metadata(book)
    title = (args.title or extracted_title or epub_path.stem).strip() or epub_path.stem
    author = (args.author or extracted_author or "unknown").strip() or "unknown"
    print(f"Title: {title}")
    print(f"Author: {author}")

    folder_slug = f"{slugify(title)}--{slugify(author)}"
    books_dir = vault_path / "Books"
    target = books_dir / folder_slug

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    spine_items = list(get_spine_items(book))
    print(f"Found {len(spine_items)} chapters in spine")

    written: list[tuple[int, str]] = []
    chapter_idx = 0
    for n, item in enumerate(spine_items, start=1):
        try:
            html = item.get_content().decode("utf-8", errors="replace")
        except Exception as exc:
            print(f"Skipping chapter {n}: could not decode ({exc})")
            continue
        body, heading = html_to_clean_markdown(html)
        if len(body) < 200:
            print(f"Skipping chapter {n}: too short (likely front matter)")
            continue
        chapter_idx += 1
        chapter_label = heading or f"Chapter {chapter_idx}"
        chapter_slug = slugify(heading, max_words=6) if heading else f"chapter-{chapter_idx}"
        path = write_chapter(target, chapter_idx, chapter_slug, folder_slug, author, chapter_label, body)
        rel = path.relative_to(vault_path)
        print(f"Writing {rel}")
        written.append((chapter_idx, chapter_slug))

    if not written:
        print("error: no chapters written. EPUB may be empty or all front matter.", file=sys.stderr)
        shutil.rmtree(target, ignore_errors=True)
        return 1

    write_book_card(target, title, author, written)

    if update_index(books_dir, folder_slug, title, author):
        print("Updated Books/_index.md")
    else:
        print("Books/_index.md already lists this book — left untouched")

    print()
    print(f"Done. Open {folder_slug}/_book.md to write your one-line summary.")
    print("Run /reindex when you're ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
