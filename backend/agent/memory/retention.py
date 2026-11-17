"""Memory retention (30 / 90 days) and the daily growth snapshot.

Retention, per the user's policy:

- Inferred memories (things Vellum guessed, not things the user said) are
  archived ``archive_after_days`` after they were learned or last used.
  Archived memories stay recallable.
- At ``delete_after_days`` they are distilled, per topic, into one digest
  memory ("What Vellum knew about X, Aug-Sep") and then permanently deleted
  from SQLite, the search index and Hindsight. The audit log keeps only ids.
- Stated memories, imported memories, corrections, pins and digests are never
  touched by retention; the user removes those themselves.
- Indexed conversation turns (search index and Hindsight turn documents)
  older than ``delete_after_days`` are deleted. The visible chat list is
  not touched.

Growth: one snapshot per day of what Vellum knows, plus milestones, so the
Memory page can show how understanding built up from day 1.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

EXEMPT_ORIGINS = {"stated", "imported", "digest"}
MILESTONE_COUNTS = (1, 10, 25, 50, 100, 250, 500)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _age_anchor(item: dict[str, Any]) -> datetime | None:
    """Learned or last used, whichever is later: memories in use stay active."""
    times = [t for t in (_parse(item.get("created_at")), _parse(item.get("last_used_at"))) if t]
    return max(times) if times else None


def _eligible(item: dict[str, Any]) -> bool:
    return (
        str(item.get("origin") or "inferred") not in EXEMPT_ORIGINS
        and item.get("kind") not in {"correction", "digest"}
        and not item.get("pinned")
    )


def run_retention(orchestrator: Any, *, now: datetime | None = None, distiller: Any | None = None) -> dict[str, Any]:
    store = orchestrator.store
    now = now or datetime.now(UTC)
    settings = store.get_settings()
    result: dict[str, Any] = {"archived": 0, "deleted": 0, "digests": 0, "history_rows_deleted": 0,
                              "provider_turns_forgotten": 0, "audit_rows_scrubbed": store.scrub_deleted_audit_text(),
                              "skipped": ""}
    if not settings.get("memory_enabled", True) or not settings.get("auto_archive_enabled", True):
        result["skipped"] = "retention_off"
        return result
    archive_after = timedelta(days=int(settings.get("archive_after_days", 30)))
    delete_after = timedelta(days=int(settings.get("delete_after_days", 90)))
    if delete_after < archive_after:
        delete_after = archive_after

    for item in store.list_saved() + store.list_pending():
        anchor = _age_anchor(item)
        if _eligible(item) and anchor and now - anchor >= archive_after:
            store.archive(item["id"])
            result["archived"] += 1

    expiring: dict[str, list[dict[str, Any]]] = {}
    for item in store.list_archived():
        anchor = _age_anchor(item)
        if _eligible(item) and anchor and now - anchor >= delete_after:
            expiring.setdefault(item.get("topic") or "About you", []).append(item)
    for topic, items in expiring.items():
        digest_text = _distill(topic, items, distiller=distiller)
        if digest_text:
            store.save_memory(kind="digest", text=digest_text, source_thread_id="retention", confidence=0.6,
                              scope="global", origin="digest", topic=topic,
                              title=f"Earlier: {topic}")
            result["digests"] += 1
        for item in items:
            store.purge(item["id"], reason="retention_deleted", kind=str(item.get("kind") or ""))
            orchestrator.fts5.delete_source_path(f"memory:{item['id']}")
            result["deleted"] += 1

    cutoff = (now - delete_after).isoformat()
    result["history_rows_deleted"] = orchestrator.fts5.delete_history_before(cutoff)
    result["provider_turns_forgotten"] = _forget_old_turns(orchestrator, cutoff)
    store.audit("retention_run", None, ", ".join(f"{k}={v}" for k, v in result.items() if k != "skipped"))
    return result


def _distill(topic: str, items: list[dict[str, Any]], *, distiller: Any | None) -> str:
    dates = sorted(filter(None, (_parse(item.get("created_at")) for item in items)))
    span = ""
    if dates:
        first, last = dates[0].strftime("%b %Y"), dates[-1].strftime("%b %Y")
        span = first if first == last else f"{first} - {last}"
    facts = [str(item["text"]).rstrip(".") for item in items]
    try:
        if distiller is not None:
            body = distiller(topic, facts)
        else:
            from agent.memory.local_llm import complete

            body = complete(
                "Condense these older notes about a user into 1-3 plain sentences that keep what still "
                "matters. Second person. No new facts.",
                f"Topic: {topic}\n" + "\n".join(f"- {fact}" for fact in facts[:60]),
                timeout=45.0, max_tokens=220,
            )
    except Exception:  # noqa: BLE001 - fall back to the facts themselves
        body = ""
    body = " ".join(str(body or "").split()) or "; ".join(facts[:8])
    return f"Earlier{f' ({span})' if span else ''}: {body[:600]}"


def _forget_old_turns(orchestrator: Any, cutoff_iso: str) -> int:
    manager = orchestrator.provider_extensions
    provider = manager.get("hindsight") if manager is not None else None
    if provider is None or not hasattr(provider, "forget_document"):
        return 0
    health = getattr(provider, "health", None)
    if callable(health) and not health():
        return 0  # try again next run; the doc ids stay recorded
    forgotten = 0
    for doc_id in orchestrator.store.provider_docs_before("hindsight", cutoff_iso):
        try:
            provider.forget_document(doc_id)
        except Exception:  # noqa: BLE001 - retried on the next run
            continue
        orchestrator.store.drop_provider_doc(doc_id, "hindsight")
        forgotten += 1
    return forgotten


# -- growth ------------------------------------------------------------------

def _counts(store: Any) -> dict[str, Any]:
    from agent.memory.orchestrator import _durable_memories

    saved = _durable_memories(store.list_saved())
    archived = _durable_memories(store.list_archived())
    by_origin: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    topics: set[str] = set()
    for item in saved + archived:
        by_origin[str(item.get("origin") or "inferred")] = by_origin.get(str(item.get("origin") or "inferred"), 0) + 1
        by_kind[str(item.get("kind") or "fact")] = by_kind.get(str(item.get("kind") or "fact"), 0) + 1
        if item.get("topic"):
            topics.add(str(item["topic"]))
    return {
        "known": len(saved) + len(archived),
        "active": len(saved),
        "archived": len(archived),
        "by_origin": by_origin,
        "by_kind": by_kind,
        "topics": sorted(topics),
        "recalls": sum(int(item.get("use_count") or 0) for item in saved + archived),
    }


def snapshot_growth(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    day = now.date().isoformat()
    history = store.growth(limit=400)
    previous = next((row for row in reversed(history) if row["day"] < day), None)
    counts = _counts(store)
    milestones: list[dict[str, str]] = []
    before = previous["counts"] if previous else {"known": 0, "topics": [], "by_kind": {}}
    for threshold in MILESTONE_COUNTS:
        if before.get("known", 0) < threshold <= counts["known"]:
            milestones.append({"kind": "count", "text": f"Knows {threshold} thing{'s' if threshold > 1 else ''} about you"})
    for topic in counts["topics"]:
        if topic not in set(before.get("topics") or []):
            milestones.append({"kind": "topic", "text": f"Started learning about {topic.lower()}"})
    if counts["by_kind"].get("correction", 0) and not before.get("by_kind", {}).get("correction", 0):
        milestones.append({"kind": "correction", "text": "Took your first correction on board"})
    since = (previous["day"] if previous else "0000")
    for item in store.list_saved():
        if (str(item.get("created_at") or "")[:10] > since and item.get("origin") == "stated"
                and item.get("kind") in {"preference", "correction"}):
            milestones.append({"kind": "learned", "text": f"Learned: {item.get('title') or item['text']}",
                               "memory_id": str(item["id"])})
    store.record_growth(day, counts, milestones[:12])
    return {"day": day, "counts": counts, "milestones": milestones[:12]}


def growth_view(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Day N of knowing the user, the known-facts series and recent milestones."""
    now = now or datetime.now(UTC)
    all_items = store.list_all()
    first = min((str(item.get("created_at") or "") for item in all_items if item.get("created_at")), default="")
    first_day = first[:10] if first else None
    day_number = (now.date() - datetime.fromisoformat(first_day).date()).days + 1 if first_day else 0
    history = store.growth(limit=90)
    series = [{"day": row["day"], "known": int(row["counts"].get("known", 0))} for row in history]
    today = now.date().isoformat()
    live = _counts(store)
    if not series or series[-1]["day"] != today:
        series.append({"day": today, "known": live["known"]})
    milestones = [
        {**milestone, "day": row["day"],
         "day_number": (datetime.fromisoformat(row["day"]).date() - datetime.fromisoformat(first_day).date()).days + 1
         if first_day else 0}
        for row in history for milestone in row["milestones"]
    ]
    return {
        "day_number": day_number,
        "first_day": first_day,
        "counts": live,
        "series": series[-30:],
        "milestones": list(reversed(milestones))[:40],
    }
