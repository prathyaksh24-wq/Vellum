"""Ingest core: extract, filter, and persist @naval Apify tweet items into the vault."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten


HANDLE = "naval"
X_EPOCH_MS = 1288834974657
APIFY_SOURCE_LABEL = "Apify apidojo/tweet-scraper"
SOURCE_PROFILE_URL = f"https://x.com/{HANDLE}"

TOPIC_RULES: dict[str, tuple[str, ...]] = {
    "ai-and-software": (
        "ai",
        "agent",
        "coding",
        "computer",
        "model",
        "software",
        "vibe",
    ),
    "business-and-startups": (
        "business",
        "capital",
        "career",
        "company",
        "founder",
        "market",
        "product",
        "startup",
    ),
    "mind-and-attention": (
        "attention",
        "belief",
        "brain",
        "desire",
        "ego",
        "mind",
        "peace",
        "think",
    ),
    "wealth-and-incentives": (
        "bitcoin",
        "cost",
        "crypto",
        "incentive",
        "money",
        "price",
        "wealth",
    ),
    "taste-and-creativity": (
        "art",
        "create",
        "creativity",
        "design",
        "taste",
        "write",
    ),
}


@dataclass(frozen=True)
class Tweet:
    status_id: str
    posted_utc: str
    text: str
    x_url: str
    mirror_url: str
    source: str

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    @property
    def topics(self) -> list[str]:
        lowered = self.text.lower()
        matches = [
            topic
            for topic, keywords in TOPIC_RULES.items()
            if any(re.search(rf"\b{re.escape(keyword)}\b", lowered) for keyword in keywords)
        ]
        return matches or ["general"]


def snowflake_datetime(status_id: str) -> datetime:
    timestamp_ms = (int(status_id) >> 22) + X_EPOCH_MS
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)


def status_id_from_url(url: str) -> str | None:
    match = re.search(r"/status/(\d+)", url or "")
    return match.group(1) if match else None


def clean_text(text: str | None) -> str:
    text = (text or "").strip()
    text = re.sub(r"\r\n?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def slugify(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())[:8]
    return "-".join(words) or "tweet"


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def canonical_note_path(base: Path, tweet: Tweet) -> Path:
    posted = datetime.fromisoformat(tweet.posted_utc)
    filename = f"{posted:%Y-%m-%d}-{tweet.status_id}-{slugify(tweet.text)}.md"
    return base / "tweets" / f"{posted:%Y}" / filename


def read_existing_manifest(base: Path) -> dict[str, dict]:
    manifest = base / "naval-tweets.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return {str(item["status_id"]): item for item in data if item.get("status_id")}
        except json.JSONDecodeError:
            return {}

    legacy = base / "naval-50-tweets.json"
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            return {str(item["status_id"]): item for item in data if item.get("status_id")}
        except json.JSONDecodeError:
            return {}

    return {}


def existing_note_paths(base: Path) -> dict[str, list[Path]]:
    paths: dict[str, list[Path]] = {}
    for path in (base / "tweets").glob("**/*.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r'^status_id:\s*"?(\d+)"?\s*$', text, re.MULTILINE)
        if match:
            paths.setdefault(match.group(1), []).append(path)
    return paths


def tweet_from_record(record: dict) -> Tweet | None:
    try:
        return Tweet(
            status_id=str(record["status_id"]),
            posted_utc=str(record["posted_utc"]),
            text=str(record["text"]).strip(),
            x_url=str(record.get("x_url") or f"https://x.com/{HANDLE}/status/{record['status_id']}"),
            mirror_url=str(record.get("mirror_url") or SOURCE_PROFILE_URL),
            source=str(record.get("source") or "Existing vault record"),
        )
    except KeyError:
        return None


def note_markdown(tweet: Tweet, captured_utc: str) -> str:
    posted = datetime.fromisoformat(tweet.posted_utc)
    title = shorten(tweet.text.replace("\n", " "), width=80, placeholder="...")
    topics_yaml = "\n".join(f"  - {topic}" for topic in tweet.topics)
    tags_yaml = "\n".join(["  - x", f"  - {HANDLE}", "  - tweet", *[f"  - topic/{topic}" for topic in tweet.topics]])
    return f"""---
