from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import urlparse

from agent.tools.registry import ToolPermissionError, ToolRegistry


class BrokerPermissionError(PermissionError):
    """Deliberately generic denial at a worker trust boundary."""


@dataclass(frozen=True)
class CapabilityGrant:
    token: str
    agent_name: str
    run_id: str
    task_id: str
    allowed_tools: frozenset[str]
    expires_at: datetime


class ToolBroker:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._grants: dict[str, CapabilityGrant] = {}
        self._revoked: set[str] = set()

    def issue_grant(
        self,
        *,
        agent_name: str,
        run_id: str,
        task_id: str,
        allowed_tools: Iterable[str],
        expires_at: datetime | None = None,
    ) -> CapabilityGrant:
        grant = CapabilityGrant(
            token=secrets.token_urlsafe(32),
            agent_name=agent_name,
            run_id=run_id,
            task_id=task_id,
            allowed_tools=frozenset(allowed_tools),
            expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=15),
        )
        self._grants[grant.token] = grant
        return grant

    def revoke(self, token: str) -> None:
        self._revoked.add(token)

    def validate(self, token: str, *, actor: str, run_id: str, task_id: str, tool_name: str) -> CapabilityGrant:
        grant = self._grants.get(token)
        now = datetime.now(UTC)
        if (
            grant is None
            or token in self._revoked
            or grant.agent_name != actor
            or grant.run_id != run_id
            or grant.task_id != task_id
            or tool_name not in grant.allowed_tools
            or _as_utc(grant.expires_at) <= now
        ):
            raise BrokerPermissionError("capability unavailable")
        return grant

    def invoke(
        self,
        token: str,
        *,
        actor: str,
        run_id: str,
        task_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.validate(token, actor=actor, run_id=run_id, task_id=task_id, tool_name=tool_name)
        try:
            return self.registry.invoke(tool_name, payload, agent_name=actor)
        except (KeyError, ToolPermissionError) as exc:
            raise BrokerPermissionError("capability unavailable") from exc


class MemoryBrokerAdapter:
    def __init__(self, memory_broker: Any) -> None:
        self._memory_broker = memory_broker

    def search(self, actor: str, query: str) -> Any:
        return self._memory_broker.search(actor, query)

    def get(self, actor: str, record_id: str) -> Any:
        return self._memory_broker.get(actor, record_id)


class FilesystemBroker:
    def __init__(self, roots: dict[str, tuple[Path, ...] | list[Path]]) -> None:
        self._roots = {actor: tuple(Path(root).resolve() for root in allowed) for actor, allowed in roots.items()}

    def resolve(self, actor: str, path: str | Path) -> Path:
        candidate = Path(path).resolve()
        if not any(_is_within(candidate, root) for root in self._roots.get(actor, ())):
            raise BrokerPermissionError("path unavailable")
        return candidate


class TerminalBroker:
    def __init__(self, roots: dict[str, Path], runner: Callable[[list[str], Path], Any]) -> None:
        self._roots = {actor: Path(root).resolve() for actor, root in roots.items()}
        self._runner = runner

    def run(self, actor: str, argv: list[str]) -> Any:
        root = self._roots.get(actor)
        if root is None or not argv:
            raise BrokerPermissionError("terminal unavailable")
        root.mkdir(parents=True, exist_ok=True)
        return self._runner(list(argv), root)


class NetworkBroker:
    def __init__(self, allowed_domains: dict[str, set[str] | frozenset[str]]) -> None:
        self._allowed = {actor: frozenset(domain.casefold() for domain in domains) for actor, domains in allowed_domains.items()}

    def authorize(self, actor: str, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"http", "https"} or host not in self._allowed.get(actor, frozenset()):
            raise BrokerPermissionError("network unavailable")
        return url


class CredentialBroker:
    def __init__(self, providers: dict[tuple[str, str], Callable[[], str]]) -> None:
        self._providers = dict(providers)

    def perform(self, actor: str, operation: str, callback: Callable[[str], Any]) -> Any:
        provider = self._providers.get((actor, operation))
        if provider is None:
            raise BrokerPermissionError("credential unavailable")
        return callback(provider())

    def __repr__(self) -> str:
        return f"CredentialBroker(scopes={len(self._providers)})"


class ModelBroker:
    def __init__(self, caller: Callable[..., Any], allowed_models: dict[str, set[str]]) -> None:
        self._caller = caller
        self._allowed = {actor: frozenset(models) for actor, models in allowed_models.items()}

    def invoke(self, actor: str, model: str, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        if model not in self._allowed.get(actor, frozenset()):
            raise BrokerPermissionError("model unavailable")
        return self._caller(model=model, messages=messages, **kwargs)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
