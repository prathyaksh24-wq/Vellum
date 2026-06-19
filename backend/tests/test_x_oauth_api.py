import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent import api


def _settings(client_id: str = "client-123"):
    return SimpleNamespace(
        x_api_client_id=client_id,
        x_api_client_secret="",
        x_tool_allow_private_reads=True,
        x_tool_allow_posts=True,
    )


class _Process:
    def poll(self):
        return None


def test_x_oauth_status_reports_config_and_token_file(monkeypatch, tmp_path):
    xai_oauth_file = tmp_path / "xai-oauth.json"
    x_api_oauth_file = tmp_path / "x-api-oauth.json"
    xai_oauth_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(api, "get_settings", lambda: _settings())
    monkeypatch.setattr(api, "_xai_oauth_file", lambda: xai_oauth_file)
    monkeypatch.setattr(api, "_x_api_oauth_file", lambda: x_api_oauth_file)
    monkeypatch.setattr(api, "_x_oauth_process", None)

    status = asyncio.run(api.x_oauth_status())

    assert status.x_api_configured is True
    assert status.x_api_connected is False
    assert status.xai_oauth_connected is True
    assert status.private_reads_enabled is True
    assert status.posting_enabled is True
    assert status.setup_running is False


def test_x_oauth_start_rejects_missing_client_id(monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: _settings(client_id=""))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.x_oauth_start(api.XOAuthStartRequest()))

    assert exc.value.status_code == 409
    assert "X_API_CLIENT_ID" in exc.value.detail


def test_x_oauth_start_launches_xai_browser_setup_script(monkeypatch, tmp_path):
    calls = {}
    setup_script = tmp_path / "scripts" / "setup_xai_oauth.py"
    setup_script.parent.mkdir()
    setup_script.write_text("print('setup')", encoding="utf-8")

    monkeypatch.setattr(api, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(api, "get_settings", lambda: _settings())
    monkeypatch.setattr(api, "_repo_python", lambda: Path("python"))
    monkeypatch.setattr(api, "_x_oauth_process", None)

    def fake_popen(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return _Process()

    monkeypatch.setattr(api.subprocess, "Popen", fake_popen)

    response = asyncio.run(api.x_oauth_start(api.XOAuthStartRequest()))

    assert response["status"] == "started"
    assert calls["args"] == ["python", str(setup_script), "--timeout-secs", "300"]
    assert calls["kwargs"]["cwd"] == str(tmp_path)
    assert calls["kwargs"]["env"]["X_API_CLIENT_ID"] == "client-123"
