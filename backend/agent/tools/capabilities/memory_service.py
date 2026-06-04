from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.agents.base import MemoryProposal
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


class MemoryCapabilityService:
    def __init__(self, vault_root: Path, sessions_db: Path) -> None:
        self.vault_root = Path(vault_root)
        self.sessions_db = Path(sessions_db)

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        allowed_agents = frozenset({"MemoryAgent", "VellumAgent", "ResearchAgent", "CodingAgent", "XAgent"})
        registry.register(
            CapabilityRecord(
                name="memory.build_context_pack",
                namespace="memory",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Built memory context",
                adapter=self.build_context_pack,
            )
        )
        registry.register(
            CapabilityRecord(
                name="memory.search_cards",
                namespace="memory",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Searched memory cards",
                adapter=self.search_cards,
            )
        )
        registry.register(
            CapabilityRecord(
                name="memory.review_proposals",
                namespace="memory",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Reviewed memory proposals",
                adapter=self.review_proposals,
            )
        )
        registry.register(
            CapabilityRecord(
                name="memory.detect_conflicts",
                namespace="memory",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Detected memory conflicts",
                adapter=self.detect_conflicts,
            )
        )
        registry.register(
            CapabilityRecord(
                name="memory.create_card",
                namespace="memory",
                access=CapabilityAccess.WRITE,
                allowed_agents=frozenset({"MemoryAgent", "VellumAgent"}),
                stream_label="Created memory card",
                adapter=self.create_card,
            )
        )
        registry.register(
            CapabilityRecord(
                name="memory.propose_card",
                namespace="memory",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Proposed memory card",
                adapter=self.propose_card,
            )
        )
        return registry

    def build_context_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query", ""))
        cards = self.search_cards({"query": query, "limit": 8})["cards"]
        if not cards:
            cards = self.search_cards({"query": "", "limit": 8})["cards"]
        return {
            "action": "memory.build_context_pack",
            "query": query,
            "thread_id": payload.get("thread_id"),
            "agent_name": payload.get("agent_name"),
            "cards": cards,
        }

    def search_cards(self, payload: dict[str, Any]) -> dict[str, Any]:
        query_terms = _terms(str(payload.get("query", "")))
        limit = _positive_int(payload.get("limit"))
        cards: list[dict[str, str]] = []
        memory_root = self.vault_root / "Agent" / "Memories"
        if limit == 0:
            return {"action": "memory.search_cards", "cards": cards}

        for path in sorted(memory_root.rglob("*.md")) if memory_root.exists() else []:
            text = path.read_text(encoding="utf-8")
            if query_terms and not query_terms.intersection(_terms(text)):
                continue
            cards.append(
                {
                    "path": path.relative_to(self.vault_root).as_posix(),
                    "text": text[:1000],
                }
            )
            if limit is not None and len(cards) >= limit:
                break

        return {"action": "memory.search_cards", "cards": cards}

    def review_proposals(self, payload: dict[str, Any]) -> dict[str, Any]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for proposal in payload.get("proposals", []):
            item = _proposal_to_dict(proposal)
            confidence = _float(item.get("confidence"))
            if confidence >= 0.75:
                accepted.append(item)
            else:
                rejected.append(item)
        return {"action": "memory.review_proposals", "accepted": accepted, "rejected": rejected}

    def detect_conflicts(self, payload: dict[str, Any]) -> dict[str, Any]:
        claims = [str(claim) for claim in payload.get("claims", [])]
        conflicts = []
        for index, left in enumerate(claims):
            for right in claims[index + 1 :]:
                if _is_simple_conflict(left, right):
                    conflicts.append({"left": left, "right": right})
        return {"action": "memory.detect_conflicts", "conflicts": conflicts}

    def create_card(self, payload: dict[str, Any]) -> dict[str, str]:
        raw_scope = str(payload.get("scope") or "shared").strip() or "shared"
        scope_parts = _scope_path_parts(raw_scope)
        scope = "/".join(part.lower() for part in scope_parts)
        title = str(payload.get("title") or payload.get("claim") or "Memory").strip() or "Memory"
        summary = str(payload.get("summary") or payload.get("claim") or "").strip()
        evidence = str(payload.get("evidence") or "").strip()
        visible_to = _normalize_visible_to(payload.get("visible_to"))
        now = datetime.now(timezone.utc)
        created = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        stamp = now.strftime("%Y%m%d-%H%M%S-%f")
        memory_root = (self.vault_root / "Agent" / "Memories").resolve()
        directory = memory_root.joinpath(*(_scope_folder_name(part) for part in scope_parts)).resolve()
        if not directory.is_relative_to(memory_root):
            raise ValueError("Memory scope resolved outside the memories vault")
        directory.mkdir(parents=True, exist_ok=True)

        text = "\n".join(
            [
                "---",
                "type: memory",
                f"scope: {_yaml_json(scope)}",
                f"created: {_yaml_json(created)}",
                f"visible_to: {_yaml_json(visible_to)}",
                "---",
                "",
                f"# {title}",
                "",
                summary,
                "",
                "## Evidence",
                "",
                evidence,
                "",
            ]
        )
        path = _write_new_card(directory, stamp, _slug(title), text)
        return {"action": "memory.create_card", "path": path.relative_to(self.vault_root.resolve()).as_posix()}

    def propose_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        proposal = MemoryProposal(
            scope=payload.get("scope", "memory"),
            claim=payload.get("claim") or payload.get("summary") or "",
            evidence=payload.get("evidence") or "",
            confidence=payload.get("confidence", 0.0),
        )
        return {"action": "memory.propose_card", "proposal": _proposal_to_dict(proposal)}


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for term in re.findall(r"[A-Za-z0-9]+", text.lower()):
        if len(term) <= 2:
            continue
        terms.add(term)
    return terms


