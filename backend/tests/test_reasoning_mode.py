import pytest

from agent.llm.reasoning import (
    ReasoningMode,
    resolve_reasoning_mode,
    reasoning_extra_body,
    reasoning_profile,
)


def test_resolve_accepts_canonical_values() -> None:
    assert resolve_reasoning_mode("light") is ReasoningMode.light
    assert resolve_reasoning_mode("medium") is ReasoningMode.medium
    assert resolve_reasoning_mode("high") is ReasoningMode.high
    assert resolve_reasoning_mode("extra high") is ReasoningMode.extra_high
    assert resolve_reasoning_mode("max") is ReasoningMode.max
    assert resolve_reasoning_mode("ultra") is ReasoningMode.ultra


def test_resolve_normalizes_case_and_whitespace() -> None:
    assert resolve_reasoning_mode("Extra High") is ReasoningMode.extra_high
    assert resolve_reasoning_mode("  EXTRA  HIGH  ") is ReasoningMode.extra_high
    assert resolve_reasoning_mode("MAX") is ReasoningMode.max


def test_resolve_none_and_empty_stay_none() -> None:
    assert resolve_reasoning_mode(None) is None
    assert resolve_reasoning_mode("") is None
    assert resolve_reasoning_mode("   ") is None


def test_resolve_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        resolve_reasoning_mode("turbo")


def test_profiles_scale_max_tokens() -> None:
    assert reasoning_profile(None) is None
    assert reasoning_profile(ReasoningMode.light).scaled_max_tokens(2048) == 2048
    assert reasoning_profile(ReasoningMode.high).scaled_max_tokens(2048) == 3072
    assert reasoning_profile(ReasoningMode.ultra).scaled_max_tokens(2048) == 8192


def test_extra_body_for_effort_modes() -> None:
    assert reasoning_extra_body(None) == {}
    assert reasoning_extra_body(ReasoningMode.high) == {"reasoning": {"effort": "medium"}}
    assert reasoning_extra_body(ReasoningMode.ultra) == {"reasoning": {"effort": "high"}}
