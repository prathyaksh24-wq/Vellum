from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request

from agent.config import get_settings

GOOGLE_RESULT_SEPARATOR = "\n\n---\n\n"


class SerpApiClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        log_path: Path | str | None = None,
        timeout_seconds: int = 45,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.serpapi_api_key
        self.base_url = base_url or settings.serpapi_base_url
        self.log_path = Path(log_path if log_path is not None else settings.serpapi_log_path)
        self.timeout_seconds = timeout_seconds

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("SERPAPI_API_KEY is not configured.")

        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        request_params = {**clean_params, "api_key": self.api_key}
        url = f"{self.base_url}?{urllib.parse.urlencode(request_params, doseq=True)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self._log_search(params=clean_params, payload=payload)
        return payload

    def google_search_text(self, query: str, *, num: int = 5) -> str:
        payload = self.search({"engine": "google", "q": query, "num": num})
        return _google_payload_text(payload, num=num)

    def fresh_google_search_text(self, query: str, *, num: int = 5) -> str:
        for engine in ("google_ai_mode", "google_light", "google"):
            payload = self.search({"engine": engine, "q": query, "num": num})
            text = _google_payload_text(payload, num=num)
            if text != "No web results found.":
                return text
        return "No web results found."

    def fresh_google_search(self, query: str, *, num: int = 5, min_sources: int = 3) -> dict[str, Any]:
        text = ""
        facts: list[str] = []
        answer_mode = ""
        sources: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        engines_used: list[str] = []
        for engine in ("google_ai_mode", "google_light", "google"):
            payload = self.search({"engine": engine, "q": query, "num": num})
            engines_used.append(engine)
            normalized = _google_payload_normalized(payload, num=num)
            candidate_text = normalized["text"]
            if not text and candidate_text != "No web results found.":
                text = candidate_text
            if not facts and normalized["facts"]:
                facts = list(normalized["facts"])
                answer_mode = str(normalized.get("answer_mode") or "")
            for source in normalized["sources"]:
                url = source.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                sources.append({**source, "engine": engine})
            if text and len(sources) >= min_sources:
                break
        return {
            "text": text or "No web results found.",
            "facts": facts,
            "answer_mode": answer_mode or "fallback",
            "sources": sources,
            "engines": engines_used,
        }

    def youtube_search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        payload = self.search({"engine": "youtube", "search_query": query})
        results = payload.get("video_results") or payload.get("results") or []
        return [_normalize_youtube_video(item) for item in results[:max_results] if isinstance(item, dict)]

    def youtube_video(self, video_id: str) -> dict[str, Any]:
        return self.search({"engine": "youtube_video", "v": video_id})

    def youtube_transcript(self, video_id: str) -> dict[str, Any]:
        payload = self.search({"engine": "youtube_video_transcript", "v": video_id})
        segments = payload.get("transcript") or payload.get("transcript_results") or []
        text = "\n".join(
            _string(segment.get("text") or segment.get("snippet"))
            for segment in segments
            if isinstance(segment, dict) and (segment.get("text") or segment.get("snippet"))
        ).strip()
        return {
            "video_id": video_id,
            "transcript": text,
            "path": "",
            "segments": segments if isinstance(segments, list) else [],
        }

    def _log_search(self, *, params: dict[str, Any], payload: dict[str, Any]) -> None:
        metadata = payload.get("search_metadata") if isinstance(payload, dict) else {}
        record = {
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "engine": params.get("engine", "google"),
            "params": dict(params),
            "search_id": metadata.get("id") if isinstance(metadata, dict) else "",
            "status": metadata.get("status") if isinstance(metadata, dict) else "",
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


def _normalize_youtube_video(item: dict[str, Any]) -> dict[str, Any]:
    url = _string(item.get("link") or item.get("url"))
    channel = item.get("channel")
    channel_name = channel.get("name") if isinstance(channel, dict) else channel
    video_id = _string(item.get("video_id") or item.get("videoId") or _video_id_from_url(url))
    return {
        "videoId": video_id,
        "title": _string(item.get("title")),
        "url": url or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""),
        "channelName": _string(channel_name),
        "publishedAt": _string(item.get("published_date") or item.get("publishedAt") or item.get("date")),
        "description": _string(item.get("description") or item.get("snippet")),
    }


def _google_payload_text(payload: dict[str, Any], *, num: int) -> str:
    normalized = _google_payload_normalized(payload, num=num)
    return normalized["text"]


