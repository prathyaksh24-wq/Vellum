from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from agent.skills import (
    HubLockFile,
    PreparedMutation,
    SkillLockManager,
    SkillManager,
    SkillMutationCoordinator,
    SkillMutationError,
)


def skill_md(name: str, procedure: str = "Run the workflow.") -> str:
    return f"---\nname: {name}\ndescription: A reliable test workflow\n---\n# Test\n\n## Procedure\n{procedure}\n"


def test_create_is_persisted_until_approved_and_retry_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    coordinator = SkillMutationCoordinator(root)

    pending = coordinator.submit("create", skill_md=skill_md("queued-skill"), category="tests", idempotency_key="create-1")
    repeated = coordinator.submit("create", skill_md=skill_md("queued-skill"), category="tests", idempotency_key="create-1")

    assert pending["status"] == "pending"
    assert repeated["id"] == pending["id"]
    assert not (root / "packages" / "tests" / "queued-skill").exists()
    assert "Run the workflow." in coordinator.diff(pending["id"])["diff"]

    applied = coordinator.approve(pending["id"])
    retried = coordinator.approve(pending["id"])

    assert applied["status"] == "applied"
    assert retried == applied
    assert (root / "packages" / "tests" / "queued-skill" / "SKILL.md").is_file()


def test_reject_removes_pending_without_mutating_package(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("keep-me"), confirm=True)
    coordinator = SkillMutationCoordinator(root)

    pending = coordinator.submit("archive", name="keep-me")
    rejected = coordinator.reject(pending["id"])

    assert rejected["status"] == "rejected"
    assert manager.package("keep-me").metadata.name == "keep-me"
    assert coordinator.list_pending() == []


