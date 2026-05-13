"""
Folder-level privacy policy for Obsidian content.

Every future retrieval, tool, and LLM node must consult this module before
moving vault content across a boundary. Private folders may be stored and
indexed locally, but their raw chunks are not allowed in OpenRouter prompts.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class FolderPermission(Enum):
    STORED = "stored"
    INDEXED = "indexed"
    SENT_TO_LLM = "sent_to_llm"
    TOOL_ACCESSIBLE = "tool_accessible"


@dataclass(frozen=True)
class FolderPolicy:
    name: str
    permissions: frozenset[FolderPermission]
    requires_scrubbing: bool = True


@dataclass(frozen=True)
class AccessDecision:
    folder: str
    policy: FolderPolicy
    can_store: bool
    can_index: bool
    can_send_to_llm: bool
    can_use_tools: bool
    requires_scrubbing: bool

    @property
    def is_private(self) -> bool:
        return not self.can_send_to_llm


def _permissions(*items: FolderPermission) -> frozenset[FolderPermission]:
    return frozenset(items)


PRIVATE_LOCAL_ONLY = _permissions(FolderPermission.STORED, FolderPermission.INDEXED)
SPORTS_ACCESSIBLE = _permissions(
    FolderPermission.STORED,
    FolderPermission.INDEXED,
    FolderPermission.SENT_TO_LLM,
    FolderPermission.TOOL_ACCESSIBLE,
)
AGENT_ACCESSIBLE = _permissions(
    FolderPermission.STORED,
    FolderPermission.INDEXED,
    FolderPermission.SENT_TO_LLM,
)


FOLDER_POLICIES: dict[str, FolderPolicy] = {
    "X": FolderPolicy("X", SPORTS_ACCESSIBLE, requires_scrubbing=False),
    "Youtube": FolderPolicy("Youtube", PRIVATE_LOCAL_ONLY, requires_scrubbing=True),
    "Books": FolderPolicy("Books", PRIVATE_LOCAL_ONLY, requires_scrubbing=True),
    "feedback": FolderPolicy("feedback", PRIVATE_LOCAL_ONLY, requires_scrubbing=True),
    "Sports": FolderPolicy("Sports", SPORTS_ACCESSIBLE, requires_scrubbing=False),
    "Sports/NBA": FolderPolicy("Sports/NBA", SPORTS_ACCESSIBLE, requires_scrubbing=False),
    "Sports/Formula One": FolderPolicy(
        "Sports/Formula One",
        SPORTS_ACCESSIBLE,
        requires_scrubbing=False,
    ),
    "Sports/Football": FolderPolicy("Sports/Football", SPORTS_ACCESSIBLE, requires_scrubbing=False),
    "Sports/Tennis": FolderPolicy("Sports/Tennis", SPORTS_ACCESSIBLE, requires_scrubbing=False),
    "Agent": FolderPolicy("Agent", AGENT_ACCESSIBLE, requires_scrubbing=False),
}

DEFAULT_POLICY = FolderPolicy("default", PRIVATE_LOCAL_ONLY, requires_scrubbing=True)

_POLICY_BY_CASEFOLD = {name.casefold(): policy for name, policy in FOLDER_POLICIES.items()}


def normalize_folder_path(folder_path: str | Path | None) -> str:
    raw = "" if folder_path is None else str(folder_path)
    normalized = raw.replace("\\", "/").strip().strip("/")

    if not normalized or normalized == ".":
        return ""

    parts = [part for part in normalized.split("/") if part and part != "."]
    if parts and parts[0].casefold() == "vault":
        parts = parts[1:]
    return "/".join(parts)


def folder_from_note_path(note_path: str | Path | None) -> str:
    normalized = normalize_folder_path(note_path)
    if not normalized:
        return ""

    parts = normalized.split("/")
    last = parts[-1]
    if "." in last:
        return "/".join(parts[:-1])
    return normalized


def get_policy(folder_path: str | Path | None) -> FolderPolicy:
    folder = folder_from_note_path(folder_path)
    if not folder:
        return DEFAULT_POLICY

    parts = folder.split("/")
    for end in range(len(parts), 0, -1):
        candidate = "/".join(parts[:end]).casefold()
        policy = _POLICY_BY_CASEFOLD.get(candidate)
        if policy is not None:
            return policy
    return DEFAULT_POLICY


def access_decision(folder_path: str | Path | None) -> AccessDecision:
    folder = folder_from_note_path(folder_path)
    policy = get_policy(folder)
    permissions = policy.permissions
    return AccessDecision(
        folder=folder,
        policy=policy,
        can_store=FolderPermission.STORED in permissions,
        can_index=FolderPermission.INDEXED in permissions,
        can_send_to_llm=FolderPermission.SENT_TO_LLM in permissions,
        can_use_tools=FolderPermission.TOOL_ACCESSIBLE in permissions,
        requires_scrubbing=policy.requires_scrubbing,
    )


def can_store(folder_path: str | Path | None) -> bool:
    return access_decision(folder_path).can_store


def can_index(folder_path: str | Path | None) -> bool:
    return access_decision(folder_path).can_index


def can_send_to_llm(folder_path: str | Path | None) -> bool:
    return access_decision(folder_path).can_send_to_llm


def can_use_tools(folder_path: str | Path | None) -> bool:
    return access_decision(folder_path).can_use_tools


def needs_scrubbing(folder_path: str | Path | None) -> bool:
    return access_decision(folder_path).requires_scrubbing


def chunk_folder(chunk: dict) -> str:
    for key in ("folder", "folder_path", "source_folder", "path", "source", "file_path"):
        value = chunk.get(key)
        if value:
            return folder_from_note_path(value)
    metadata = chunk.get("metadata")
    if isinstance(metadata, dict):
        for key in ("folder", "folder_path", "source_folder", "path", "source", "file_path"):
            value = metadata.get(key)
            if value:
                return folder_from_note_path(value)
    return ""


def filter_chunks_for_llm(chunks: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    allowed: list[dict] = []
    blocked: list[dict] = []

    for chunk in chunks:
        folder = chunk_folder(chunk)
        if can_send_to_llm(folder):
            allowed.append(chunk)
        else:
            blocked.append(chunk)

    return allowed, blocked