def _is_simple_conflict(left: str, right: str) -> bool:
    left_like = _likes_subject(left)
    right_like = _likes_subject(right)
    if left_like is None or right_like is None:
        return False
    left_polarity, left_subject = left_like
    right_polarity, right_subject = right_like
    return left_subject == right_subject and left_polarity != right_polarity


def _likes_subject(claim: str) -> tuple[str, str] | None:
    match = re.search(r"\b(dislikes|likes)\b", claim, flags=re.IGNORECASE)
    if match is None:
        return None
    subject = claim[: match.start()] + " " + claim[match.end() :]
    normalized = " ".join(re.findall(r"[A-Za-z0-9]+", subject.lower()))
    return match.group(1).lower(), normalized


def _proposal_to_dict(proposal: Any) -> dict[str, Any]:
    if hasattr(proposal, "model_dump"):
        return dict(proposal.model_dump())
    if hasattr(proposal, "dict"):
        return dict(proposal.dict())
    if isinstance(proposal, dict):
        return dict(proposal)
    return {
        "scope": getattr(proposal, "scope", "memory"),
        "claim": getattr(proposal, "claim", ""),
        "evidence": getattr(proposal, "evidence", ""),
        "confidence": getattr(proposal, "confidence", 0.0),
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _slug(text: str) -> str:
    slug = "-".join(re.findall(r"[A-Za-z0-9]+", text.lower()))
    return slug or "memory"


def _scope_path_parts(scope: str) -> list[str]:
    parts = []
    for raw_part in re.split(r"[\\/]+", scope):
        stripped = raw_part.strip()
        if stripped in {"", ".", ".."}:
            continue
        part = _slug(stripped)
        if part not in {".", ".."}:
            parts.append(part)
    return parts or ["shared"]


def _scope_folder_name(part: str) -> str:
    if part == "shared":
        return "Shared"
    return part.title()


def _normalize_visible_to(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _yaml_json(value: str | list[str]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_new_card(directory: Path, stamp: str, slug: str, text: str) -> Path:
    counter = 1
    while True:
        suffix = "" if counter == 1 else f"-{counter}"
        path = directory / f"{stamp}-{slug}{suffix}.md"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            return path
        except FileExistsError:
            pass
        counter += 1
