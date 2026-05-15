from pathlib import Path

from agent.terminal.profiles import (
    DEFAULT_CWD,
    PROFILE_ALIASES,
    TerminalProfile,
    get_profile,
    list_profiles,
)


def test_default_cwd_points_at_repo_root():
    assert DEFAULT_CWD.name == "Vellum"
    assert (DEFAULT_CWD / "backend").exists()
    assert (DEFAULT_CWD / "frontend").exists()


def test_catalog_contains_expected_profile_ids(monkeypatch):
    monkeypatch.setattr("agent.terminal.profiles._which", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setattr("agent.terminal.profiles._wsl_distros", lambda: ["Ubuntu"])
    monkeypatch.delenv("VELLUM_MACOS_SSH_TARGET", raising=False)

    profiles = {profile.id: profile for profile in list_profiles()}

    assert set(profiles) == {"powershell", "cmd", "pwsh", "wsl", "git-bash", "macos"}
    assert profiles["powershell"].available is True
    assert profiles["cmd"].available is True
    assert profiles["pwsh"].available is True
    assert profiles["wsl"].available is True
    assert profiles["git-bash"].available is True
    assert profiles["macos"].available is False
    assert "SSH target" in profiles["macos"].reason


def test_unavailable_profiles_include_reason(monkeypatch):
    monkeypatch.setattr("agent.terminal.profiles._which", lambda name: None)
    monkeypatch.setattr("agent.terminal.profiles._wsl_distros", lambda: [])
    monkeypatch.delenv("VELLUM_MACOS_SSH_TARGET", raising=False)

    profiles = {profile.id: profile for profile in list_profiles()}

    assert profiles["pwsh"].available is False
    assert "pwsh.exe" in profiles["pwsh"].reason
    assert profiles["wsl"].available is False
    assert "WSL" in profiles["wsl"].reason
    assert profiles["git-bash"].available is False
    assert "Git Bash" in profiles["git-bash"].reason


def test_macos_profile_uses_ssh_target_from_environment(monkeypatch):
    monkeypatch.setattr("agent.terminal.profiles._which", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setenv("VELLUM_MACOS_SSH_TARGET", "archit@mac-mini.local")

    profile = get_profile("mac")

    assert profile.id == "macos"
    assert profile.available is True
    assert profile.command == "ssh"
    assert profile.args == ["archit@mac-mini.local"]


def test_profile_aliases_resolve_to_canonical_ids(monkeypatch):
    monkeypatch.setattr("agent.terminal.profiles._which", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setattr("agent.terminal.profiles._wsl_distros", lambda: ["Ubuntu"])

    assert PROFILE_ALIASES["ubuntu"] == "wsl"
    assert get_profile("ps").id == "powershell"
    assert get_profile("bash").id == "git-bash"
    assert get_profile("unknown") is None


def test_terminal_profile_serializes_for_api():
    profile = TerminalProfile(
        id="powershell",
        label="PowerShell",
        command="powershell.exe",
        args=["-NoLogo"],
        cwd=Path("C:/work"),
        available=True,
        reason=None,
    )

    assert profile.to_public_dict() == {
        "id": "powershell",
        "label": "PowerShell",
        "available": True,
        "reason": None,
        "cwd": "C:\\work",
    }