type: x_tweet
author: {HANDLE}
handle: {HANDLE}
status_id: {yaml_quote(tweet.status_id)}
posted_utc: {yaml_quote(tweet.posted_utc)}
captured_utc: {yaml_quote(captured_utc)}
source: {yaml_quote(tweet.source)}
x_url: {yaml_quote(tweet.x_url)}
mirror_url: {yaml_quote(tweet.mirror_url)}
text_hash: {yaml_quote(tweet.text_hash)}
topics:
{topics_yaml}
tags:
{tags_yaml}
---

# {posted:%Y-%m-%d} - {title}

## Tweet

{tweet.text}

## Retrieval

- Status ID: {tweet.status_id}
- Topics: {", ".join(tweet.topics)}
- X: {tweet.x_url}
- Mirror: {tweet.mirror_url}
"""


def write_tweet_note(base: Path, tweet: Tweet, captured_utc: str) -> Path:
    path = canonical_note_path(base, tweet)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_markdown(tweet, captured_utc), encoding="utf-8", newline="\n")
    return path


def normalize_existing_notes(base: Path, tweets_by_id: dict[str, Tweet], captured_utc: str) -> None:
    paths_by_id = existing_note_paths(base)
    for status_id, paths in paths_by_id.items():
        tweet = tweets_by_id.get(status_id)
        if not tweet:
            continue
        canonical = write_tweet_note(base, tweet, captured_utc)
        for path in paths:
            if path.resolve() != canonical.resolve() and path.exists():
                path.unlink()

    for directory in sorted((base / "tweets").glob("**/*"), reverse=True):
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass


def record_for(tweet: Tweet, base: Path) -> dict:
    note_path = canonical_note_path(base, tweet).relative_to(base.parent.parent).as_posix()
    return {
        "status_id": tweet.status_id,
        "posted_utc": tweet.posted_utc,
        "text": tweet.text,
        "text_hash": tweet.text_hash,
        "topics": tweet.topics,
        "x_url": tweet.x_url,
        "mirror_url": tweet.mirror_url,
        "source": tweet.source,
        "note_path": note_path,
    }


def wiki_link(note_path: str, label: str) -> str:
    return f"[[{note_path}|{label}]]"


def write_latest(base: Path, records: list[dict], captured_utc: str, limit: int) -> None:
    lines = [
        "---",
        "type: x_latest",
        f"author: {HANDLE}",
        f"handle: {HANDLE}",
        f"captured_utc: {yaml_quote(captured_utc)}",
        f"tweet_count: {min(limit, len(records))}",
        "tags:",
        "  - x",
        f"  - {HANDLE}",
        "  - latest",
        "---",
        "",
        f"# @{HANDLE} - Latest {min(limit, len(records))} Original Text Tweets",
        "",
    ]
    for index, record in enumerate(records[:limit], 1):
        posted = datetime.fromisoformat(record["posted_utc"])
        title = shorten(record["text"].replace("\n", " "), width=92, placeholder="...")
        lines.extend(
            [
                f"## {index:02d}. {posted:%Y-%m-%d}",
                "",
                record["text"],
                "",
                f"- Note: {wiki_link(record['note_path'], record['status_id'])}",
                f"- X: {record['x_url']}",
                "",
            ]
        )
        if title:
            lines[-4] = f"- Note: {wiki_link(record['note_path'], title)}"

    (base / "latest-50.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_topic_indexes(base: Path, records: list[dict]) -> None:
    topics_dir = base / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    by_topic: dict[str, list[dict]] = {}
    for record in records:
        for topic in record.get("topics", ["general"]):
            by_topic.setdefault(topic, []).append(record)

    for topic, topic_records in sorted(by_topic.items()):
        lines = [
            "---",
            "type: x_topic_index",
            f"author: {HANDLE}",
            f"topic: {topic}",
            f"tweet_count: {len(topic_records)}",
            "tags:",
            "  - x",
            f"  - {HANDLE}",
            f"  - topic/{topic}",
            "---",
            "",
            f"# @{HANDLE} - {topic.replace('-', ' ').title()}",
            "",
        ]
        for record in topic_records:
            posted = datetime.fromisoformat(record["posted_utc"])
            label = shorten(record["text"].replace("\n", " "), width=96, placeholder="...")
            lines.append(f"- {posted:%Y-%m-%d}: {wiki_link(record['note_path'], label)}")
        (topics_dir / f"{topic}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_year_indexes(base: Path, records: list[dict]) -> None:
    years_dir = base / "years"
    years_dir.mkdir(parents=True, exist_ok=True)
    by_year: dict[str, list[dict]] = {}
    for record in records:
        year = datetime.fromisoformat(record["posted_utc"]).strftime("%Y")
        by_year.setdefault(year, []).append(record)

    for year, year_records in sorted(by_year.items(), reverse=True):
        lines = [
            "---",
            "type: x_year_index",
            f"author: {HANDLE}",
            f"year: {year}",
            f"tweet_count: {len(year_records)}",
            "tags:",
            "  - x",
            f"  - {HANDLE}",
            f"  - year/{year}",
            "---",
            "",
            f"# @{HANDLE} - {year}",
            "",
        ]
        for record in year_records:
            posted = datetime.fromisoformat(record["posted_utc"])
            label = shorten(record["text"].replace("\n", " "), width=96, placeholder="...")
            lines.append(f"- {posted:%Y-%m-%d}: {wiki_link(record['note_path'], label)}")
        (years_dir / f"{year}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_agent_guide(base: Path, records: list[dict]) -> None:
    topic_counts: dict[str, int] = {}
    for record in records:
        for topic in record.get("topics", ["general"]):
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    topic_lines = [f"- [[X/{HANDLE}/topics/{topic}|{topic}]]: {count}" for topic, count in sorted(topic_counts.items())]

    lines = [
        "---",
        "type: x_agent_guide",
        f"author: {HANDLE}",
        f"tweet_count: {len(records)}",
        "tags:",
        "  - x",
        f"  - {HANDLE}",
        "  - agent-memory",
        "---",
        "",
        f"# @{HANDLE} Agent Guide",
        "",
        "## Retrieval Contract",
        "",
        "- Use `naval-tweets.jsonl` for precise lookup by `status_id`, topic, date, or text search.",
        "- Use `latest-50.md` when freshness matters.",
        "- Use `topics/` when the user asks for patterns, tone, beliefs, or examples by theme.",
        "- Individual tweet notes are canonical memory atoms; avoid duplicating tweet text elsewhere.",
        "",
        "## Growth Rules",
        "",
        "- De-dupe by `status_id`; never create a second note for the same tweet.",
        "- Store canonical notes by posted year under `tweets/YYYY/`.",
        "- Keep generated indexes link-only where possible so the vault remains readable as it grows.",
        "- Preserve source URLs and timestamps; skip likes, comments, retweets, replies, and engagement metrics.",
        "",
        "## Tone Hints",
        "",
        "- Prefer compact, aphoristic wording when referencing this collection.",
        "- Keep claims sharp and plain; avoid padded explanations unless the user asks for analysis.",
        "- When helping proactively, look for recurring themes: attention, incentives, software, leverage, taste, and agency.",
        "",
        "## Topic Map",
        "",
        *topic_lines,
        "",
    ]
    (base / "agent-guide.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_root_index(base: Path, records: list[dict], captured_utc: str) -> None:
    years = sorted({datetime.fromisoformat(record["posted_utc"]).strftime("%Y") for record in records}, reverse=True)
    topics = sorted({topic for record in records for topic in record.get("topics", ["general"])})
    lines = [
        "---",
        "type: x_collection",
        f"author: {HANDLE}",
        f"handle: {HANDLE}",
        f"captured_utc: {yaml_quote(captured_utc)}",
        f"tweet_count: {len(records)}",
        'criteria: "Original text tweets only; no retweets, replies, likes, comments, or engagement metrics."',
        "tags:",
        "  - x",
        f"  - {HANDLE}",
        "---",
        "",
        f"# @{HANDLE} X Archive",
        "",
        "## Start Here",
        "",
        "- [[X/naval/latest-50|Latest 50]]",
        "- [[X/naval/agent-guide|Agent Guide]]",
        "- `naval-tweets.jsonl` for structured retrieval",
        "",
        "## Topic Indexes",
        "",
        *[f"- [[X/{HANDLE}/topics/{topic}|{topic}]]" for topic in topics],
        "",
        "## Year Indexes",
        "",
        *[f"- [[X/{HANDLE}/years/{year}|{year}]]" for year in years],
        "",
        "## Sources",
        "",
        f"- {SOURCE_PROFILE_URL}",
        "",
    ]
    (base / "_index.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_manifests(base: Path, records: list[dict]) -> None:
    (base / "naval-tweets.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with (base / "naval-tweets.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_state(base: Path, fetched_count: int, added_count: int, total_count: int) -> None:
    state_dir = base / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "handle": HANDLE,
        "fetched_count": fetched_count,
        "added_count": added_count,
        "total_count": total_count,
    }
    (state_dir / "naval_x_scraper_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def tweet_from_apify_item(item: dict) -> Tweet | None:
    """Convert an Apify dataset item to our Tweet dataclass.

    Accepts items shaped by `apidojo/tweet-scraper`. Tolerates field aliases
    (id/tweetId, createdAt/created_at, text/full_text, url/tweetUrl).
    """
    status_id = (
        item.get("id")
        or item.get("tweetId")
        or status_id_from_url(item.get("url") or item.get("tweetUrl") or "")
    )
    if not status_id:
        return None
    status_id = str(status_id)

    text = clean_text(item.get("text") or item.get("full_text"))
    if not text:
        return None

    created_raw = item.get("createdAt") or item.get("created_at")
    if created_raw:
        try:
            iso = created_raw.replace("Z", "+00:00")
            posted_utc = datetime.fromisoformat(iso).astimezone(timezone.utc).isoformat()
        except ValueError:
            posted_utc = snowflake_datetime(status_id).isoformat()
    else:
        posted_utc = snowflake_datetime(status_id).isoformat()

    x_url = item.get("url") or item.get("tweetUrl") or f"https://x.com/{HANDLE}/status/{status_id}"

    return Tweet(
        status_id=status_id,
        posted_utc=posted_utc,
        text=text,
        x_url=x_url,
        mirror_url=x_url,
        source=APIFY_SOURCE_LABEL,
    )


@dataclass
class IngestResult:
    fetched: int
    filtered: int
    added: int
    total: int


def ingest(*, base: Path, items: list[dict]) -> IngestResult:
    """Filter, dedupe, persist. Returns counts."""
    # Lazy import to avoid coupling tests
    import importlib.util as _il
    _spec = _il.spec_from_file_location(
        "aphorism_filter", Path(__file__).parent / "aphorism_filter.py"
    )
    _af = _il.module_from_spec(_spec)
    _spec.loader.exec_module(_af)

    base.mkdir(parents=True, exist_ok=True)
    existing_records = read_existing_manifest(base)
    tweets_by_id: dict[str, Tweet] = {}
    for status_id, record in existing_records.items():
        t = tweet_from_record(record)
        if t:
            tweets_by_id[status_id] = t

    fetched = len(items)
    filtered = 0
    added = 0
    for item in items:
        if not _af.is_aphorism(item):
            filtered += 1
            continue
        tweet = tweet_from_apify_item(item)
        if not tweet:
            filtered += 1
            continue
        if tweet.status_id in tweets_by_id:
            continue
        tweets_by_id[tweet.status_id] = tweet
        added += 1

    tweets = sorted(tweets_by_id.values(), key=lambda t: t.posted_utc, reverse=True)
    captured_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for tweet in tweets:
        write_tweet_note(base, tweet, captured_utc)
    normalize_existing_notes(base, tweets_by_id, captured_utc)

    records = [record_for(tweet, base) for tweet in tweets]
    write_manifests(base, records)
    write_latest(base, records, captured_utc, limit=50)
    write_topic_indexes(base, records)
    write_year_indexes(base, records)
    write_agent_guide(base, records)
    write_root_index(base, records, captured_utc)
    write_state(base, fetched_count=fetched, added_count=added, total_count=len(records))

    return IngestResult(fetched=fetched, filtered=filtered, added=added, total=len(records))
