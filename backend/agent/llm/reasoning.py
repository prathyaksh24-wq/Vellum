"""Reasoning-mode control for Vellum's reasoning agent.

Codex-style per-turn inference-effort levels: ``light``, ``medium``,
``high``, ``extra high``, ``max``, ``ultra``. Each level maps to a provider
profile (reasoning effort token + output budget multiplier) that the
routing adapters apply at the model seam. ``None`` means the standard
interactive profile (unchanged behaviour).

Applies to the reasoning chat agent, its sub-agents, and automations.
The coding mode has its own narrower ``ReasoningEffort`` and is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ReasoningMode(StrEnum):
    light = "light"
    medium = "medium"
    high = "high"
    extra_high = "extra high"
    max = "max"
    ultra = "ultra"


@dataclass(frozen=True)
class ReasoningProfile:
    """Provider-facing profile for a reasoning mode.

    ``effort`` is the provider reasoning-effort token (``low``/``medium``/
    ``high``) passed through to APIs that support reasoning effort.
    ``max_tokens_multiplier`` scales the output budget so deeper reasoning
    modes can emit longer reasoning + answers.
    """

    effort: str | None
    max_tokens_multiplier: float

    def scaled_max_tokens(self, base: int) -> int:
        return max(256, int(base * self.max_tokens_multiplier))


REASONING_PROFILES: dict[ReasoningMode, ReasoningProfile] = {
    ReasoningMode.light: ReasoningProfile(effort="low", max_tokens_multiplier=1.0),
    ReasoningMode.medium: ReasoningProfile(effort="low", max_tokens_multiplier=1.25),
    ReasoningMode.high: ReasoningProfile(effort="medium", max_tokens_multiplier=1.5),
    ReasoningMode.extra_high: ReasoningProfile(effort="high", max_tokens_multiplier=2.0),
    ReasoningMode.max: ReasoningProfile(effort="high", max_tokens_multiplier=3.0),
    ReasoningMode.ultra: ReasoningProfile(effort="high", max_tokens_multiplier=4.0),
}


def resolve_reasoning_mode(raw: str | None) -> ReasoningMode | None:
    """Normalize a user-supplied reasoning mode label.

    Accepts display labels with whitespace/case variance ("Extra High") and
    the canonical enum values. Returns ``None`` for empty/None input, and
    raises ``ValueError`` for unknown labels.
    """
    if raw is None:
        return None
    text = " ".join(str(raw).strip().casefold().split())
    if not text:
        return None
    for mode in ReasoningMode:
        if text == mode.value:
            return mode
    raise ValueError(
        f"unknown reasoning mode {raw!r}; expected one of: "
        + ", ".join(mode.value for mode in ReasoningMode)
    )


def reasoning_profile(mode: ReasoningMode | None) -> ReasoningProfile | None:
    return REASONING_PROFILES[mode] if mode is not None else None


def reasoning_extra_body(mode: ReasoningMode | None) -> dict[str, Any]:
    """Extra request-body keys to send for a reasoning mode (best-effort).

    Uses OpenRouter's ``reasoning: {effort}`` convention, which OpenAI-
    compatible providers accept; providers that do not support reasoning
    effort ignore unknown fields.
    """
    profile = reasoning_profile(mode)
    if profile is None or profile.effort is None:
        return {}
    return {"reasoning": {"effort": profile.effort}}
