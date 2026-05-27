from types import SimpleNamespace

from agent.tools import sports_curiosity


def test_disabled_league_fetch_returns_disabled_decision_without_throwing(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    monkeypatch.setattr(
        sports_curiosity,
        "get_settings",
        lambda: SimpleNamespace(obsidian_vault_path=vault),
    )

    score = sports_curiosity.should_fetch_sports.invoke({"league": "UFC"})
    result = sports_curiosity.fetch_sports_if_curious.invoke({"league": "UFC"})

    assert score["would_fetch"] is False
    assert score["reason"] == "disabled"
    assert result["fetched"] is False
    assert result["decision"]["league"] == "UFC"
    assert result["decision"]["reason"] == "disabled"
