from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable


STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "been", "before", "but", "can", "chat",
    "conversation", "could", "does", "for", "from", "have", "help", "how", "into", "just", "like",
    "make", "more", "new", "not", "now", "our", "please", "should", "that", "the", "their", "then",
    "there", "these", "they", "this", "those", "use", "want", "was", "what", "when", "where", "which",
    "will", "with", "would", "you", "your",
}

SYNONYMS = {
    "f1": {"formula", "one"},
    "formula1": {"formula", "one"},
    "soccer": {"football"},
    "fixtures": {"schedule"},
    "fixture": {"schedule"},
    "songs": {"music"},
    "tracks": {"music"},
    "dm": {"message"},
    "dms": {"message"},
}

SPACE_RULES = {
    "vellum": {
        "label": "Vellum",
        "terms": {
            "vellum", "agent", "agents", "memory", "skills", "routing", "openrouter", "frontend", "backend",
            "langgraph", "obsidian", "honcho", "plugin", "plugins", "sidebar",
        },
    },
    "sports": {
        "label": "Sports",
        "terms": {
            "sports", "formula", "f1", "nba", "football", "soccer", "arsenal", "league", "race", "racing",
            "driver", "grand", "prix", "basketball", "champions", "premier", "match", "standings",
        },
    },
    "music": {
        "label": "Music",
        "terms": {"music", "spotify", "playlist", "playlists", "album", "albums", "song", "songs", "artist", "tracks"},
    },
    "work": {
        "label": "Work",
        "terms": {"meeting", "roadmap", "sprint", "team", "milestone", "deadline", "stakeholder", "workshop"},
    },
    "personal": {
        "label": "Personal",
        "terms": {"personal", "travel", "trip", "home", "family", "journal", "casual", "holiday", "vacation"},
    },
}

TOPIC_RULES = {
    "vellum": (
        ("chat-organization", "Chat organization", {"organize", "organization", "recent", "sidebar", "folders", "spaces", "search"}),
        ("agent-architecture", "Agent architecture", {"agent", "agents", "architecture", "delegation", "langgraph", "runtime"}),
        ("memory", "Memory", {"memory", "honcho", "fts5", "recall", "obsidian", "vault"}),
        ("skills", "Skills", {"skill", "skills", "hermes", "package", "packages"}),
        ("model-routing", "Model routing", {"model", "models", "routing", "openrouter", "provider", "fallback"}),
        ("frontend", "Frontend", {"frontend", "sidebar", "interface", "ui", "design"}),
    ),
    "sports": (
        ("formula-one", "Formula One", {"f1", "formula", "race", "racing", "driver", "grand", "prix"}),
        ("football", "Football", {"football", "soccer", "arsenal", "champions", "premier", "fixtures", "match"}),
        ("nba", "NBA", {"nba", "basketball"}),
    ),
    "music": (
        ("spotify", "Spotify", {"spotify"}),
        ("playlists", "Playlists", {"playlist", "playlists", "mix", "discover"}),
    ),
    "work": (
        ("meetings", "Meetings", {"meeting", "agenda", "minutes"}),
        ("planning", "Planning", {"roadmap", "sprint", "milestone", "deadline", "plan", "planning"}),
    ),
    "personal": (
        ("travel", "Travel", {"travel", "trip", "holiday", "vacation", "flight", "hotel"}),
    ),
}

SOURCE_ALIASES = {
    "calendar": "Calendar",
    "google-calendar": "Calendar",
    "outlook-calendar": "Calendar",
    "slack": "Slack",
    "spotify": "Spotify",
    "github": "GitHub",
    "google-drive": "Google Drive",
    "drive": "Google Drive",
    "notion": "Notion",
    "gmail": "Gmail",
    "outlook": "Outlook",
    "teams": "Teams",
    "web": "Web",
    "web_search": "Web",
    "serpapi": "Web",
    "files": "Files",
}

ACTIVITY_RULES = (
    ("Scheduling", {"schedule", "calendar", "reschedule", "appointment", "event"}),
    ("Messaging", {"message", "notify", "send", "slack", "email"}),
    ("Coding", {"code", "implement", "debug", "fix", "test", "commit"}),
    ("Research", {"research", "search", "find", "compare", "investigate"}),
    ("Summary", {"summarize", "summary", "recap", "digest"}),
    ("Planning", {"plan", "planning", "roadmap", "strategy"}),
)


