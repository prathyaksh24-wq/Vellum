"""Bounded, atomic OS credential records shared by official connector services."""
import json
import logging
import re
import secrets

logger = logging.getLogger(__name__)
RECORD_FORMAT = "vellum-keyring-parts-v1"
PART_CHARS = 500  # Even worst-case JSON escaping fits Windows' 2,560-byte limit.
MAX_PARTS = 64

class KeyringRecordStore:
    def __init__(self, keyring, *, service, error_type=ValueError, account="connection-v1"):
        self.keyring = keyring
        self.credential_service, self.credential_account = service, account
        self.credential_error = error_type

    def load(self):
        try:
            value = self.keyring.get_password(self.credential_service, self.credential_account)
            data = json.loads(value) if value else {}
            if not isinstance(data, dict):
                raise ValueError()
            if data.get("storage") == RECORD_FORMAT:
                generation, count = self._record_pointer(data)
                parts = []
                for index in range(count):
                    value = self.keyring.get_password(self._part_service(generation, index), self.credential_account)
                    part = json.loads(value) if value else {}
                    if part.get("generation") != generation or not isinstance(part.get("value"), str):
                        raise ValueError()
                    parts.append(part["value"])
                data = json.loads("".join(parts))
                if not isinstance(data, dict):
                    raise ValueError()
            return data
        except Exception:
            raise self.credential_error("Unlock the system credential store and retry this connection.") from None

    def save(self, data):
        written, committed, pointer, root_update_attempted = [], False, None, False
        generation = secrets.token_urlsafe(24)
        try:
            # Parts have unique service names, so Windows keyring does not create
            # shadow copies of prior token blobs when its root entry is updated.
            encoded = json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
            values = [encoded[index:index + PART_CHARS] for index in range(0, len(encoded), PART_CHARS)]
            if not 1 <= len(values) <= MAX_PARTS:
                raise ValueError()
            old = self.keyring.get_password(self.credential_service, self.credential_account)
            for index, value in enumerate(values):
                service = self._part_service(generation, index)
                part = json.dumps({"generation": generation, "value": value}, separators=(",", ":"))
                # Escaping this envelope can expand backslashes from JSON values.
                # The byte guard is authoritative for every platform backend.
                if len(part.encode("utf-16-le")) > 2400:
                    raise ValueError()
                self.keyring.set_password(service, self.credential_account, part)
                written.append(service)
                if self.keyring.get_password(service, self.credential_account) != part:
                    raise ValueError()
            pointer = json.dumps({"storage": RECORD_FORMAT, "generation": generation, "parts": len(values)}, separators=(",", ":"))
            try:
                root_update_attempted = True
                self.keyring.set_password(self.credential_service, self.credential_account, pointer)
            except Exception:
                # A backend can fail after committing. Do not remove parts that
                # are already referenced by the active record in that case.
                if self.keyring.get_password(self.credential_service, self.credential_account) != pointer:
                    raise
            committed = True
            logger.info("Connector authorization stored: entries=%d utf16_bytes=%d", len(values), len(encoded.encode("utf-16-le")))
            try:
                previous = json.loads(old) if old else {}
                if previous.get("storage") == RECORD_FORMAT:
                    previous_generation, count = self._record_pointer(previous)
                    self._delete_parts([self._part_service(previous_generation, index) for index in range(count)])
            except (ValueError, TypeError):
                pass
        except Exception as exc:
            logger.warning("Connector credential save failed: error_type=%s winerror=%s", type(exc).__name__, getattr(exc, "winerror", None))
            if not committed:
                # Cleanup is best-effort; a locked OS store must never make us
                # delete or replace the preceding verified connection.
                safe_to_delete = not root_update_attempted
                if root_update_attempted:
                    try:
                        safe_to_delete = self.keyring.get_password(self.credential_service, self.credential_account) != pointer
                    except Exception:
                        pass
                if safe_to_delete:
                    self._delete_parts(written)
            raise self.credential_error("Connector authorization could not be saved in the system credential store.") from None

    @staticmethod
    def _record_pointer(data):
        generation, count = data.get("generation"), data.get("parts")
        if not isinstance(generation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", generation) or type(count) is not int or not 1 <= count <= MAX_PARTS:
            raise ValueError("Invalid OS credential record")
        return generation, count

    def _part_service(self, generation, index):
        return f"{self.credential_service}.part.{generation}.{index}"

    def _delete_parts(self, services):
        for service in services:
            try:
                self.keyring.delete_password(service, self.credential_account)
            except Exception:
                logger.warning("Connector credential cleanup deferred: OS entry could not be removed")
