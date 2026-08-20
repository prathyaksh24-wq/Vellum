from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class ActiveProfilePolicy:
    profile_id: str
    allowed_tools: frozenset[str]
    allowed_skills: frozenset[str]
    require_confirmation: frozenset[str]


_ACTIVE_PROFILE_POLICY: ContextVar[ActiveProfilePolicy | None] = ContextVar(
    "active_profile_policy",
    default=None,
)


@contextmanager
def profile_policy(
    *,
    profile_id: str,
    allowed_tools: frozenset[str],
    allowed_skills: frozenset[str] = frozenset(),
    require_confirmation: frozenset[str] = frozenset(),
) -> Iterator[ActiveProfilePolicy]:
    policy = ActiveProfilePolicy(
        profile_id=profile_id,
        allowed_tools=allowed_tools,
        allowed_skills=allowed_skills,
        require_confirmation=require_confirmation,
    )
    token = _ACTIVE_PROFILE_POLICY.set(policy)
    try:
        yield policy
    finally:
        _ACTIVE_PROFILE_POLICY.reset(token)


def get_active_profile_policy() -> ActiveProfilePolicy | None:
    return _ACTIVE_PROFILE_POLICY.get()
