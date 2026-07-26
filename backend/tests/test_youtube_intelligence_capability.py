from __future__ import annotations

from pathlib import Path

import pytest

from agent.agents.youtube import YoutubeAgent
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from agent.tools.registry import ToolPermissionError


def _snapshot(_query: str, _limit: int) -> dict:
    return {
        "local_only": True,
        "channels": [
            {
                "label": "Sidemen",
                "trend": "falling",
                "lifecycle": "waning",
                "confidence": 0.91,
                "evidence_count": 24,
                "latest_observation_at": "2026-07-10T10:00:00+00:00",
            }
        ],
        "search_themes": [
            {
                "label": "Arsenal tactics",
                "trend": "rising",
                "lifecycle": "active",
                "confidence": 0.82,
                "evidence_count": 9,
                "latest_observation_at": "2026-07-21T10:00:00+00:00",
            }
        ],
    }


def test_personal_context_capability_is_local_and_youtube_agent_only(tmp_path: Path) -> None:
    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        search_backend=lambda query, limit: [],
        personal_context_backend=_snapshot,
    )
    registry = service.build_registry()

    result = registry.invoke(
        "youtube.personal_context",
        {"query": "How has my interest in Sidemen changed?", "limit": 20},
        agent_name="YoutubeAgent",
    )

    assert result["action"] == "youtube.personal_context"
    assert result["local_only"] is True
    assert result["channels"][0]["label"] == "Sidemen"
    with pytest.raises(ToolPermissionError):
        registry.invoke("youtube.personal_context", {}, agent_name="VellumAgent")


def test_youtube_agent_answers_interest_change_from_local_intelligence(tmp_path: Path) -> None:
    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        search_backend=lambda query, limit: [],
        personal_context_backend=_snapshot,
    )
    agent = YoutubeAgent(tmp_path / "Vault", youtube_service=service)

    response = agent.answer("How has my interest in Sidemen changed?")

    assert response.status == "answered"
    assert "Sidemen" in response.summary
    assert "falling" in response.summary
    assert "24 watch events" in response.summary
    assert response.confidence == 0.91
    assert response.analysis == "Used youtube.personal_context from the local Knowledge Core."
