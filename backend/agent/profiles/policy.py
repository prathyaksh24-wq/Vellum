from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class ActiveProfilePolicy:
    profile_id: str
    user_id: str
    source_egress: str
    allowed_tools: frozenset[str]
    allowed_skills: frozenset[str]
    require_confirmation: frozenset[str]
    book_discovery_network: bool = False
    book_discovery_approval: str = ""
    book_discovery_request_key: str = ""


_ACTIVE_PROFILE_POLICY: ContextVar[ActiveProfilePolicy | None] = ContextVar(
    "active_profile_policy",
    default=None,
)


@contextmanager
def profile_policy(
    *,
    profile_id: str,
    user_id: str = "default",
    source_egress: str = "local",
    allowed_tools: frozenset[str],
    allowed_skills: frozenset[str] = frozenset(),
    require_confirmation: frozenset[str] = frozenset(),
    book_discovery_network: bool = False,
    book_discovery_approval: str = "",
    book_discovery_request_key: str = "",
) -> Iterator[ActiveProfilePolicy]:
    clean_user_id = user_id.strip()
    if not clean_user_id:
        raise ValueError("user_id is required")
    if source_egress not in {"local", "external"}:
        raise ValueError("source_egress must be local or external")
    policy = ActiveProfilePolicy(
        profile_id=profile_id,
        user_id=clean_user_id,
        source_egress=source_egress,
        allowed_tools=allowed_tools,
        allowed_skills=allowed_skills,
        require_confirmation=require_confirmation,
        book_discovery_network=book_discovery_network,
        book_discovery_approval=book_discovery_approval,
        book_discovery_request_key=book_discovery_request_key,
    )
    token = _ACTIVE_PROFILE_POLICY.set(policy)
    try:
        yield policy
    finally:
        _ACTIVE_PROFILE_POLICY.reset(token)


def get_active_profile_policy() -> ActiveProfilePolicy | None:
    return _ACTIVE_PROFILE_POLICY.get()