def _google_payload_normalized(payload: dict[str, Any], *, num: int) -> dict[str, Any]:
    blocks: list[str] = []
    full_answer = _serp_full_answer(payload)
    if full_answer["answer"]:
        facts = [full_answer["answer"]]
        if _needs_structured_supplement(full_answer["answer"]):
            facts.extend(_structured_source_facts(payload, num=num))
        return {
            "text": GOOGLE_RESULT_SEPARATOR.join(facts),
            "facts": facts,
            "sources": _google_payload_sources(payload, num=num),
            "answer_mode": full_answer["mode"],
        }

    facts = _compact_facts(payload, num=num)
    blocks.extend(facts)

    if facts:
        for item in _search_items(payload, include_organic=False)[:num]:
            if not isinstance(item, dict):
                continue
            title = _string(item.get("title") or item.get("source") or "Search result")
            link = _string(item.get("link") or item.get("url"))
            snippet = _string(item.get("snippet") or item.get("description"))
            if not link:
                continue
            blocks.append(f"**{title}**\n{snippet}\n{link}")

    if not facts:
        text_blocks = payload.get("text_blocks")
        if isinstance(text_blocks, list):
            for block in text_blocks[:num]:
                text = _string(block.get("text") if isinstance(block, dict) else block)
                if text:
                    blocks.append(text)

        for item in _search_items(payload, include_organic=True)[:num]:
            if not isinstance(item, dict):
                continue
            title = _string(item.get("title") or item.get("source") or "Search result")
            link = _string(item.get("link") or item.get("url"))
            snippet = _string(item.get("snippet") or item.get("description"))
            if not link:
                continue
            blocks.append(f"**{title}**\n{snippet}\n{link}")

    return {
        "text": GOOGLE_RESULT_SEPARATOR.join(block for block in blocks if block.strip()) or "No web results found.",
        "facts": facts,
        "sources": _google_payload_sources(payload, num=num),
        "answer_mode": "compact_facts" if facts else "fallback",
    }


def _google_payload_sources(payload: dict[str, Any], *, num: int) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for item in _source_items(payload, num=num):
        if not isinstance(item, dict):
            continue
        url = _string(item.get("link") or item.get("url"))
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc[4:] if parsed.netloc.startswith("www.") else parsed.netloc
        provider_label = _string(item.get("source") or item.get("displayed_link") or domain)
        favicon_url = _string(item.get("favicon") or item.get("source_icon") or item.get("thumbnail") or item.get("logo"))
        sources.append(
            {
                "title": _string(item.get("title") or provider_label or domain or "Search result"),
                "url": url,
                "snippet": _string(item.get("snippet") or item.get("description"))[:700],
                "domain": domain,
                "favicon_url": favicon_url,
                "provider_label": provider_label or domain,
            }
        )
    return sources


def _serp_full_answer(payload: dict[str, Any]) -> dict[str, str]:
    markdown = _string(payload.get("reconstructed_markdown"))
    if markdown.strip():
        return {"mode": "full_markdown_answer", "answer": markdown}

    text_blocks = payload.get("text_blocks")
    if isinstance(text_blocks, list) and text_blocks:
        answer = _text_blocks_to_markdown(text_blocks).strip()
        if answer:
            return {"mode": "structured_blocks", "answer": answer}

    return {"mode": "", "answer": ""}


def _text_blocks_to_markdown(blocks: list[Any], *, indent: int = 0) -> str:
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            text = _string(block).strip()
            if text:
                parts.append(("  " * indent) + text)
            continue
        block_type = _string(block.get("type")).casefold()
        snippet = _string(block.get("snippet") or block.get("text")).strip()

        nested_blocks = block.get("text_blocks")
        if isinstance(nested_blocks, list):
            nested = _text_blocks_to_markdown(nested_blocks, indent=indent).strip()
            if nested:
                parts.append(nested)
            continue

        if block_type == "heading":
            if snippet:
                level = min(6, 2 + indent)
                parts.append(f"{'#' * level} {snippet}")
            continue

        if block_type == "list":
            lines = _list_block_to_markdown(block.get("list"), indent=indent)
            if lines:
                parts.append(lines)
            continue

        if block_type == "table":
            table = _table_block_to_markdown(block)
            if table:
                parts.append(table)
            continue

        if snippet:
            parts.append(("  " * indent) + snippet)
    return "\n\n".join(part for part in parts if part.strip())


