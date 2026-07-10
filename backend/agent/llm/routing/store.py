from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from agent.llm.routing.models import (
    CredentialRecord,
    CredentialLease,
    CredentialStrategy,
    CredentialStatus,
    FallbackTarget,
    OPENROUTER_DEFAULT_PROVIDER_ORDER,
    ProviderRoutingPolicy,
    RoutingAttempt,
    validate_fallback_chain,
)


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS routing_policy (
    scope TEXT PRIMARY KEY,
    policy_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routing_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fallback_target (
    position INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credential (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    label TEXT NOT NULL,
    source TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    strategy TEXT NOT NULL,
    model_allowlist_json TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    consecutive_429 INTEGER NOT NULL DEFAULT 0,
    cooldown_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, source)
);

CREATE INDEX IF NOT EXISTS idx_credential_provider_status
ON credential(provider, status);

CREATE TABLE IF NOT EXISTS pool_state (
    provider TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    cursor INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS credential_lease (
    id TEXT PRIMARY KEY,
    credential_id TEXT NOT NULL REFERENCES credential(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_credential_lease_expiry
ON credential_lease(expires_at);

CREATE TABLE IF NOT EXISTS routing_attempt (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    correlation_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    model TEXT NOT NULL,
    api_provider TEXT NOT NULL,
    inference_provider TEXT,
    credential_fingerprint TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    fallback_index INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    failure_kind TEXT,
    status_code INTEGER,
    latency_ms REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_routing_attempt_created
ON routing_attempt(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_routing_attempt_correlation
ON routing_attempt(correlation_id, attempt_number);

PRAGMA user_version=1;
"""


class RoutingStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @staticmethod
    def _policy_scope(model_id: str | None) -> str:
        return "global" if model_id is None else f"model:{model_id.strip()}"

    def _set_policy(self, scope: str, policy: ProviderRoutingPolicy) -> None:
        now = datetime.now(UTC).isoformat()
        payload = policy.model_dump_json(exclude_none=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO routing_policy(scope, policy_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET
                    policy_json=excluded.policy_json,
                    updated_at=excluded.updated_at
                """,
                (scope, payload, now),
            )

    def _get_policy(self, scope: str) -> ProviderRoutingPolicy | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT policy_json FROM routing_policy WHERE scope = ?",
                (scope,),
            ).fetchone()
        if row is None:
            return None
        return ProviderRoutingPolicy.model_validate_json(row["policy_json"])

    def set_global_policy(self, policy: ProviderRoutingPolicy) -> None:
        self._set_policy(self._policy_scope(None), policy)

    def get_global_policy(self) -> ProviderRoutingPolicy:
        return self._get_policy(self._policy_scope(None)) or ProviderRoutingPolicy(
            order=list(OPENROUTER_DEFAULT_PROVIDER_ORDER),
            require_parameters=True,
            allow_fallbacks=True,
        )

    def set_model_policy(self, model_id: str, policy: ProviderRoutingPolicy) -> None:
        normalized = model_id.strip()
        if not normalized:
            raise ValueError("model_id cannot be empty")
        self._set_policy(self._policy_scope(normalized), policy)

    def get_model_policy(self, model_id: str) -> ProviderRoutingPolicy | None:
        return self._get_policy(self._policy_scope(model_id))

    def delete_model_policy(self, model_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM routing_policy WHERE scope = ?",
                (self._policy_scope(model_id),),
            )
        return cursor.rowcount > 0

    def list_model_policies(self) -> dict[str, ProviderRoutingPolicy]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT scope, policy_json FROM routing_policy
                WHERE scope LIKE 'model:%' ORDER BY scope
                """
            ).fetchall()
        return {
            row["scope"].removeprefix("model:"): ProviderRoutingPolicy.model_validate_json(
                row["policy_json"]
            )
            for row in rows
        }

    def replace_fallbacks(self, targets: list[FallbackTarget]) -> None:
        validated = validate_fallback_chain(targets)
        with self._connect() as connection:
            connection.execute("DELETE FROM fallback_target")
            connection.executemany(
                "INSERT INTO fallback_target(position, id, provider, model) VALUES (?, ?, ?, ?)",
                [
                    (position, target.id, target.provider, target.model)
                    for position, target in enumerate(validated)
                ],
            )
            connection.execute(
                """
                INSERT INTO routing_metadata(key, value) VALUES ('fallbacks_initialized', '1')
                ON CONFLICT(key) DO UPDATE SET value='1'
                """
            )

    def fallbacks_initialized(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM routing_metadata WHERE key='fallbacks_initialized'"
            ).fetchone()
        return row is not None and row["value"] == "1"

    def list_fallbacks(self) -> list[FallbackTarget]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, provider, model FROM fallback_target ORDER BY position"
            ).fetchall()
        return [FallbackTarget(**dict(row)) for row in rows]

    def upsert_credential(self, credential: CredentialRecord) -> CredentialRecord:
        now = datetime.now(UTC)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, created_at FROM credential WHERE provider = ? AND source = ?",
                (credential.provider, credential.source),
            ).fetchone()
            credential_id = existing["id"] if existing is not None else credential.id
            created_at = existing["created_at"] if existing is not None else credential.created_at.isoformat()
            connection.execute(
                """
                INSERT INTO credential(
                    id, provider, label, source, fingerprint, status, strategy,
                    model_allowlist_json, request_count, consecutive_429,
                    cooldown_until, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, source) DO UPDATE SET
                    label=excluded.label,
                    fingerprint=excluded.fingerprint,
                    status=excluded.status,
                    strategy=excluded.strategy,
                    model_allowlist_json=excluded.model_allowlist_json,
                    updated_at=excluded.updated_at
                """,
                (
                    credential_id,
                    credential.provider,
                    credential.label,
                    credential.source,
                    credential.fingerprint,
                    credential.status.value,
                    credential.strategy.value,
                    json.dumps(credential.model_allowlist),
                    credential.request_count,
                    credential.consecutive_429,
                    credential.cooldown_until.isoformat() if credential.cooldown_until else None,
                    created_at,
                    now.isoformat(),
                ),
            )
        saved = self.get_credential(credential_id)
        if saved is None:
            raise RuntimeError("credential upsert did not persist")
        return saved

    @staticmethod
    def _credential_from_row(row: sqlite3.Row) -> CredentialRecord:
        return CredentialRecord(
            id=row["id"],
            provider=row["provider"],
            label=row["label"],
            source=row["source"],
            fingerprint=row["fingerprint"],
            status=row["status"],
            strategy=row["strategy"],
            model_allowlist=json.loads(row["model_allowlist_json"]),
            request_count=row["request_count"],
            consecutive_429=row["consecutive_429"],
            cooldown_until=row["cooldown_until"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_credential(self, credential_id: str) -> CredentialRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM credential WHERE id = ?",
                (credential_id,),
            ).fetchone()
        return self._credential_from_row(row) if row is not None else None

    def has_active_leases(self, credential_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM credential_lease WHERE credential_id = ? LIMIT 1",
                (credential_id,),
            ).fetchone()
        return row is not None

    def delete_credential(self, credential_id: str) -> bool:
        if self.has_active_leases(credential_id):
            raise RuntimeError("credential has active leases")
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM credential WHERE id = ?",
                (credential_id,),
            )
        return cursor.rowcount > 0

    def list_credentials(self, provider: str | None = None) -> list[CredentialRecord]:
        query = "SELECT * FROM credential"
        parameters: tuple[str, ...] = ()
        if provider is not None:
            query += " WHERE provider = ?"
            parameters = (provider,)
        query += " ORDER BY created_at, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._credential_from_row(row) for row in rows]

    def set_pool_strategy(self, provider: str, strategy: CredentialStrategy) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pool_state(provider, strategy, cursor) VALUES (?, ?, 0)
                ON CONFLICT(provider) DO UPDATE SET strategy=excluded.strategy
                """,
                (provider, strategy.value),
            )

    def get_pool_state(self, provider: str) -> tuple[CredentialStrategy, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT strategy, cursor FROM pool_state WHERE provider = ?",
                (provider,),
            ).fetchone()
        if row is None:
            return CredentialStrategy.fill_first, 0
        return CredentialStrategy(row["strategy"]), int(row["cursor"])

    def set_pool_cursor(self, provider: str, cursor: int) -> None:
        strategy, _ = self.get_pool_state(provider)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pool_state(provider, strategy, cursor) VALUES (?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET cursor=excluded.cursor
                """,
                (provider, strategy.value, cursor),
            )

    def increment_request_count(self, credential_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE credential
                SET request_count=request_count + 1, updated_at=?
                WHERE id=?
                """,
                (datetime.now(UTC).isoformat(), credential_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(credential_id)

    def create_lease(self, lease: CredentialLease) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO credential_lease(id, credential_id, provider, model, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    lease.id,
                    lease.credential_id,
                    lease.provider,
                    lease.model,
                    lease.expires_at.isoformat(),
                ),
            )

    def release_lease(self, lease_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM credential_lease WHERE id = ?",
                (lease_id,),
            )
        return cursor.rowcount > 0

    def reap_expired_leases(self, now: datetime) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM credential_lease WHERE expires_at <= ?",
                (now.isoformat(),),
            )
        return cursor.rowcount

    def record_attempt(self, attempt: RoutingAttempt) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO routing_attempt(
                    id, correlation_id, thread_id, model, api_provider,
                    inference_provider, credential_fingerprint, attempt_number,
                    fallback_index, outcome, failure_kind, status_code,
                    latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.id,
                    attempt.correlation_id,
                    attempt.thread_id,
                    attempt.model,
                    attempt.api_provider,
                    attempt.inference_provider,
                    attempt.credential_fingerprint,
                    attempt.attempt_number,
                    attempt.fallback_index,
                    attempt.outcome,
                    attempt.failure_kind.value if attempt.failure_kind else None,
                    attempt.status_code,
                    attempt.latency_ms,
                    attempt.created_at.isoformat(),
                ),
            )

    def list_attempts(self, *, limit: int = 50, offset: int = 0) -> list[RoutingAttempt]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, correlation_id, thread_id, model, api_provider,
                       inference_provider, credential_fingerprint, attempt_number,
                       fallback_index, outcome, failure_kind, status_code,
                       latency_ms, created_at
                FROM routing_attempt
                ORDER BY row_id
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [RoutingAttempt(**dict(row)) for row in rows]

    def set_credential_state(
        self,
        credential_id: str,
        *,
        status: CredentialStatus,
        cooldown_until: datetime | None,
        consecutive_429: int,
    ) -> CredentialRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE credential
                SET status = ?, cooldown_until = ?, consecutive_429 = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    cooldown_until.isoformat() if cooldown_until else None,
                    consecutive_429,
                    datetime.now(UTC).isoformat(),
                    credential_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(credential_id)
        saved = self.get_credential(credential_id)
        if saved is None:
            raise KeyError(credential_id)
        return saved

    def user_version(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def journal_mode(self) -> str:
        with self._connect() as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0])
