from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from agent.agents import MemoryProposal, SpecialistResponse, SpecialistSource, SportsAgent
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


def test_sports_agent_detects_enabled_and_disabled_sports_queries(tmp_path):
    agent = SportsAgent(vault_root=tmp_path / "Vault")

    assert agent.can_handle("What is happening with the NBA Finals?")
    assert agent.can_handle("Give me Arsenal and Champions League news")
    assert agent.can_handle("Arsenal Champions League")
    assert agent.can_handle("Any F1 race updates?")
    assert agent.can_handle("NBA injury report")
    assert agent.can_handle("Arsenal score")
    assert agent.can_handle("UFC updates tonight?")
    assert not agent.can_handle("What is on my calendar tomorrow?")


def test_sports_agent_blocks_disabled_fight_queries(tmp_path):
    agent = SportsAgent(vault_root=tmp_path / "Vault")

    response = agent.answer("Any UFC fight card updates tonight?")

    assert response.status == "blocked"
    assert "disabled" in response.summary.lower()
    assert response.agent == "SportsAgent"
    assert response.confidence > 0.8


def test_sports_agent_disabled_keywords_do_not_match_word_fragments(tmp_path):
    agent = SportsAgent(vault_root=tmp_path / "Vault")

    response = agent.answer("Give me a summary of NBA Finals")

    assert response.status != "blocked"
    assert response.status == "needs_fetch"
    assert not agent.can_handle("Summarize my calendar")


def test_sports_agent_enabled_keywords_do_not_match_word_fragments():
    agent = SportsAgent(vault_root=Path("unused"))

    assert not agent.can_handle("How do I type an underscore in Python?")


def test_sports_agent_generic_terms_need_sports_context():
    agent = SportsAgent(vault_root=Path("unused"))

    assert not agent.can_handle("How do I write a pytest fixture?")
    assert not agent.can_handle("What is my injury insurance policy?")
    assert not agent.can_handle("Can you improve my model score function?")


def test_sports_agent_treats_seeded_placeholder_latest_as_needing_fetch(tmp_path):
    vault_root = tmp_path / "Vault"
    latest = vault_root / "Library" / "Sports" / "NBA" / "latest.md"
    latest.parent.mkdir(parents=True)
    latest.write_text("# NBA - Latest Snapshots\n\n_No snapshots yet._\n", encoding="utf-8")
    agent = SportsAgent(vault_root=vault_root)

    response = agent.answer("NBA Finals update")

    assert response.status == "needs_fetch"
    assert "placeholder" in response.analysis.lower()
    assert response.sources == []


def test_sports_agent_reads_latest_sports_note(tmp_path):
    vault_root = tmp_path / "Vault"
    latest = vault_root / "Library" / "Sports" / "NBA" / "latest.md"
    latest.parent.mkdir(parents=True)
    latest.write_text(
        "---\n"
        "captured_at: 2026-05-27T12:00:00Z\n"
        "---\n\n"
        "Knicks beat the Celtics behind a late fourth-quarter run.\n",
        encoding="utf-8",
    )
    agent = SportsAgent(vault_root=vault_root)

    response = agent.answer("NBA Finals update")

    assert response.status == "answered"
    assert "Knicks" in response.summary
    assert response.sources[0].path_or_url == "Library/Sports/NBA/latest.md"
    assert response.sources[0].captured_at == "2026-05-27T12:00:00Z"
    assert response.memory_proposals[0].scope == "sports"
