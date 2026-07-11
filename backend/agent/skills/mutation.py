from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol
import shutil
import tempfile
import uuid

from agent.skills.configuration import SkillConfigStore
from agent.skills.locking import SkillLockManager
from agent.skills.manager import SkillManager, SkillMutationError
from agent.skills.parser import SkillPackageError, SkillPackageParser
from agent.skills.security import SkillSecurityScanner


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tree_hash(root: Path | None) -> str | None:
    if root is None or not root.exists():
        return None
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class PreparedMutation:
    identity: str
    action: str
    target: str
    target_path: Path
    current_fingerprint: str | None
    preview_files: dict[str, str]


class SkillMutationBackend(Protocol):
    """Storage-neutral boundary used by the mutation coordinator."""

    def prepare(self, action: str, payload: dict[str, Any]) -> PreparedMutation: ...

    def current_fingerprint(self, action: str, payload: dict[str, Any]) -> str | None: ...

    def apply(self, action: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class FilesystemSkillBackend:
    _PACKAGE_MUTATIONS = {"patch", "edit", "write_file", "remove_file"}

    def __init__(self, root: str | Path, *, protected: set[str] | None = None):
        self.root = Path(root)
        self.manager = SkillManager(self.root, require_confirmation=False)
        self.parser = SkillPackageParser()
        self.scanner = SkillSecurityScanner()
        self.protected = protected or {"skill-skill-creator-v1", "plan"}

    def prepare(self, action: str, payload: dict[str, Any]) -> PreparedMutation:
        normalized = action.strip().casefold().replace("-", "_")
        staging = Path(tempfile.mkdtemp(prefix="skill-preview-", dir=self._staging_parent()))
        try:
            if normalized == "create":
                package_root = staging / "package"
                package_root.mkdir()
                (package_root / "SKILL.md").write_text(str(payload.get("skill_md") or ""), encoding="utf-8")
                package = self._validate_package(package_root)
                category = SkillManager._category(str(payload.get("category") or "uncategorized"))
                target = self.root / "packages" / category / package.metadata.name
                if self.manager._name_exists(package.metadata.name):
                    raise SkillMutationError(f"skill already exists: {package.metadata.name}")
                return PreparedMutation(
                    package.metadata.name,
                    normalized,
                    f"packages/{category}/{package.metadata.name}",
                    target,
                    None,
                    self._text_files(package_root),
                )

            name = str(payload.get("name") or "").strip().casefold()
            if not name:
                raise SkillMutationError("skill name is required")
            if normalized in self._PACKAGE_MUTATIONS:
                source = self.manager.package(name).root
                package_root = staging / "package"
                shutil.copytree(source, package_root)
                self._mutate_preview(package_root, normalized, payload)
                parsed = self._validate_package(package_root)
                if parsed.metadata.name != name:
                    raise SkillMutationError("skill name cannot change during edit")
                return PreparedMutation(
                    name,
                    normalized,
                    source.relative_to(self.root).as_posix(),
                    source,
                    _tree_hash(source),
                    self._text_files(package_root),
                )

            if normalized in {"archive", "retire"}:
                source = self.manager.package(name).root
            elif normalized == "restore":
                source = self.manager._locate(self.root / ".archive", name)
                if source is None:
                    raise SkillMutationError(f"archived skill not found: {name}")
            elif normalized == "approve_proposed":
                source = self.manager._locate(self.root / "proposed", name)
                if source is None:
                    raise SkillMutationError(f"proposed skill not found: {name}")
            elif normalized == "delete":
                self._assert_deletable(name)
                source = self.manager._locate(self.root / "packages", name) or self.manager._locate(
                    self.root / ".archive", name
                )
                if source is None:
                    raise SkillMutationError(f"skill not found: {name}")
            else:
                raise SkillMutationError(f"unsupported skill action: {normalized}")
            self._validate_package(source)
            return PreparedMutation(
                name,
                normalized,
                source.relative_to(self.root).as_posix(),
                source,
                _tree_hash(source),
                {} if normalized == "delete" else self._text_files(source),
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def apply(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = action.strip().casefold().replace("-", "_")
        name = str(payload.get("name") or "")
        if normalized == "create":
            return self.manager.create(
                str(payload.get("skill_md") or ""),
                category=str(payload.get("category") or "uncategorized"),
                origin=str(payload.get("origin") or "foreground"),
                confirm=True,
            )
        if normalized == "patch":
            return self.manager.patch(name, str(payload.get("old_text") or ""), str(payload.get("new_text") or ""), confirm=True)
        if normalized == "edit":
            return self.manager.edit(name, str(payload.get("skill_md") or ""), confirm=True)
        if normalized == "write_file":
            return self.manager.write_file(name, str(payload.get("path") or ""), str(payload.get("content") or ""), confirm=True)
        if normalized == "remove_file":
            return self.manager.remove_file(name, str(payload.get("path") or ""), confirm=True)
        if normalized == "archive":
            return self.manager.archive(name, confirm=True)
        if normalized == "retire":
            return self.manager.retire(name, confirm=True)
        if normalized == "restore":
            return self.manager.restore(name, confirm=True)
        if normalized == "approve_proposed":
            return self.manager.approve(name, confirm=True)
        if normalized == "delete":
            self._assert_deletable(name)
            return self.manager.delete(name, confirm=True)
        raise SkillMutationError(f"unsupported skill action: {normalized}")

    def current_fingerprint(self, action: str, payload: dict[str, Any]) -> str | None:
        normalized = action.strip().casefold().replace("-", "_")
        if normalized == "create":
            return None
        name = str(payload.get("name") or "").strip().casefold()
        if normalized in self._PACKAGE_MUTATIONS or normalized in {"archive", "retire"}:
            source = self.manager._locate(self.root / "packages", name)
        elif normalized == "restore":
            source = self.manager._locate(self.root / ".archive", name)
        elif normalized == "approve_proposed":
            source = self.manager._locate(self.root / "proposed", name)
        elif normalized == "delete":
            source = self.manager._locate(self.root / "packages", name) or self.manager._locate(self.root / ".archive", name)
        else:
            source = None
        return _tree_hash(source)

    def _staging_parent(self) -> Path:
        parent = self.root / ".staging"
        parent.mkdir(parents=True, exist_ok=True)
        return parent

    def _validate_package(self, root: Path):
        try:
            package = self.parser.parse(root)
        except SkillPackageError as exc:
            raise SkillMutationError(f"invalid skill package: {exc}") from exc
        result = self.scanner.scan(root, source="local", trust_level="local")
        if result.verdict == "dangerous":
            identifiers = ", ".join(finding.pattern_id for finding in result.findings)
            raise SkillMutationError(f"skill security scan rejected package: {identifiers}")
        return package

    def _assert_deletable(self, name: str) -> None:
        if name in self.protected:
            raise SkillMutationError(f"skill is protected and cannot be deleted: {name}")
        usage = self.manager.usage.get(name)
        if usage.get("protected") is True:
            raise SkillMutationError(f"skill is protected and cannot be deleted: {name}")
        if usage.get("pinned") is True:
            raise SkillMutationError(f"skill is pinned; unpin before deletion: {name}")

    @staticmethod
    def _mutate_preview(root: Path, action: str, payload: dict[str, Any]) -> None:
        if action == "patch":
            old = str(payload.get("old_text") or "")
            if not old:
                raise SkillMutationError("patch requires non-empty old_text")
            target = root / "SKILL.md"
            current = target.read_text(encoding="utf-8")
            if current.count(old) != 1:
                raise SkillMutationError("patch old_text must occur exactly once")
            target.write_text(current.replace(old, str(payload.get("new_text") or ""), 1), encoding="utf-8")
        elif action == "edit":
            (root / "SKILL.md").write_text(str(payload.get("skill_md") or ""), encoding="utf-8")
        elif action == "write_file":
            target = SkillManager._safe_target(root, str(payload.get("path") or ""))
            if target.name == "SKILL.md":
                raise SkillMutationError("use edit to replace SKILL.md")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(payload.get("content") or ""), encoding="utf-8")
        elif action == "remove_file":
            target = SkillManager._safe_target(root, str(payload.get("path") or ""))
            if target.name == "SKILL.md":
                raise SkillMutationError("SKILL.md cannot be removed")
            if not target.is_file() or target.is_symlink():
                raise SkillMutationError(f"support file not found: {payload.get('path') or ''}")
            target.unlink()

    @staticmethod
    def _text_files(root: Path) -> dict[str, str]:
        files: dict[str, str] = {}
        for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
            try:
                files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                files[path.relative_to(root).as_posix()] = "<binary>"
        return files


class SkillMutationCoordinator:
    def __init__(
        self,
        root: str | Path,
        *,
        backend: SkillMutationBackend | None = None,
        external_dirs: list[str | Path] | None = None,
        lock_timeout: float = 10.0,
    ):
        self.root = Path(root)
        self.backend = backend or FilesystemSkillBackend(self.root)
        self.pending_dir = self.root / "pending" / "skills"
        self.receipts_dir = self.root / "pending" / "receipts"
        self.config = SkillConfigStore(self.root / "config.yaml")
        self.locks = SkillLockManager(self.root / ".locks", timeout=lock_timeout)
        configured = external_dirs
        if configured is None:
            configured = self.config.get_option("external_dirs", []) or []
        self.external_dirs = [self._expand_path(value) for value in configured]

    @property
    def write_approval(self) -> bool:
        return bool(self.config.get_option("write_approval", True))

    def set_write_approval(self, enabled: bool) -> dict[str, Any]:
        self.config.set_option("write_approval", bool(enabled))
        return {"ok": True, "write_approval": bool(enabled)}

    def submit(
        self,
        action: str,
        *,
        origin: str = "foreground",
        gist: str = "",
        idempotency_key: str | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        normalized = action.strip().casefold().replace("-", "_")
        data = {**payload, "origin": origin}
        prepared = self.backend.prepare(normalized, data)
        with self.locks.acquire(prepared.identity):
            prepared = self.backend.prepare(normalized, data)
            self._assert_local_target(prepared.target_path)
            key = idempotency_key or _canonical_hash({"action": normalized, "payload": data, "origin": origin})
            existing = self._find_idempotency(key)
            if existing is not None:
                return existing
            record = {
                "id": uuid.uuid4().hex,
                "status": "pending",
                "action": normalized,
                "target": prepared.target,
                "identity": prepared.identity,
                "origin": origin,
                "gist": gist.strip() or self._default_gist(normalized, prepared.identity),
                "created_at": _now(),
                "updated_at": _now(),
                "idempotency_key": key,
                "payload": data,
                "payload_hash": _canonical_hash(data),
                "expected_target_fingerprint": prepared.current_fingerprint,
                "preview_files": prepared.preview_files,
            }
            if not self.write_approval:
                return self._apply_record(record)
            self._write_pending(record)
            return self._public(record)

    def list_pending(self) -> list[dict[str, Any]]:
        if not self.pending_dir.exists():
            return []
        records = []
        for path in sorted(self.pending_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("status") == "pending":
                records.append(self._public(record))
        return records

    def diff(self, identifier: str) -> dict[str, Any]:
        record = self._read_pending(identifier)
        prepared = self.backend.prepare(record["action"], record["payload"])
        self._verify_record(record, prepared)
        current = self._current_text_files(prepared)
        chunks: list[str] = []
        for name in sorted(set(current) | set(record.get("preview_files", {}))):
            before = current.get(name, "").splitlines(keepends=True)
            after = str(record.get("preview_files", {}).get(name, "")).splitlines(keepends=True)
            chunks.extend(difflib.unified_diff(before, after, fromfile=f"a/{name}", tofile=f"b/{name}"))
        return {**self._public(record), "diff": "".join(chunks)}

    def approve(self, identifier: str) -> dict[str, Any]:
        receipt = self._read_receipt(identifier)
        if receipt is not None:
            return receipt["result"]
        record = self._read_pending(identifier)
        with self.locks.acquire(record["identity"]):
            record = self._read_pending(identifier)
            return self._apply_record(record)

    def reject(self, identifier: str) -> dict[str, Any]:
        receipt = self._read_receipt(identifier)
        if receipt is not None:
            return receipt["result"]
        record = self._read_pending(identifier)
        result = {"ok": True, "action": "reject", "id": record["id"], "name": record["identity"], "status": "rejected"}
        self._write_receipt(record, result)
        self._pending_path(record["id"]).unlink(missing_ok=True)
        return result

    def approve_all(self) -> dict[str, Any]:
        return self._apply_all("approve")

    def reject_all(self) -> dict[str, Any]:
        return self._apply_all("reject")

    def _apply_all(self, action: str) -> dict[str, Any]:
        results = []
        errors = []
        for record in self.list_pending():
            try:
                results.append(getattr(self, action)(record["id"]))
            except (OSError, ValueError) as exc:
                errors.append({"id": record["id"], "error": str(exc)})
        return {"ok": not errors, "action": f"{action}_all", "results": results, "errors": errors}

    def _apply_record(self, record: dict[str, Any]) -> dict[str, Any]:
        current_fingerprint = self.backend.current_fingerprint(record["action"], record["payload"])
        if current_fingerprint != record.get("expected_target_fingerprint"):
            raise SkillMutationError("skill changed since this mutation was staged; review a fresh diff")
        prepared = self.backend.prepare(record["action"], record["payload"])
        self._assert_local_target(prepared.target_path)
        self._verify_record(record, prepared)
        snapshot = None
        if record["action"] == "delete":
            from agent.skills.curator import CuratorBackupStore

            snapshot = CuratorBackupStore(self.root).create(f"pre-delete {record['identity']}")
        applied = self.backend.apply(record["action"], record["payload"])
        result = {
            **applied,
            "id": record["id"],
            "status": "applied",
            "idempotency_key": record["idempotency_key"],
        }
        if snapshot:
            result["snapshot"] = snapshot
        self._write_receipt(record, result)
        self._pending_path(record["id"]).unlink(missing_ok=True)
        return result

    def _verify_record(self, record: dict[str, Any], prepared: PreparedMutation) -> None:
        if _canonical_hash(record.get("payload")) != record.get("payload_hash"):
            raise SkillMutationError("pending mutation payload hash mismatch")
        if prepared.identity != record.get("identity") or prepared.target != record.get("target"):
            raise SkillMutationError("pending mutation target changed since review")
        if prepared.current_fingerprint != record.get("expected_target_fingerprint"):
            raise SkillMutationError("skill changed since this mutation was staged; review a fresh diff")

    def _current_text_files(self, prepared: PreparedMutation) -> dict[str, str]:
        if prepared.action == "create":
            return {}
        if not prepared.target_path.exists():
            return {}
        return FilesystemSkillBackend._text_files(prepared.target_path)

    def _find_idempotency(self, key: str) -> dict[str, Any] | None:
        for record in self.list_pending():
            if record.get("idempotency_key") == key:
                return record
        receipt_path = self.receipts_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"
        if receipt_path.is_file():
            try:
                return json.loads(receipt_path.read_text(encoding="utf-8"))["result"]
            except (OSError, json.JSONDecodeError, KeyError):
                return None
        return None

    def _write_pending(self, record: dict[str, Any]) -> None:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_json(self._pending_path(record["id"]), record)

    def _read_pending(self, identifier: str) -> dict[str, Any]:
        path = self._pending_path(identifier)
        if not path.is_file():
            raise SkillMutationError(f"pending skill mutation not found: {identifier}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") != "pending":
            raise SkillMutationError(f"skill mutation is not pending: {identifier}")
        return record

    def _write_receipt(self, record: dict[str, Any], result: dict[str, Any]) -> None:
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        receipt = {"id": record["id"], "idempotency_key": record["idempotency_key"], "completed_at": _now(), "result": result}
        self._atomic_json(self.receipts_dir / f"{record['id']}.json", receipt)
        key_name = hashlib.sha256(record["idempotency_key"].encode("utf-8")).hexdigest()
        self._atomic_json(self.receipts_dir / f"{key_name}.json", receipt)

    def _read_receipt(self, identifier: str) -> dict[str, Any] | None:
        self._validate_identifier(identifier)
        path = self.receipts_dir / f"{identifier}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _assert_local_target(self, target: Path) -> None:
        resolved = target.resolve(strict=False)
        for external in self.external_dirs:
            if resolved == external or external in resolved.parents:
                raise SkillMutationError("external skill directories are read-only; import the skill locally before changing it")

    @staticmethod
    def _expand_path(value: str | Path) -> Path:
        return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve(strict=False)

    @staticmethod
    def _default_gist(action: str, identity: str) -> str:
        return f"{action.replace('_', ' ')} {identity}"

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key not in {"payload", "preview_files"}}

    def _pending_path(self, identifier: str) -> Path:
        self._validate_identifier(identifier)
        return self.pending_dir / f"{identifier}.json"

    @staticmethod
    def _validate_identifier(identifier: str) -> None:
        if not identifier or any(character not in "0123456789abcdef" for character in identifier.casefold()):
            raise SkillMutationError("invalid pending mutation id")

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
