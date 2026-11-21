"""Keep a connector's published MCP tool catalog across restarts.

Connector services compare their in-memory catalog revision with the revision
saved in the OS credential store. Without a durable copy, every restart left the
catalog empty and each connector reported "catalog changed, refresh" until the
user reconnected. This mixin stores only the public tool schemas and a salted
PBKDF2 digest of the connection revision; credentials and the revision itself
stay in the OS credential store, and a catalog is restored only when the digest
still matches. Files from the earlier SHA-256 format are ignored (one refresh).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
FORMAT = "vellum-tool-catalog-v2"
# The revision comes from the credential store, so it is hashed like a stored
# secret: salted and deliberately slow, never a bare fast hash.
KDF_ITERATIONS = 120_000


def default_catalog_dir() -> Path:
    from agent.config import REPO_ROOT
    return Path(REPO_ROOT) / "data" / "plugins" / "tool-catalogs"


def _digest(revision: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", revision.encode("utf-8"), bytes.fromhex(salt), KDF_ITERATIONS).hex()


class PersistedToolCatalog:
    """Mixin for services exposing `tools`, `tools_revision` and `load()`."""

    catalog_dir: Path | None = None

    @property
    def catalog_key(self) -> str:
        return self.provider.plugin_id

    def _catalog_path(self) -> Path:
        key = "".join(ch for ch in self.catalog_key if ch.isalnum() or ch in "-_")
        return (self.catalog_dir or default_catalog_dir()) / f"{key}.json"

    @property
    def tools(self) -> list[dict[str, Any]]:
        self._restore_catalog()
        return self.__dict__.get("_catalog_tools", [])

    @tools.setter
    def tools(self, value) -> None:
        self.__dict__["_catalog_restored"] = True
        self.__dict__["_catalog_tools"] = list(value)

    @property
    def tools_revision(self) -> str:
        self._restore_catalog()
        return self.__dict__.get("_catalog_revision", "")

    @tools_revision.setter
    def tools_revision(self, value: str) -> None:
        self.__dict__["_catalog_restored"] = True
        self.__dict__["_catalog_revision"] = value or ""
        self._persist_catalog()

    def _persist_catalog(self) -> None:
        path = self._catalog_path()
        revision = self.__dict__.get("_catalog_revision", "")
        tools = self.__dict__.get("_catalog_tools", [])
        try:
            if not revision or not tools:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            salt = os.urandom(16).hex()
            temporary.write_text(json.dumps({"format": FORMAT, "salt": salt, "revision_digest": _digest(revision, salt),
                                             "tools": tools}, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        except OSError as exc:  # a missing cache only costs one catalog refresh
            logger.warning("Tool catalog cache write failed: plugin=%s error_type=%s", self.catalog_key, type(exc).__name__)

    def _restore_catalog(self) -> None:
        if self.__dict__.get("_catalog_restored"):
            return
        self.__dict__["_catalog_restored"] = True
        try:
            stored = json.loads(self._catalog_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        tools = stored.get("tools") if isinstance(stored, dict) else None
        if stored.get("format") != FORMAT or not isinstance(tools, list) or not all(isinstance(item, dict) for item in tools):
            return
        try:
            revision = str(self.load().get("revision") or "")
        except Exception:  # credential store locked: keep the cache for a later read
            self.__dict__["_catalog_restored"] = False
            return
        salt, expected = str(stored.get("salt") or ""), str(stored.get("revision_digest") or "")
        try:
            matches = bool(revision and salt and expected) and hmac.compare_digest(_digest(revision, salt), expected)
        except ValueError:  # malformed salt
            matches = False
        if matches:
            self.__dict__["_catalog_tools"] = tools
            self.__dict__["_catalog_revision"] = revision