def _list_block_to_markdown(items: Any, *, indent: int) -> str:
    if not isinstance(items, list):
        return ""
    lines: list[str] = []
    prefix = "  " * indent
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("text_blocks"), list):
            nested = _text_blocks_to_markdown(item["text_blocks"], indent=indent).strip()
            if nested:
                lines.append(nested)
            continue
        text = ""
        if isinstance(item, dict):
            text = _string(item.get("snippet") or item.get("text")).strip()
        else:
            text = _string(item).strip()
        if text:
            lines.append(f"{prefix}- {text}")
    return "\n".join(lines)


def _table_block_to_markdown(block: dict[str, Any]) -> str:
    rows = block.get("table")
    if not isinstance(rows, list) or not rows:
        detailed = block.get("detailed")
        if isinstance(detailed, list):
            rows = [
                [
                    _string(cell.get("snippet") if isinstance(cell, dict) else cell)
                    for cell in row
                ]
                for row in detailed
                if isinstance(row, list)
            ]
    clean_rows = [
        [_string(cell).replace("\n", " ").strip() for cell in row]
        for row in (rows or [])
        if isinstance(row, list)
    ]
    if not clean_rows:
        return ""
    width = max(len(row) for row in clean_rows)
    clean_rows = [row + [""] * (width - len(row)) for row in clean_rows]
    header = clean_rows[0]
    separator = ["---"] * width
    body = clean_rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _source_items(payload: dict[str, Any], *, num: int) -> list[Any]:
    primary = _primary_source_items(payload, num=num)
    if primary:
        return primary
    return _search_items(payload, include_organic=True)


def _primary_source_items(payload: dict[str, Any], *, num: int) -> list[Any]:
    items: list[Any] = []
    answer_box = payload.get("answer_box")
    if isinstance(answer_box, dict) and (answer_box.get("link") or answer_box.get("url")):
        items.append(
            {
                "title": answer_box.get("title") or answer_box.get("answer") or "Answer box",
                "link": answer_box.get("link") or answer_box.get("url"),
                "snippet": answer_box.get("snippet") or answer_box.get("answer") or answer_box.get("description"),
                "source": answer_box.get("source"),
            }
        )

    sports_results = payload.get("sports_results")
    if isinstance(sports_results, dict):
        for item in _sports_items(sports_results)[:num]:
            link = item.get("link") or item.get("url")
            if link:
                items.append(item)

    video_results = payload.get("video_results")
    if isinstance(video_results, list):
        items.extend(video_results[:num])

    for key in ("references", "top_stories", "news_results"):
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(value[:num])
    return items


def _search_items(payload: dict[str, Any], *, include_organic: bool) -> list[Any]:
    items: list[Any] = []
    keys = ["references", "top_stories", "news_results"]
    if include_organic:
        keys.append("organic_results")
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(value)
    return items


def _compact_facts(payload: dict[str, Any], *, num: int) -> list[str]:
    facts: list[str] = []
    answer = _string(payload.get("ai_answer") or payload.get("answer") or payload.get("summary"))
    if answer:
        facts.append(answer)

    answer_box = payload.get("answer_box")
    if isinstance(answer_box, dict):
        facts.extend(_answer_box_facts(answer_box))

    sports_results = payload.get("sports_results")
    if isinstance(sports_results, dict):
        sports_facts = _compact_sports_results(sports_results, num=num)
        facts.extend(sports_facts)

    video_results = payload.get("video_results")
    if isinstance(video_results, list):
        for item in video_results[:num]:
            if not isinstance(item, dict):
                continue
            fact = _compact_video_result(item)
            if fact:
                facts.append(fact)
    return _dedupe_text(facts)


def _compact_sports_results(results: dict[str, Any], *, num: int) -> list[str]:
    facts: list[str] = []
    header = _compact_mapping(
        "sports_results",
        results,
        ("league", "title", "season", "status", "date", "venue", "location"),
    )
    if header:
        facts.append(header)

    for item in _sports_items(results)[:num]:
        fact = _compact_mapping(
            "sports_results",
            item,
            (
                "rank",
                "position",
                "team",
                "name",
                "player",
                "athlete",
                "country",
                "tournament",
                "event",
                "title",
                "date",
                "time",
                "score",
                "home_team",
                "away_team",
                "home_score",
                "away_score",
                "venue",
                "location",
                "points",
                "wins",
                "losses",
                "goals",
                "stats",
                "link",
                "url",
            ),
        )
        if fact:
            facts.append(fact)
    return facts


