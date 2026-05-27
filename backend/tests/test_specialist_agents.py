from typing import get_args

import pytest
from pydantic import ValidationError

from agent.agents import MemoryProposal, SpecialistResponse, SpecialistSource
from agent.agents.base import (
    Freshness,
    MemoryScope,
    SourceKind,
    SpecialistStatus,
)


def test_specialist_response_defaults_are_empty_and_bounded():
    response = SpecialistResponse(
        agent="SportsAgent",
        status="answered",
        summary="Arsenal won the title.",
    )

    assert response.analysis == ""
    assert response.sources == []
    assert response.confidence == 0.0
    assert response.memory_proposals == []
    assert "answered" in get_args(SpecialistStatus)


def test_specialist_source_tracks_freshness_metadata():
    source = SpecialistSource(
        kind="api",
        title="NBA live scoreboard",
        path_or_url="https://example.com/scores",
        captured_at="2026-05-27T10:00:00Z",
        freshness="live",
    )

    assert source.kind == "api"
    assert source.captured_at == "2026-05-27T10:00:00Z"
    assert source.freshness == "live"
    assert "api" in get_args(SourceKind)
    assert "live" in get_args(Freshness)


def test_specialist_source_defaults_to_historical_without_capture_time():
    source = SpecialistSource(
        kind="vault",
        title="Sports ambient note",
        path_or_url="Vault/Library/Sports/Ambient/latest.md",
    )

    assert source.captured_at == ""
    assert source.freshness == "historical"


def test_memory_proposal_structure_and_confidence_validation():
    proposal = MemoryProposal(
        scope="sports",
        claim="User prefers strategic sports analysis over raw scoreboards.",
        evidence="Repeatedly asked for injuries, analysis, and key players.",
        confidence=0.8,
    )

    assert proposal.scope == "sports"
    assert proposal.claim.startswith("User prefers")
    assert proposal.evidence.startswith("Repeatedly")
    assert proposal.confidence == 0.8
    assert "sports" in get_args(MemoryScope)

    with pytest.raises(ValidationError):
        MemoryProposal(
            scope="sports",
            claim="Invalid confidence",
            evidence="Confidence must stay in range.",
            confidence=1.1,
        )
