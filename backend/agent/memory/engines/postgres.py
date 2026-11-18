"""One embedded PostgreSQL instance for the memory engines (pg0, no Docker).

Learned from the prototype:

- pg0 defaults to port 5432, which can collide with a Postgres the user
  already runs. Vellum picks a free loopback port once and keeps it.
- pg0 keeps its binaries and instance registry under ``~/.pg0`` whatever the
  environment says. Only the data directory is configurable, so Vellum puts
  the data in the workspace (``data/engines/postgres``), where backups and
  the user expect it.
- Stopping a client server does not stop Postgres. Vellum stops it
  explicitly when the backend shuts down.

Each engine gets its own database with pgvector enabled.
"""
from __future__ import annotations

import json
import re
import secrets
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INSTANCE_NAME = "vellum-memory"
USERNAME = "vellum"
_DB_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class PostgresState:
    port: int
    password: str


class EnginePostgres:
    def __init__(self, root: Path, *, pg_factory: Callable[..., Any] | None = None,
                 port_picker: Callable[[], int] = free_loopback_port) -> None:
        self.root = Path(root)
        self.data_dir = self.root / "postgres"
        self.state_path = self.root / "postgres.json"
        self._pg_factory = pg_factory
        self._port_picker = port_picker
        self._pg: Any | None = None
        self.state = self._load_state()

    def _load_state(self) -> PostgresState:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return PostgresState(port=int(raw["port"]), password=str(raw["password"]))
        except (OSError, ValueError, KeyError):
            return PostgresState(port=0, password="")

    def _save_state(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"port": self.state.port, "password": self.state.password}),
                                   encoding="utf-8")

    def _factory(self) -> Callable[..., Any]:
        if self._pg_factory is not None:
            return self._pg_factory
        from pg0 import Pg0  # shipped with hindsight-all (pg0-embedded)

        return Pg0

    def _port_free(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def start(self) -> str:
        """Start (or reuse) the instance and return its admin URI."""
        fresh = not self.data_dir.exists()
        if not self.state.password:
            self.state.password = secrets.token_urlsafe(18)
        pg = self._factory()(name=INSTANCE_NAME, port=self.state.port or None, username=USERNAME,
                             password=self.state.password, database="postgres",
                             data_dir=str(self.data_dir))
        info = pg.info()
        if not getattr(info, "running", False):
            if not self.state.port or (not fresh and not self._port_free(self.state.port)):
                # Our saved port was taken by something else: move.
                self.state.port = self._port_picker()
                pg.port = self.state.port
            self.data_dir.parent.mkdir(parents=True, exist_ok=True)
            info = pg.start()
        self.state.port = int(getattr(info, "port", None) or self.state.port)
        self._save_state()
        self._pg = pg
        return self.uri("postgres")

    def uri(self, database: str, *, driver: str = "postgresql") -> str:
        return f"{driver}://{USERNAME}:{self.state.password}@127.0.0.1:{self.state.port}/{database}"

    def ensure_database(self, name: str) -> str:
        """Create the database if missing and enable pgvector in it."""
        if not _DB_NAME.match(name):
            raise ValueError(f"invalid database name: {name!r}")
        if self._pg is None:
            raise RuntimeError("start() first")
        # `pg0 psql` connects to port 5432 whatever the instance's port is, so
        # always pass a full connection URI.
        exists = self._pg.psql("-tA", "-d", self.uri("postgres"), "-c",
                               f"SELECT 1 FROM pg_database WHERE datname = '{name}'").stdout.strip()
        if exists != "1":
            self._pg.psql("-d", self.uri("postgres"), "-c", f'CREATE DATABASE "{name}"')
        self._pg.psql("-d", self.uri(name), "-c", "CREATE EXTENSION IF NOT EXISTS vector")
        return self.uri(name)

    def stop(self) -> None:
        pg = self._pg
        if pg is None:
            try:
                pg = self._factory()(name=INSTANCE_NAME)
            except Exception:  # noqa: BLE001 - pg0 not installed: nothing to stop
                return
        pg.stop()
        self._pg = None