@dataclass(frozen=True)
class SearchWeights:
    exact_phrase: float = 12.0
    title_term: float = 3.0
    label_term: float = 4.0
    message_term: float = 16.0
    source_term: float = 4.0
    pinned_bonus: float = 0.8
    recency_bonus: float = 0.7

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "SearchWeights":
        allowed = asdict(cls()).keys()
        return cls(**{key: float(value) for key, value in values.items() if key in allowed})

    def with_updates(self, **updates: float) -> "SearchWeights":
        return replace(self, **updates)


DEFAULT_SEARCH_WEIGHTS = SearchWeights()


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return clean or "unsorted"


def _text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    return str(message.get("text") or message.get("content") or "").strip()


def _role(message: Any) -> str:
    return str(message.get("role") or "message").casefold() if isinstance(message, dict) else "message"


def _tokens(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9]+", text.casefold())
    result: list[str] = []
    for token in raw:
        if len(token) < 2 or token in STOP_WORDS:
            continue
        result.append(token)
        result.extend(sorted(SYNONYMS.get(token, ())))
    return result


def _conversation_text(conversation: dict[str, Any], *, include_assistant: bool = False) -> str:
    parts = [str(conversation.get("title") or "")]
    for message in conversation.get("messages") or []:
        if _role(message) == "user" or include_assistant:
            parts.append(_text(message))
    return " ".join(part for part in parts if part)


def _classify_space(text: str) -> tuple[str, str, float, dict[str, float]]:
    counts = Counter(_tokens(text))
    scores: dict[str, float] = {}
    for space_id, rule in SPACE_RULES.items():
        score = sum(counts[term] for term in rule["terms"])
        if space_id == "vellum" and counts["vellum"]:
            score += 3
        if space_id == "sports" and (counts["f1"] or (counts["formula"] and counts["one"])):
            score += 3
        if space_id == "music" and counts["spotify"]:
            score += 3
        scores[space_id] = float(score)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    winner, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if top <= 0:
        return "unsorted", "Unsorted", 0.0, scores
    confidence = min(0.99, 0.55 + ((top - second) / max(top, 1.0)) * 0.4)
    return winner, str(SPACE_RULES[winner]["label"]), round(confidence, 3), scores


def _topic_for(space_id: str, text: str) -> tuple[str, str]:
    tokens = Counter(_tokens(text))
    ranked: list[tuple[int, int, str, str]] = []
    for index, (topic_id, label, terms) in enumerate(TOPIC_RULES.get(space_id, ())):
        score = sum(tokens[term] for term in terms)
        if topic_id in {"spotify", "nba"} and tokens[topic_id]:
            score += 3
        if score:
            ranked.append((score, -index, topic_id, label))
    if ranked:
        _score, _order, topic_id, label = max(ranked)
        return topic_id, label
    candidates = [token for token, count in tokens.most_common(8) if token not in {space_id, "general"} and count > 0]
    if candidates and space_id != "unsorted":
        label = " ".join(candidates[:2]).title()
        return _slug(label), label
    return "unsorted", "Unsorted"