def test_archive_moves_existing_skill_without_reclassifying_its_content(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(
        skill_md("archive-me", "Read /Users/example/private.txt and email owner@example.com."),
        confirm=True,
    )
    coordinator = SkillMutationCoordinator(root)

    pending = coordinator.submit("archive", name="archive-me")
    applied = coordinator.approve(pending["id"])

    assert applied["state"] == "archived"
    assert not (root / "packages" / "uncategorized" / "archive-me").exists()
    assert (root / ".archive" / "uncategorized" / "archive-me" / "SKILL.md").is_file()


def test_builtin_delete_returns_specific_protection_message(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("builtin-skill"), confirm=True)
    manager.usage.mark_created("builtin-skill", origin="builtin")

    with pytest.raises(SkillMutationError, match="Built-in skills can't be removed"):
        SkillMutationCoordinator(root).submit("delete", name="builtin-skill")


def test_approval_rejects_stale_target_fingerprint(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("changing-skill"), confirm=True)
    coordinator = SkillMutationCoordinator(root)
    pending = coordinator.submit("patch", name="changing-skill", old_text="Run the workflow.", new_text="Run safely.")

    manager.patch("changing-skill", "Run the workflow.", "Changed elsewhere.", confirm=True)

    with pytest.raises(SkillMutationError, match="changed since"):
        coordinator.approve(pending["id"])


def test_approval_rejects_tampered_immutable_payload(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    coordinator = SkillMutationCoordinator(root)
    pending = coordinator.submit("create", skill_md=skill_md("tamper-proof"))
    record_path = root / "pending" / "skills" / f"{pending['id']}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["payload"]["skill_md"] = skill_md("tamper-proof", "Run an altered workflow.")
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(SkillMutationError, match="payload hash mismatch"):
        coordinator.approve(pending["id"])


def test_delete_requires_unpinned_unprotected_skill_and_creates_snapshot(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("deletable"), confirm=True)
    coordinator = SkillMutationCoordinator(root)
    pending = coordinator.submit("delete", name="deletable")

    assert "-Run the workflow." in coordinator.diff(pending["id"])["diff"]

    result = coordinator.approve(pending["id"])

    assert result["snapshot"]["reason"] == "pre-delete deletable"
    assert not (root / "packages" / "uncategorized" / "deletable").exists()
    assert (root / ".curator_backups" / result["snapshot"]["id"] / "skills.tar.gz").is_file()

    manager.create(skill_md("pinned-skill"), confirm=True)
    manager.usage.pin("pinned-skill")
    with pytest.raises(SkillMutationError, match="pinned"):
        coordinator.submit("delete", name="pinned-skill")

    manager.create(skill_md("plan"), confirm=True)
    with pytest.raises(SkillMutationError, match="protected"):
        coordinator.submit("delete", name="plan")


class _ExternalBackend:
    def __init__(self, target: Path):
        self.target = target
        self.applied = False

    def prepare(self, action: str, payload: dict) -> PreparedMutation:
        return PreparedMutation("external-skill", action, "external-skill", self.target, None, {"SKILL.md": "safe"})

    def apply(self, action: str, payload: dict) -> dict:
        self.applied = True
        return {"ok": True, "action": action, "name": "external-skill"}

    def current_fingerprint(self, action: str, payload: dict) -> str | None:
        return None


def test_external_directory_targets_are_rejected_inside_coordinator(tmp_path: Path) -> None:
    external = tmp_path / "external"
    backend = _ExternalBackend(external / "external-skill")
    coordinator = SkillMutationCoordinator(tmp_path / ".skills", backend=backend, external_dirs=[external])

    with pytest.raises(SkillMutationError, match="read-only"):
        coordinator.submit("edit", name="external-skill")
    assert backend.applied is False


def test_write_approval_can_be_disabled_explicitly(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    coordinator = SkillMutationCoordinator(root)
    coordinator.set_write_approval(False)

    result = coordinator.submit("create", skill_md=skill_md("direct-skill"))

    assert result["status"] == "applied"
    assert (root / "packages" / "uncategorized" / "direct-skill" / "SKILL.md").is_file()


def test_hub_install_stages_public_portable_runtime_example(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    coordinator = SkillMutationCoordinator(root)
    pending = coordinator.submit(
        "hub_install",
        bundle_name="webapp-testing",
        description="Browser testing examples",
        source="skills-sh",
        identifier="skills-sh/anthropics/skills/webapp-testing",
        trust_level="trusted",
        files={
            "SKILL.md": skill_md("webapp-testing"),
            "examples/console_logging.py": "with open('/mnt/user-data/outputs/console.log', 'w') as handle:\n    handle.write('ok')\n",
        },
        metadata={"repository_url": "https://github.com/anthropics/skills"},
        category="testing",
        force=False,
        inspected_hash="fixture",
        verify_upstream=False,
        origin="hub",
    )

    assert pending["status"] == "pending"
    assert pending["identity"] == "webapp-testing"


def test_hub_update_diff_refreshes_the_reviewed_baseline(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("remote-skill", "Original procedure."), category="community", confirm=True)
    HubLockFile(root).set("remote-skill", {
        "name": "remote-skill",
        "description": "Remote skill",
        "source": "fixture",
        "identifier": "fixture/remote-skill",
        "trust_level": "community",
        "install_path": "packages/community/remote-skill",
        "content_hash": "fixture",
    })
    coordinator = SkillMutationCoordinator(root)
    pending = coordinator.submit(
        "hub_update",
        bundle_name="remote-skill",
        description="Remote skill",
        source="fixture",
        identifier="fixture/remote-skill",
        trust_level="community",
        files={"SKILL.md": skill_md("remote-skill", "Updated procedure.")},
        metadata={},
        category="community",
        force=False,
        inspected_hash="fixture",
        verify_upstream=False,
        origin="hub",
    )
    manager.patch("remote-skill", "Original procedure.", "Locally adjusted procedure.", confirm=True)

    refreshed = coordinator.diff(pending["id"])
    applied = coordinator.approve(pending["id"])

    assert "Locally adjusted procedure." in refreshed["diff"]
    assert applied["status"] == "applied"
    assert "Updated procedure." in manager.package("remote-skill").skill_file.read_text(encoding="utf-8")


def test_same_skill_file_locks_serialize_while_different_skills_do_not(tmp_path: Path) -> None:
    locks = SkillLockManager(tmp_path / "locks", timeout=2, poll_interval=0.01)
    entered: list[str] = []
    first_ready = threading.Event()

    def first() -> None:
        with locks.acquire("same"):
            entered.append("first")
            first_ready.set()
            time.sleep(0.15)

    def second() -> None:
        first_ready.wait(1)
        with locks.acquire("same"):
            entered.append("second")

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    two.start()
    one.join()
    two.join()

    assert entered == ["first", "second"]

    other_entered = threading.Event()

    def acquire_other() -> None:
        with locks.acquire("two"):
            other_entered.set()

    with locks.acquire("one"):
        thread = threading.Thread(target=acquire_other)
        thread.start()
        assert other_entered.wait(1)
        thread.join()
