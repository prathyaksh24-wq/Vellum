"""Private, idempotent ingestion for official Discord data packages."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit
import zipfile

from agent.knowledge.ingestion import IngestionCoordinator, IngestionResult
from agent.knowledge.models import (
    ExternalPolicy,
    IngestionJobInput,
    ObservationActor,
    ObservationInput,
    Sensitivity,
    SourceItemInput,
)
from agent.knowledge.store import KnowledgeStore


ORIGIN = "discord_data_package"
MESSAGE_ACTION = "discord.message.authored"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 250_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_MESSAGE_FILE_BYTES = 64 * 1024 * 1024
MAX_CHANNEL_FILE_BYTES = 1024 * 1024
MAX_ACCOUNT_FILE_BYTES = 4 * 1024 * 1024
MAX_MESSAGES = 2_000_000
_MESSAGE_ENTRY = re.compile(r"^Messages/c(?P<channel_id>\d{5,25})/messages\.json$")


class DiscordPackageError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DiscordPackageImporter:
    def __init__(self, *, store: KnowledgeStore, account_id: str = "default") -> None:
        self.store = store
        self.account_id = account_id.strip() or "default"

    def run(
        self,
        archive_path: str | Path,
        *,
        idempotency_key: str = "",
        requested_by: str = "user",
    ) -> dict[str, Any]:
        path = Path(archive_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("Discord data package was not found")
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise DiscordPackageError("DISCORD_PACKAGE_TOO_LARGE")
        if not zipfile.is_zipfile(path):
            raise DiscordPackageError("DISCORD_PACKAGE_INVALID_ZIP")
        archive_hash = _file_sha256(path)
        key = idempotency_key.strip() or f"discord-package:{self.account_id}:{archive_hash}"
        return IngestionCoordinator(self.store).run(
            IngestionJobInput(
                connector=ORIGIN,
                account_id=self.account_id,
                job_type="message_archive",
                idempotency_key=key,
                requested_by=requested_by,
                lease_seconds=86400,
            ),
            operation=lambda _cursor: self._import_archive(path, archive_hash),
        )

    def status(self) -> dict[str, Any]:
        page = self.history(limit=1)
        return {
            "available": page["total"] > 0,
            "messages": page["total"],
            "latest": page["items"][0]["timestamp"] if page["items"] else "",
            "local_only": True,
        }

    def history(self, *, query: str = "", year: int | None = None, limit: int = 20) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 50))
        terms = _search_terms(query)
        total = 0
        matches: list[dict[str, Any]] = []
        offset = 0
        while offset < MAX_MESSAGES:
            rows = self.store.list_observation_details(
                origin=ORIGIN,
                action=MESSAGE_ACTION,
                limit=500,
                offset=offset,
            )
            if not rows:
                break
            offset += len(rows)
            for row in rows:
                payload = dict(row.get("payload") or {})
                if str(payload.get("account_id") or "") != self.account_id:
                    continue
                total += 1
                timestamp = str(row.get("observed_at") or "")
                if year is not None and not timestamp.startswith(f"{int(year):04d}-"):
                    continue
                if len(matches) >= bounded_limit:
                    continue
                source = self.store.get_source(str(row.get("source_id") or ""), include_content=True)
                if not source:
                    continue
                try:
                    item = json.loads(str(source.get("content") or "{}"))
                except json.JSONDecodeError:
                    continue
                haystack = " ".join(
                    str(item.get(key) or "")
                    for key in ("content", "channel", "channel_type", "guild")
                ).casefold()
                if terms and not all(term in haystack for term in terms):
                    continue
                matches.append(
                    {
                        "id": str(item.get("id") or ""),
                        "channel_id": str(item.get("channel_id") or ""),
                        "channel": str(item.get("channel") or ""),
                        "channel_type": str(item.get("channel_type") or ""),
                        "guild": str(item.get("guild") or ""),
                        "content": str(item.get("content") or ""),
                        "attachments": list(item.get("attachments") or []),
                        "timestamp": str(item.get("timestamp") or timestamp),
                        "source_id": str(source.get("id") or ""),
                        "uri": str(source.get("uri") or ""),
                    }
                )
            if len(rows) < 500:
                break
        return {
            "available": total > 0,
            "total": total,
            "query": query.strip(),
            "year": year,
            "items": matches,
            "local_only": True,
        }

    def _import_archive(self, path: Path, archive_hash: str) -> IngestionResult:
        stats = {
            "channels": 0,
            "messages": 0,
            "messages_with_text": 0,
            "messages_with_attachments": 0,
            "sources_created": 0,
            "sources_existing": 0,
            "source_versions_created": 0,
            "observations_created": 0,
            "observations_existing": 0,
            "excluded_entries": 0,
        }
        observations: list[ObservationInput] = []
        with zipfile.ZipFile(path) as archive:
            entries = _validated_entries(archive)
            account_fingerprint = _account_fingerprint(archive, entries)
            message_entries = sorted(
                (info for name, info in entries.items() if _MESSAGE_ENTRY.fullmatch(name)),
                key=lambda info: info.filename,
            )
            selected_names = {"Messages/index.json", "Account/user.json"}
            for message_info in message_entries:
                match = _MESSAGE_ENTRY.fullmatch(message_info.filename)
                if match is None:
                    continue
                channel_id = match.group("channel_id")
                channel_name = f"Messages/c{channel_id}/channel.json"
                channel_info = entries.get(channel_name)
                if channel_info is None:
                    raise DiscordPackageError("DISCORD_PACKAGE_CHANNEL_METADATA_MISSING")
                selected_names.update({message_info.filename, channel_name})
                channel = _channel_metadata(_read_json(archive, channel_info, MAX_CHANNEL_FILE_BYTES), channel_id)
                messages = _read_json(archive, message_info, MAX_MESSAGE_FILE_BYTES)
                if not isinstance(messages, list):
                    raise DiscordPackageError("DISCORD_PACKAGE_MESSAGES_INVALID")
                stats["channels"] += 1
                for raw_message in messages:
                    if stats["messages"] >= MAX_MESSAGES:
                        raise DiscordPackageError("DISCORD_PACKAGE_MESSAGE_LIMIT_EXCEEDED")
                    normalized = _message_record(raw_message, channel, account_fingerprint)
                    source_result = self.store.upsert_source(
                        SourceItemInput(
                            kind="discord_message",
                            external_id=(
                                f"discord:message:{normalized['channel_id']}:{normalized['id']}"
                            ),
                            account_id=self.account_id,
                            title=f"Discord message authored in {normalized['channel']}",
                            content=json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=2),
                            uri=(
                                f"discord://channels/{normalized['channel_id']}/messages/{normalized['id']}"
                            ),
                            source_path=message_info.filename,
                            published_at=_timestamp(normalized["timestamp"]),
                            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                            external_policy=ExternalPolicy.DENY_RAW,
                            trust="official_discord_data_package",
                            metadata={
                                "connector": ORIGIN,
                                "channel_id": normalized["channel_id"],
                                "channel_type": normalized["channel_type"],
                                "authorship": "account_owner",
                                "preference_evidence": False,
                                "archive_sha256": archive_hash,
                            },
                        )
                    )
                    stats["messages"] += 1
                    stats["messages_with_text"] += int(bool(normalized["content"]))
                    stats["messages_with_attachments"] += int(bool(normalized["attachments"]))
                    stats["sources_created"] += int(bool(source_result["created"]))
                    stats["sources_existing"] += int(not source_result["created"])
                    stats["source_versions_created"] += int(bool(source_result["version_created"]))
                    observations.append(
                        ObservationInput(
                            origin=ORIGIN,
                            action=MESSAGE_ACTION,
                            actor=ObservationActor.USER,
                            trigger="discord_data_export",
                            source_id=str(source_result["source_id"]),
                            event_key=f"discord:message-authored:{self.account_id}:{normalized['id']}",
                            payload={
                                "account_id": self.account_id,
                                "message_id": normalized["id"],
                                "channel_id": normalized["channel_id"],
                                "channel_type": normalized["channel_type"],
                                "has_text": bool(normalized["content"]),
                                "attachment_count": len(normalized["attachments"]),
                                "archive_sha256": archive_hash,
                            },
                            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                            confidence=1.0,
                            observed_at=_timestamp(normalized["timestamp"]),
                        )
                    )
                    if len(observations) >= 500:
                        _flush_observations(self.store, observations, stats)
            _flush_observations(self.store, observations, stats)
            stats["excluded_entries"] = sum(
                1 for info in archive.infolist() if not info.is_dir() and info.filename not in selected_names
            )
            manifest = {
                "archive_sha256": archive_hash,
                "archive_bytes": path.stat().st_size,
                "entry_count": len(archive.infolist()),
                "selected_message_files": len(message_entries),
                "excluded_entries": stats["excluded_entries"],
                "messages": stats["messages"],
                "account_fingerprint": account_fingerprint,
            }
            self.store.upsert_source(
                SourceItemInput(
                    kind="discord_data_package",
                    external_id=f"discord:package:{self.account_id}:{archive_hash}",
                    account_id=self.account_id,
                    title="Discord data package",
                    content=json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
                    sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                    external_policy=ExternalPolicy.DENY_RAW,
                    trust="official_discord_data_package",
                    metadata={"connector": ORIGIN, "archive_sha256": archive_hash},
                )
            )
        return IngestionResult(
            stats=stats,
            cursor=archive_hash,
            cursor_state={
                "archive_sha256": archive_hash,
                "messages": stats["messages"],
                "channels": stats["channels"],
            },
        )


def _validated_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise DiscordPackageError("DISCORD_PACKAGE_ENTRY_LIMIT_EXCEEDED")
    if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
        raise DiscordPackageError("DISCORD_PACKAGE_EXPANDED_SIZE_EXCEEDED")
    entries: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        normalized = info.filename.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
            raise DiscordPackageError("DISCORD_PACKAGE_UNSAFE_PATH")
        if info.flag_bits & 0x1:
            raise DiscordPackageError("DISCORD_PACKAGE_ENCRYPTED_ENTRY")
        if ((info.external_attr >> 16) & 0o170000) == 0o120000:
            raise DiscordPackageError("DISCORD_PACKAGE_SYMLINK_ENTRY")
        if normalized in entries:
            raise DiscordPackageError("DISCORD_PACKAGE_DUPLICATE_ENTRY")
        entries[normalized] = info
    if "Messages/index.json" not in entries:
        raise DiscordPackageError("DISCORD_PACKAGE_MESSAGES_INDEX_MISSING")
    if not any(_MESSAGE_ENTRY.fullmatch(name) for name in entries):
        raise DiscordPackageError("DISCORD_PACKAGE_MESSAGES_MISSING")
    return entries


def _read_json(archive: zipfile.ZipFile, info: zipfile.ZipInfo, max_bytes: int) -> Any:
    if info.file_size > max_bytes:
        raise DiscordPackageError("DISCORD_PACKAGE_JSON_TOO_LARGE")
    with archive.open(info) as source:
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise DiscordPackageError("DISCORD_PACKAGE_JSON_TOO_LARGE")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscordPackageError("DISCORD_PACKAGE_JSON_INVALID") from exc


def _account_fingerprint(archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]) -> str:
    info = entries.get("Account/user.json")
    if info is None:
        return ""
    account = _read_json(archive, info, MAX_ACCOUNT_FILE_BYTES)
    account_id = str(account.get("id") or "").strip() if isinstance(account, dict) else ""
    return sha256(account_id.encode("utf-8")).hexdigest()[:24] if account_id else ""


def _channel_metadata(raw: Any, expected_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DiscordPackageError("DISCORD_PACKAGE_CHANNEL_METADATA_INVALID")
    channel_id = str(raw.get("id") or "").strip()
    if channel_id != expected_id:
        raise DiscordPackageError("DISCORD_PACKAGE_CHANNEL_ID_MISMATCH")
    channel_type = str(raw.get("type") or "UNKNOWN").strip()[:80]
    guild = raw.get("guild") if isinstance(raw.get("guild"), dict) else {}
    guild_name = str(guild.get("name") or "").strip()[:500]
    recipients = raw.get("recipients") if isinstance(raw.get("recipients"), list) else []
    recipient_names = []
    for recipient in recipients[:50]:
        if isinstance(recipient, dict):
            label = str(
                recipient.get("global_name") or recipient.get("username") or recipient.get("name") or ""
            ).strip()
        else:
            label = str(recipient or "").strip()
        if label:
            recipient_names.append(label[:200])
    name = str(raw.get("name") or "").strip()
    label = name or ", ".join(recipient_names) or f"channel {channel_id}"
    return {
        "id": channel_id,
        "type": channel_type,
        "label": label[:500],
        "guild": guild_name,
    }


def _message_record(raw: Any, channel: dict[str, Any], account_fingerprint: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DiscordPackageError("DISCORD_PACKAGE_MESSAGE_INVALID")
    message_id = str(raw.get("ID") or raw.get("id") or "").strip()
    if not re.fullmatch(r"\d{5,25}", message_id):
        raise DiscordPackageError("DISCORD_PACKAGE_MESSAGE_ID_INVALID")
    timestamp = _timestamp(str(raw.get("Timestamp") or raw.get("timestamp") or ""))
    content = str(raw.get("Contents") or raw.get("content") or "")
    if len(content) > 100_000:
        raise DiscordPackageError("DISCORD_PACKAGE_MESSAGE_CONTENT_TOO_LARGE")
    return {
        "id": message_id,
        "channel_id": channel["id"],
        "channel": channel["label"],
        "channel_type": channel["type"],
        "guild": channel["guild"],
        "content": content,
        "attachments": _attachment_metadata(raw.get("Attachments") or raw.get("attachments")),
        "timestamp": timestamp.isoformat(),
        "authorship": "account_owner",
        "account_fingerprint": account_fingerprint,
    }


def _attachment_metadata(raw: Any) -> list[dict[str, str]]:
    values = raw if isinstance(raw, list) else [raw]
    result: list[dict[str, str]] = []
    for value in values[:50]:
        for candidate in str(value or "").splitlines():
            clean = candidate.strip()
            if not clean:
                continue
            parsed = urlsplit(clean)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
                filename = unquote(PurePosixPath(parsed.path).name)[:500]
                result.append({"url": clean_url, "host": parsed.hostname or "", "filename": filename})
            else:
                result.append({"url": "", "host": "", "filename": PurePosixPath(clean).name[:500]})
    return result


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiscordPackageError("DISCORD_PACKAGE_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _flush_observations(
    store: KnowledgeStore,
    observations: list[ObservationInput],
    stats: dict[str, int],
) -> None:
    if not observations:
        return
    result = store.record_observations(observations)
    stats["observations_created"] += result["created"]
    stats["observations_existing"] += result["existing"]
    observations.clear()


def _search_terms(query: str) -> list[str]:
    ignored = {
        "about",
        "discord",
        "archive",
        "from",
        "for",
        "history",
        "message",
        "messages",
        "said",
        "that",
        "what",
        "when",
        "where",
        "with",
    }
    return [
        term
        for term in re.findall(r"[\w'-]+", query.casefold())
        if len(term) > 2 and term not in ignored
    ][:12]


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
