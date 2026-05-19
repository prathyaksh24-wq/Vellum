"""Handle-agnostic X ingest core.

Persists Apify items into Vault/Library/X/<handle>/ with per-handle filter
profile and within/cross-handle text-hash dedup.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten
from typing import Any


X_EPOCH_MS = 1288834974657

TOPIC_RULES: dict[str, tuple[str, ...]] = {
    "ai-and-software": ("ai", "agent", "coding", "computer", "model", "software", "vibe"),
    "business-and-startups": ("business", "capital", "career", "company", "founder", "market", "product", "startup"),
    "mind-and-attention": ("attention", "belief", "brain", "desire", "ego", "mind", "peace", "think"),
    "wealth-and-incentives": ("bitcoin", "cost", "crypto", "incentive", "money", "price", "wealth"),
    "taste-and-creativity": ("art", "create", "creativity", "design", "taste", "write"),
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
        normalized = " ".join(self.text.lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    @property
    def topics(self) -> list[str]:
        lowered = self.text.lower()
        matches = [
            topic for topic, keywords in TOPIC_RULES.items()
            if any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in keywords)
        ]
        return matches or ["general"]


@dataclass
class IngestResult:
    fetched: int
    filtered: int
    added: int
    total: int


def _load_sibling(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


def wiki_link(note_path: str, label: str) -> str:
    return f"[[{note_path}|{label}]]"


def tweet_from_apify_item(item: dict, *, handle_name: str, source_label: str = "Apify apidojo/tweet-scraper") -> Tweet | None:
    status_id = (
        item.get("id")
        or item.get("tweetId")
        or item.get("tweet_id")
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

    x_url = item.get("url") or item.get("tweetUrl") or f"https://x.com/{handle_name}/status/{status_id}"

    return Tweet(
        status_id=status_id,
        posted_utc=posted_utc,
        text=text,
        x_url=x_url,
        mirror_url=x_url,
        source=source_label,
    )


def canonical_note_path(base: Path, tweet: Tweet) -> Path:
    posted = datetime.fromisoformat(tweet.posted_utc)
    filename = f"{posted:%Y-%m-%d}-{tweet.status_id}-{slugify(tweet.text)}.md"
    return base / "tweets" / f"{posted:%Y}" / filename


def relative_note_path(base: Path, tweet: Tweet, vault_root: Path) -> str:
    return canonical_note_path(base, tweet).relative_to(vault_root).as_posix()


def read_existing_manifest(base: Path) -> dict[str, dict]:
    manifest = base / "tweets.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return {str(item["status_id"]): item for item in data if item.get("status_id")}
        except json.JSONDecodeError:
            return {}
    return {}


def tweet_from_record(record: dict, *, source_label: str) -> Tweet | None:
    try:
        return Tweet(
            status_id=str(record["status_id"]),
            posted_utc=str(record["posted_utc"]),
            text=str(record["text"]).strip(),
            x_url=str(record.get("x_url") or ""),
            mirror_url=str(record.get("mirror_url") or ""),
            source=str(record.get("source") or source_label),
        )
    except KeyError:
        return None


def note_markdown(tweet: Tweet, captured_utc: str, handle_name: str) -> str:
    posted = datetime.fromisoformat(tweet.posted_utc)
    title = shorten(tweet.text.replace("\n", " "), width=80, placeholder="...")
    topics_yaml = "\n".join(f"  - {t}" for t in tweet.topics)
    tags_yaml = "\n".join([
        "  - x",
        f"  - {handle_name}",
        "  - tweet",
        *[f"  - topic/{t}" for t in tweet.topics],
    ])
    return f"""---