def _answer_box_facts(answer_box: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    fact = _compact_mapping(
        "answer_box",
        answer_box,
        ("title", "answer", "snippet", "description", "date", "source", "link", "url"),
    )
    if fact:
        facts.append(fact)

    contents = answer_box.get("contents")
    if isinstance(contents, dict):
        table = contents.get("table")
        if isinstance(table, list):
            markdown = _table_block_to_markdown({"table": table})
            if markdown:
                title = _string(answer_box.get("title") or answer_box.get("description") or "Answer box table")
                link = _string(answer_box.get("link") or answer_box.get("url"))
                parts = [f"### {title}", markdown]
                if link:
                    parts.append(link)
                facts.append("\n\n".join(parts))
    return facts


def _needs_structured_supplement(answer: str) -> bool:
    lowered = answer.casefold()
    if re.search(r"(?m)^\|.+\|$", answer):
        return False
    markers = (
        "calendar",
        "schedule",
        "standings",
        "lineup",
        "lineups",
        "table",
        "detailed below",
        "details below",
    )
    return any(marker in lowered for marker in markers)


def _structured_source_facts(payload: dict[str, Any], *, num: int) -> list[str]:
    facts: list[str] = []
    for item in _source_items(payload, num=num)[:num]:
        if not isinstance(item, dict):
            continue
        snippet = _string(item.get("snippet") or item.get("description"))
        table = _table_from_snippet(snippet)
        if not table:
            continue
        title = _string(item.get("title") or item.get("source") or "Source table")
        link = _string(item.get("link") or item.get("url"))
        parts = [f"### {title}", table]
        if link:
            parts.append(link)
        facts.append("\n\n".join(parts))
    return _dedupe_text(facts)


def _table_from_snippet(snippet: str) -> str:
    if "Table_content:" not in snippet:
        return ""
    table = snippet.split("Table_content:", 1)[1].strip()
    table = re.split(r"\s(?:[A-Z][A-Za-z_ ]{2,}:)\s", table, maxsplit=1)[0].strip()
    table = (
        table.replace("\\|", "|")
        .replace("\\-", "-")
        .replace("\\_", "_")
        .replace("\\(", "(")
        .replace("\\)", ")")
    )
    normalized = _normalize_inline_markdown_table(table)
    if normalized:
        return normalized
    return table if re.search(r"(?m)^\|.+\|", table) else ""


def _normalize_inline_markdown_table(table: str) -> str:
    if "\n" in table:
        return table
    cells = [cell.strip() for cell in table.split("|") if cell.strip()]
    first_separator = next(
        (
            index
            for index, cell in enumerate(cells)
            if cell and not cell.replace(":", "").replace("-", "").strip()
        ),
        -1,
    )
    if first_separator <= 0:
        return ""
    width = first_separator
    if len(cells) < width * 2:
        return ""
    rows = [cells[index : index + width] for index in range(0, len(cells), width)]
    rows = [row + [""] * (width - len(row)) for row in rows if row]
    if len(rows) < 2:
        return ""
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _sports_items(results: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("games", "game_spotlight", "rankings", "standings", "results", "fixtures", "matches"):
        value = results.get(key)
        if isinstance(value, dict):
            items.append(value)
        elif isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    return items


def _compact_video_result(item: dict[str, Any]) -> str:
    channel = item.get("channel")
    channel_name = channel.get("name") if isinstance(channel, dict) else channel
    parts = [
        _kv("title", item.get("title")),
        _kv("channel", channel_name),
        _kv("date", item.get("published_date") or item.get("publishedAt") or item.get("date")),
        _kv("link", item.get("link") or item.get("url")),
    ]
    joined = " | ".join(part for part in parts if part)
    return f"video_results: {joined}" if joined else ""


def _compact_mapping(label: str, data: dict[str, Any], keys: tuple[str, ...]) -> str:
    parts = [_kv(key, data.get(key)) for key in keys]
    joined = " | ".join(part for part in parts if part)
    return f"{label}: {joined}" if joined else ""


def _kv(key: str, value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = " ".join(text.split())
    if key == "title":
        return text
    return f"{key}: {text}"


def _dedupe_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _video_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.strip("/")
    query = urllib.parse.parse_qs(parsed.query)
    return query.get("v", [""])[0]


def _string(value: Any) -> str:
    return "" if value is None else str(value)
