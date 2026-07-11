import asyncio
from types import SimpleNamespace

from agent.scheduler import retention


def test_scheduled_retention_uses_guarded_apply_policy(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        retention,
        "get_settings",
        lambda: SimpleNamespace(
            obsidian_vault_path=tmp_path / "Vault",
            retention_archive_days=30,
            retention_delete_days=90,
        ),
    )

    def fake_apply(**kwargs):
        captured.update(kwargs)
        return {"archived": 1, "deleted": 0, "blocked": 0}

    monkeypatch.setattr(retention, "apply_retention", fake_apply)

    result = asyncio.run(retention.run_retention())

    assert result["archived"] == 1
    assert captured["dry_run"] is False
    assert captured["archive_after_days"] == 30
    assert captured["delete_after_days"] == 90