type: x_tweet
author: {handle_name}
handle: {handle_name}
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
"""


def write_tweet_note(base: Path, tweet: Tweet, captured_utc: str, handle_name: str) -> Path:
    path = canonical_note_path(base, tweet)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_markdown(tweet, captured_utc, handle_name), encoding="utf-8", newline="\n")
    return path


def record_for(tweet: Tweet, base: Path, vault_root: Path) -> dict:
    return {
        "status_id": tweet.status_id,
        "posted_utc": tweet.posted_utc,
        "text": tweet.text,
        "text_hash": tweet.text_hash,
        "topics": tweet.topics,
        "x_url": tweet.x_url,
        "mirror_url": tweet.mirror_url,
        "source": tweet.source,
        "note_path": relative_note_path(base, tweet, vault_root),
    }


def write_manifests(base: Path, records: list[dict]) -> None:
    (base / "tweets.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with (base / "tweets.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_latest(base: Path, records: list[dict], captured_utc: str, handle_name: str, limit: int = 50) -> None:
    lines = [
        "---",
        "type: x_latest",
        f"author: {handle_name}",
        f"handle: {handle_name}",
        f"captured_utc: {yaml_quote(captured_utc)}",
        f"tweet_count: {min(limit, len(records))}",
        "tags:",
        "  - x",
        f"  - {handle_name}",
        "  - latest",
        "---",
        "",
        f"# @{handle_name} - Latest {min(limit, len(records))} Tweets",
        "",
    ]
    for index, record in enumerate(records[:limit], 1):
        posted = datetime.fromisoformat(record["posted_utc"])
        title = shorten(record["text"].replace("\n", " "), width=92, placeholder="...")
        note_link = wiki_link(record["note_path"], title or record["status_id"])
        lines.extend([
            f"## {index:02d}. {posted:%Y-%m-%d}",
            "",
            record["text"],
            "",
            f"- Note: {note_link}",
            f"- X: {record['x_url']}",
            "",
        ])
    (base / "latest-50.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_topic_indexes(base: Path, records: list[dict], handle_name: str) -> None:
    topics_dir = base / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    by_topic: dict[str, list[dict]] = {}
    for record in records:
        for t in record.get("topics", ["general"]):
            by_topic.setdefault(t, []).append(record)
    for topic, topic_records in sorted(by_topic.items()):
        lines = [
            "---",
            "type: x_topic_index",
            f"author: {handle_name}",
            f"topic: {topic}",
            f"tweet_count: {len(topic_records)}",
            "tags:",
            "  - x",
            f"  - {handle_name}",
            f"  - topic/{topic}",
            "---",
            "",
            f"# @{handle_name} - {topic.replace('-', ' ').title()}",
            "",
        ]
        for record in topic_records:
            posted = datetime.fromisoformat(record["posted_utc"])
            label = shorten(record["text"].replace("\n", " "), width=96, placeholder="...")
            lines.append(f"- {posted:%Y-%m-%d}: {wiki_link(record['note_path'], label)}")
        (topics_dir / f"{topic}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_year_indexes(base: Path, records: list[dict], handle_name: str) -> None:
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
            f"author: {handle_name}",
            f"year: {year}",
            f"tweet_count: {len(year_records)}",
            "tags:",
            "  - x",
            f"  - {handle_name}",
            f"  - year/{year}",
            "---",
            "",
            f"# @{handle_name} - {year}",
            "",
        ]
        for record in year_records:
            posted = datetime.fromisoformat(record["posted_utc"])
            label = shorten(record["text"].replace("\n", " "), width=96, placeholder="...")
            lines.append(f"- {posted:%Y-%m-%d}: {wiki_link(record['note_path'], label)}")
        (years_dir / f"{year}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_agent_guide(base: Path, records: list[dict], handle_name: str) -> None:
    topic_counts: dict[str, int] = {}
    for record in records:
        for t in record.get("topics", ["general"]):
            topic_counts[t] = topic_counts.get(t, 0) + 1
    topic_lines = [f"- [[Library/X/{handle_name}/topics/{t}|{t}]]: {c}" for t, c in sorted(topic_counts.items())]
    lines = [
        "---",
        "type: x_agent_guide",
        f"author: {handle_name}",
        f"tweet_count: {len(records)}",
        "tags:",
        "  - x",
        f"  - {handle_name}",
        "  - agent-memory",
        "---",
        "",
        f"# @{handle_name} Agent Guide",
        "",
        "## Retrieval Contract",
        "",
        "- Use `tweets.jsonl` for precise lookup by `status_id`, topic, date, or text search.",
        "- Use `latest-50.md` when freshness matters.",
        "- Use `topics/` when the user asks for patterns, tone, beliefs, or examples by theme.",
        "",
        "## Topic Map",
        "",
        *topic_lines,
        "",
    ]
    (base / "agent-guide.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_root_index(base: Path, records: list[dict], captured_utc: str, handle_name: str) -> None:
    years = sorted({datetime.fromisoformat(r["posted_utc"]).strftime("%Y") for r in records}, reverse=True)
    topics = sorted({t for r in records for t in r.get("topics", ["general"])})
    lines = [
        "---",
        "type: x_collection",
        f"author: {handle_name}",
        f"handle: {handle_name}",
        f"captured_utc: {yaml_quote(captured_utc)}",
        f"tweet_count: {len(records)}",
        "tags:",
        "  - x",
        f"  - {handle_name}",
        "---",
        "",
        f"# @{handle_name} X Archive",
        "",
        "## Start Here",
        "",
        f"- [[Library/X/{handle_name}/latest-50|Latest 50]]",
        f"- [[Library/X/{handle_name}/agent-guide|Agent Guide]]",
        "- `tweets.jsonl` for structured retrieval",
        "",
        "## Topic Indexes",
        "",
        *[f"- [[Library/X/{handle_name}/topics/{t}|{t}]]" for t in topics],
        "",
        "## Year Indexes",
        "",
        *[f"- [[Library/X/{handle_name}/years/{y}|{y}]]" for y in years],
        "",
        "## Sources",
        "",
        f"- https://x.com/{handle_name}",
        "",
    ]
    (base / "_index.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_state(base: Path, fetched_count: int, added_count: int, total_count: int, handle_name: str) -> None:
    state_dir = base / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "handle": handle_name,
        "fetched_count": fetched_count,
        "added_count": added_count,
        "total_count": total_count,
    }
    (state_dir / "naval_x_scraper_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def ingest(*, handle, vault_root: Path, items: list[dict]) -> IngestResult:
    """Filter, dedup, persist. `handle` is a HandleConfig instance."""
    fp = _load_sibling("filter_profiles")
    dedup = _load_sibling("x_dedup")
    hc = _load_sibling("handle_config")

    base = hc.vault_base_for(handle, vault_root)
    base.mkdir(parents=True, exist_ok=True)

    existing_records = read_existing_manifest(base)
    tweets_by_id: dict[str, Tweet] = {}
    for status_id, record in existing_records.items():
        t = tweet_from_record(record, source_label=handle.source_label)
        if t:
            tweets_by_id[status_id] = t

    within_hashes = {t.text_hash for t in tweets_by_id.values()}
    sibling_handles = hc.handles_in_dedup_group(handle.dedup_group)
    cross_hashes = dedup.collect_group_text_hashes(
        handles=sibling_handles, vault_root=vault_root, exclude_name=handle.name
    )
    forbidden = within_hashes | cross_hashes

    fetched = len(items)
    filtered = 0
    added = 0
    for item in items:
        if not fp.accepts(handle.filter_profile, item):
            filtered += 1
            continue
        tweet = tweet_from_apify_item(item, handle_name=handle.name, source_label=handle.source_label)
        if not tweet:
            filtered += 1
            continue
        if tweet.text_hash in forbidden:
            continue
        if tweet.status_id in tweets_by_id:
            continue
        tweets_by_id[tweet.status_id] = tweet
        forbidden.add(tweet.text_hash)
        added += 1

    tweets = sorted(tweets_by_id.values(), key=lambda t: t.posted_utc, reverse=True)
    captured_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for tweet in tweets:
        write_tweet_note(base, tweet, captured_utc, handle.name)

    records = [record_for(tweet, base, vault_root) for tweet in tweets]
    write_manifests(base, records)
    write_latest(base, records, captured_utc, handle.name)
    write_topic_indexes(base, records, handle.name)
    write_year_indexes(base, records, handle.name)
    write_agent_guide(base, records, handle.name)
    write_root_index(base, records, captured_utc, handle.name)
    write_state(base, fetched_count=fetched, added_count=added, total_count=len(records), handle_name=handle.name)

    return IngestResult(fetched=fetched, filtered=filtered, added=added, total=len(records))