def _source_facets(conversation: dict[str, Any]) -> list[str]:
    found: set[str] = set()

    def add(value: Any) -> None:
        raw = str(value or "").strip().casefold().replace("_", "-")
        if not raw:
            return
        for key, label in sorted(SOURCE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            normalized = key.replace("_", "-")
            if raw == normalized or raw.startswith(normalized + "-") or normalized in raw:
                found.add(label)
                return

    for app_id in conversation.get("appIds") or conversation.get("app_ids") or []:
        add(app_id)
    for message in conversation.get("messages") or []:
        if isinstance(message, dict):
            if message.get("attachments"):
                found.add("Files")
            for tool in message.get("tools") or []:
                add(tool.get("name") if isinstance(tool, dict) else tool)
            for item in message.get("activity") or []:
                if isinstance(item, dict):
                    add(item.get("name") or item.get("type"))
            for source in message.get("sources") or []:
                if isinstance(source, dict):
                    add(source.get("provider") or source.get("provider_label") or source.get("domain") or "web")
    return sorted(found)


def _activities(text: str) -> list[str]:
    terms = set(_tokens(text))
    matches = [label for label, triggers in ACTIVITY_RULES if terms.intersection(triggers)]
    return matches or ["Conversation"]


def _status(conversation: dict[str, Any], text: str) -> str:
    if conversation.get("archived"):
        return "Archived"
    lowered = text.casefold()
    if any(marker in lowered for marker in ("follow up", "follow-up", "remind me", "later", "next step", "todo")):
        return "Follow-up"
    if any(marker in lowered for marker in ("completed", "done", "resolved", "finished")):
        return "Completed"
    return "Active"


def _segments(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for index, message in enumerate(conversation.get("messages") or []):
        if _role(message) != "user" or not _text(message):
            continue
        space_id, space_label, confidence, _scores = _classify_space(_text(message))
        topic_id, topic_label = _topic_for(space_id, _text(message))
        message_id = str(message.get("id") or index) if isinstance(message, dict) else str(index)
        if segments and segments[-1]["space_id"] == space_id and segments[-1]["topic_id"] == topic_id:
            segments[-1]["end_message_id"] = message_id
            segments[-1]["message_count"] += 1
            segments[-1]["confidence"] = round(max(segments[-1]["confidence"], confidence), 3)
        else:
            segments.append({
                "id": f"segment-{len(segments) + 1}",
                "start_message_id": message_id,
                "end_message_id": message_id,
                "message_count": 1,
                "space_id": space_id,
                "space_label": space_label,
                "topic_id": topic_id,
                "topic_label": topic_label,
                "confidence": confidence,
            })
    return segments


def organize_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    """Return derived metadata without mutating the canonical conversation."""
    text = _conversation_text(conversation)
    space_id, space_label, confidence, scores = _classify_space(text)
    topic_id, topic_label = _topic_for(space_id, text)
    existing = conversation.get("organization") if isinstance(conversation.get("organization"), dict) else {}
    assignment = str(existing.get("assignment") or "automatic")
    if assignment == "manual":
        space_id = _slug(str(existing.get("space_id") or existing.get("space_label") or space_id))
        space_label = str(existing.get("space_label") or space_label)
        topic_id = _slug(str(existing.get("topic_id") or existing.get("topic_label") or topic_id))
        topic_label = str(existing.get("topic_label") or topic_label)
        confidence = 1.0
    elif existing.get("space_id") and existing.get("space_id") != space_id and confidence < 0.78:
        # Avoid visual reshuffling on a weak topic change while a chat is active.
        space_id = str(existing.get("space_id"))
        space_label = str(existing.get("space_label") or space_label)
        topic_id = str(existing.get("topic_id") or topic_id)
        topic_label = str(existing.get("topic_label") or topic_label)

    tokens = Counter(_tokens(text))
    return {
        "space_id": space_id,
        "space_label": space_label,
        "topic_id": topic_id,
        "topic_label": topic_label,
        "sources": _source_facets(conversation),
        "activities": _activities(text),
        "status": _status(conversation, text),
        "confidence": confidence,
        "assignment": assignment,
        "keywords": [term for term, _count in tokens.most_common(8)],
        "segments": _segments(conversation),
        "signals": {key: score for key, score in scores.items() if score > 0},
    }


def _updated_at(conversation: dict[str, Any]) -> str:
    return str(conversation.get("updated_at") or conversation.get("created_at") or conversation.get("created") or "")


def build_conversation_library(conversations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    enriched: list[dict[str, Any]] = []
    space_rows: dict[str, dict[str, Any]] = {}
    topic_counts: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    smart_counts = Counter()

    for conversation in conversations:
        organization = organize_conversation(conversation)
        item = {**conversation, "organization": organization}
        enriched.append(item)
        if conversation.get("archived"):
            smart_counts["archived"] += 1
            continue
        space_id = organization["space_id"]
        row = space_rows.setdefault(space_id, {
            "id": space_id,
            "label": organization["space_label"],
            "count": 0,
            "updated_at": "",
            "topics": [],
        })
        row["count"] += 1
        row["updated_at"] = max(str(row["updated_at"]), _updated_at(conversation))
        topic_counts[space_id][(organization["topic_id"], organization["topic_label"])] += 1
        if conversation.get("pinned"):
            smart_counts["pinned"] += 1
        if organization["status"] == "Follow-up":
            smart_counts["follow-up"] += 1
        for source in organization["sources"]:
            smart_counts[_slug(source)] += 1

    for space_id, row in space_rows.items():
        row["topics"] = [
            {"id": topic_id, "label": label, "count": count}
            for (topic_id, label), count in topic_counts[space_id].most_common()
        ]

    spaces = sorted(space_rows.values(), key=lambda row: (-int(row["count"]), str(row["label"]).casefold()))
    smart_views = [
        {"id": key, "label": label, "count": int(smart_counts[key])}
        for key, label in (
            ("pinned", "Pinned"),
            ("follow-up", "Needs follow-up"),
            ("calendar", "Calendar"),
            ("slack", "Slack"),
            ("spotify", "Spotify"),
            ("files", "Files"),
        )
        if smart_counts[key]
    ]
    enriched.sort(key=_updated_at, reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "spaces": spaces,
        "smart_views": smart_views,
        "conversations": enriched,
    }


def _recency_score(position: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return 1.0 - (position / max(total - 1, 1))


def _snippet(text: str, query_terms: set[str], *, limit: int = 220) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    lowered = clean.casefold()
    positions = [lowered.find(term) for term in query_terms if lowered.find(term) >= 0]
    start = max(0, (min(positions) if positions else 0) - 70)
    end = min(len(clean), start + limit)
    prefix = "..." if start else ""
    suffix = "..." if end < len(clean) else ""
    return prefix + clean[start:end].strip() + suffix


def search_conversations(
    conversations: Iterable[dict[str, Any]],
    query: str,
    *,
    space: str | None = None,
    source: str | None = None,
    status: str | None = None,
    archived: bool = False,
    limit: int = 20,
    weights: SearchWeights = DEFAULT_SEARCH_WEIGHTS,
) -> list[dict[str, Any]]:
    ordered = sorted(list(conversations), key=_updated_at, reverse=True)
    query_clean = query.strip().casefold()
    query_terms = set(_tokens(query))
    results: list[dict[str, Any]] = []

    for position, conversation in enumerate(ordered):
        if bool(conversation.get("archived")) != bool(archived):
            continue
        organization = organize_conversation(conversation)
        if space and _slug(str(space)) not in {organization["space_id"], _slug(organization["space_label"])}:
            continue
        if source and _slug(str(source)) not in {_slug(item) for item in organization["sources"]}:
            continue
        if status and str(status).casefold() != str(organization["status"]).casefold():
            continue

        title = str(conversation.get("title") or "Untitled chat")
        title_terms = set(_tokens(title))
        label_text = " ".join((organization["space_label"], organization["topic_label"], *organization["keywords"]))
        label_terms = set(_tokens(label_text))
        source_terms = set(_tokens(" ".join(organization["sources"])))
        best_message: dict[str, Any] | None = None
        best_message_overlap = 0
        best_exact = False
        for index, message in enumerate(conversation.get("messages") or []):
            message_text = _text(message)
            overlap = len(query_terms.intersection(_tokens(message_text)))
            exact = bool(query_clean and query_clean in message_text.casefold())
            if exact or overlap > best_message_overlap:
                best_message = message if isinstance(message, dict) else {"text": message_text, "id": str(index)}
                best_message_overlap = overlap
                best_exact = exact

        exact_anywhere = bool(query_clean and query_clean in _conversation_text(conversation, include_assistant=True).casefold())
        score = (
            weights.exact_phrase * float(exact_anywhere)
            + weights.title_term * len(query_terms.intersection(title_terms))
            + weights.label_term * len(query_terms.intersection(label_terms))
            + weights.message_term * best_message_overlap
            + weights.source_term * len(query_terms.intersection(source_terms))
            + weights.pinned_bonus * float(bool(conversation.get("pinned")))
            + weights.recency_bonus * _recency_score(position, len(ordered))
        )
        if query_terms and score <= weights.recency_bonus + weights.pinned_bonus:
            continue
        if not query_terms and query_clean and not exact_anywhere:
            continue
        message_text = _text(best_message) if best_message else title
        message_id = str(best_message.get("id") or "") if best_message else ""
        results.append({
            "id": str(conversation.get("id") or ""),
            "thread_id": str(conversation.get("thread_id") or conversation.get("id") or ""),
            "title": title,
            "space_id": organization["space_id"],
            "space_label": organization["space_label"],
            "topic_id": organization["topic_id"],
            "topic_label": organization["topic_label"],
            "sources": organization["sources"],
            "status": organization["status"],
            "updated_at": _updated_at(conversation),
            "pinned": bool(conversation.get("pinned")),
            "message_id": message_id,
            "snippet": _snippet(message_text, query_terms),
            "score": round(score, 4),
            "exact": best_exact,
        })

    results.sort(key=lambda item: (float(item["score"]), str(item["updated_at"])), reverse=True)
    return results[: max(1, min(int(limit), 100))]
