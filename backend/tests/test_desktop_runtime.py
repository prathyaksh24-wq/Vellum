"""Desktop identity and lease checks use disposable data, never a user workspace."""
import os
import subprocess
import sys

import pytest

from agent.desktop_runtime import source_build_id, source_files, workspace_root


def test_workspace_override_is_explicit_and_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("VELLUM_WORKSPACE_ROOT", str(tmp_path))
    assert workspace_root() == tmp_path.resolve()
    monkeypatch.setenv("VELLUM_WORKSPACE_ROOT", "relative")
    with pytest.raises(ValueError, match="absolute"):
        workspace_root()


def test_bundle_source_selection_excludes_workspace_data_and_env(tmp_path):
    source = tmp_path / "backend/agent/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("print(1)")
    identity = source_build_id(tmp_path)
    (tmp_path / ".env").write_text("SECRET=private")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/auth.json").write_text("private")
    assert source_files(tmp_path) == [source]
    assert source_build_id(tmp_path) == identity


@pytest.mark.parametrize("hostname", ["localhost", "127.0.0.1"])
def test_account_returns_allow_exact_desktop_origin_without_widening_local_access(hostname):
    from agent.contracts.accounts import SignInRequest
    address = f"http://{hostname}:5184/design-uploads/Vellum%20Default%20Re-designed.html?desktop=1"
    assert SignInRequest(provider="github", return_url=address).return_url == address
    for rejected in (address.replace(":5184", ":5185"), address.replace(hostname, "example.com"), address + "&redirect=evil"):
        with pytest.raises(ValueError):
            SignInRequest(provider="github", return_url=rejected)


def test_workspace_lease_blocks_second_process_and_recovers_after_exit(tmp_path):
    environment = {**os.environ, "VELLUM_WORKSPACE_ROOT": str(tmp_path)}
    code = "from agent.desktop_runtime import acquire_workspace_lease; acquire_workspace_lease(); print('ready',flush=True); input()"
    owner = subprocess.Popen([sys.executable, "-c", code], env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert owner.stdout.readline().strip() == "ready"
        blocked = subprocess.run([sys.executable, "-c", "from agent.desktop_runtime import acquire_workspace_lease; acquire_workspace_lease()"],
                                 env=environment, capture_output=True, text=True, timeout=10)
        assert blocked.returncode != 0
        assert "already has a backend" in blocked.stderr
    finally:
        owner.communicate("\n", timeout=10)
    recovered = subprocess.run([sys.executable, "-c", "from agent.desktop_runtime import acquire_workspace_lease; acquire_workspace_lease()"],
                               env=environment, capture_output=True, timeout=10)
    assert recovered.returncode == 0
