"""Deny-by-default disclosure policy at Vellum's external model seam."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
from types import MappingProxyType
from typing import Any, AsyncIterator, Mapping, Sequence
from uuid import uuid4

from agent.privacy.scrubber import PIIDetection, PrivacyScrubber, Replacement


HARD_BLOCKED_LABELS = frozenset(
    {"SECRET", "CRYPTO_KEY", "GOVERNMENT_ID", "CREDIT_CARD", "FINANCIAL_ID"}
)
_SURROGATE_FIRST_NAMES = (
    "Marcus", "Elena", "Jonah", "Nadia", "Adrian", "Maya", "Julian", "Leila",
    "Theo", "Clara", "Elias", "Anika", "Caleb", "Sofia", "Dorian", "Mira",
    "Leon", "Amara", "Simon", "Talia", "Rowan", "Iris", "Noah", "Selene",
)
_SURROGATE_LAST_NAMES = (
    "Hale", "Brooks", "Mercer", "Navarro", "Ellis", "Bennett", "Sato", "Laurent",
    "Keller", "Monroe", "Fischer", "Vega", "Patel", "Quinn", "Ibrahim", "Moreau",
    "Reyes", "Sinclair", "Nolan", "Kim", "Shah", "Meyer", "Costa", "Blake",
)
_SURROGATE_LOCATIONS = (
    "Northbridge", "Silvermere", "Cedar Hollow", "Westhaven", "Larkspur Bay",
    "Ashford Vale", "Maple Crossing", "Stonewick", "Brightwater", "Pinecrest",
    "Redwood Point", "Willowmere", "Foxglove", "Elmstead", "Rosehaven", "Fairmont",
)
_SURROGATE_ORGANIZATIONS = (
    "Aster Works", "Northstar Labs", "Cedar & Finch", "Meridian Studio",
    "Bluehaven Group", "Lattice Research", "Harborlight Systems", "Juniper House",
    "Orchard Labs", "Silverline Partners", "Mosaic Works", "Redwood Collective",
    "Clearwater Studio", "Lantern Research", "Oak & Vale", "Fieldstone Systems",
)


def _natural_surrogate(label: str, digest: bytes, value: str) -> str | None:
    if label == "PERSON":
        first = _SURROGATE_FIRST_NAMES[digest[0] % len(_SURROGATE_FIRST_NAMES)]
        last_index = digest[1] % len(_SURROGATE_LAST_NAMES)
        candidate = f"{first} {_SURROGATE_LAST_NAMES[last_index]}"
        if candidate.casefold() == value.casefold():
            last_index = (last_index + 1) % len(_SURROGATE_LAST_NAMES)
            candidate = f"{first} {_SURROGATE_LAST_NAMES[last_index]}"
        return candidate
    if label == "LOCATION":
        return _SURROGATE_LOCATIONS[int.from_bytes(digest[:2], "big") % len(_SURROGATE_LOCATIONS)]
    if label == "ORGANIZATION":
        return _SURROGATE_ORGANIZATIONS[int.from_bytes(digest[:2], "big") % len(_SURROGATE_ORGANIZATIONS)]
    if label == "EMAIL":
        return f"contact.{digest[:4].hex()}@masked.invalid"
    if label == "PHONE":
        return f"+1 202-555-{100 + (int.from_bytes(digest[:2], 'big') % 100):04d}"
    if label == "ADDRESS":
        number = 10 + (digest[0] % 80)
        street = _SURROGATE_LOCATIONS[digest[1] % len(_SURROGATE_LOCATIONS)]
        return f"{number} {street} Lane"
    if label == "IP_ADDRESS":
        return f"192.0.2.{1 + (digest[0] % 253)}"
    return None




class ProtectionMode(StrEnum):
    local_only = "local_only"
    ask_before_sharing = "ask_before_sharing"
    protect_for_me = "protect_for_me"
    full_context = "full_context"


class DisclosureBlocked(RuntimeError):
    """Raised before network I/O when a disclosure cannot satisfy local policy."""


@dataclass(frozen=True)
class DestinationPolicy:
    """Reviewed model destination and its non-disableable privacy properties."""

    name: str
    endpoint: str
    approved_models: frozenset[str]
    data_collection: str
    zdr: bool
    prompt_logging: bool
    response_caching: bool

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("destination name is required")
        if not self.endpoint.casefold().startswith("https://"):
            raise ValueError("external model destinations must use TLS")
        if not self.approved_models:
            raise ValueError("approved model allowlist cannot be empty")
        if self.data_collection != "deny":
            raise ValueError("external model destinations must deny data collection")
        if self.zdr is not True:
            raise ValueError("external model destinations must require ZDR")
        if self.prompt_logging:
            raise ValueError("external model destinations must disable prompt logging")
        if self.response_caching:
            raise ValueError("external model destinations must disable response caching")


@dataclass(frozen=True)
class DisclosurePolicy:
    mode: ProtectionMode
    receipt_path: Path
    destinations: Mapping[str, DestinationPolicy]

    def __post_init__(self) -> None:
        normalized = {key.casefold(): value for key, value in self.destinations.items()}
        if len(normalized) != len(self.destinations):
            raise ValueError("duplicate disclosure destination")
        object.__setattr__(self, "destinations", MappingProxyType(normalized))


@dataclass(frozen=True)
class DisclosureGrant:
    """Local, scoped, expiring authority for one class of outbound disclosure."""

    mode: ProtectionMode
    destinations: frozenset[str]
    purposes: frozenset[str]
    thread_id: str
    categories: frozenset[str]
    expires_at: datetime
    id: str = field(default_factory=lambda: uuid4().hex)

    def permits(
        self,
        *,
        mode: ProtectionMode,
        destination: str,
        purpose: str,
        thread_id: str,
        categories: frozenset[str],
        now: datetime,
    ) -> bool:
        expiry = self.expires_at
        if expiry.tzinfo is None:
            return False
        return (
            self.mode is mode
            and now < expiry.astimezone(UTC)
            and destination.casefold() in {item.casefold() for item in self.destinations}
            and purpose.casefold() in {item.casefold() for item in self.purposes}
            and self.thread_id == thread_id
            and categories <= {item.upper() for item in self.categories}
        )


@dataclass(frozen=True)
class PreparedDisclosure:
    messages: tuple[Any, ...]
    replacements: tuple[Replacement, ...]
    receipt_id: str
    destination: str
    endpoint: str
    model: str
    purpose: str
    mode: ProtectionMode
    categories: tuple[str, ...]
    transformations: tuple[str, ...]
    decision_source: str
    policy_flags: Mapping[str, Any]

    def restore_message(self, message: Any) -> Any:
        return _copy_message(message, lambda value: _restore_value(value, self.replacements))


class DisclosureBroker:
    """Prepare an external model request and record its metadata-only receipt."""

    def __init__(
        self,
        *,
        policy: DisclosurePolicy,
        scrubber: PrivacyScrubber | None = None,
        alias_key: bytes | None = None,
    ) -> None:
        self.policy = policy
        self.scrubber = scrubber or PrivacyScrubber()
        self._alias_key = alias_key or secrets.token_bytes(32)
        self._receipt_lock = threading.Lock()

    def prepare_messages(
        self,
        messages: Sequence[Any],
        *,
        destination: str,
        model: str,
        purpose: str,
        thread_id: str,
        mode: ProtectionMode | str | None = None,
        grant: DisclosureGrant | None = None,
    ) -> PreparedDisclosure:
        selected_mode = ProtectionMode(mode or self.policy.mode)
        normalized_destination = destination.casefold()
        destination_policy = self.policy.destinations.get(normalized_destination)
        if destination_policy is None:
            self._block(
                destination=destination,
                model=model,
                purpose=purpose,
                mode=selected_mode,
                categories=(),
                reason="destination_not_reviewed",
            )
            raise DisclosureBlocked("external destination is not approved")
        if model not in destination_policy.approved_models:
            self._block(
                destination=destination,
                model=model,
                purpose=purpose,
                mode=selected_mode,
                categories=(),
                reason="model_not_reviewed",
                destination_policy=destination_policy,
            )
            raise DisclosureBlocked("external model is not approved")

        detections = self._analyze_messages(messages)
        categories = frozenset(item.label for item in detections)
        if categories & HARD_BLOCKED_LABELS:
            self._block(
                destination=destination,
                model=model,
                purpose=purpose,
                mode=selected_mode,
                categories=categories,
                reason="hard_blocked_category",
                destination_policy=destination_policy,
            )
            raise DisclosureBlocked("sensitive content is blocked from external disclosure")
        if selected_mode is ProtectionMode.local_only:
            self._block(
                destination=destination,
                model=model,
                purpose=purpose,
                mode=selected_mode,
                categories=categories,
                reason="local_only",
                destination_policy=destination_policy,
            )
            raise DisclosureBlocked("cloud disclosure is disabled for this task")

        decision_source = "mode:protect_for_me"
        exact = False
        if selected_mode is ProtectionMode.ask_before_sharing:
            if not self._grant_permits(
                grant,
                mode=ProtectionMode.ask_before_sharing,
                destination=destination,
                purpose=purpose,
                thread_id=thread_id,
                categories=categories,
            ):
                self._approval_block(
                    destination_policy, destination, model, purpose, selected_mode, categories
                )
            decision_source = f"grant:{grant.id}"
        elif selected_mode is ProtectionMode.full_context:
            if not self._grant_permits(
                grant,
                mode=ProtectionMode.full_context,
                destination=destination,
                purpose=purpose,
                thread_id=thread_id,
                categories=categories,
            ):
                self._approval_block(
                    destination_policy, destination, model, purpose, selected_mode, categories
                )
            decision_source = f"grant:{grant.id}"
            exact = True
        elif grant is not None and self._grant_permits(
            grant,
            mode=ProtectionMode.full_context,
            destination=destination,
            purpose=purpose,
            thread_id=thread_id,
            categories=categories,
        ):
            decision_source = f"grant:{grant.id}"
            exact = True

        replacements: list[Replacement] = []
        outbound_messages = tuple(messages)
        if not exact:
            scope = f"{normalized_destination}\0{purpose.casefold()}\0{thread_id}"
            outbound_messages = tuple(
                _copy_message(
                    message,
                    lambda value: self._protect_value(value, scope, replacements),
                )
                for message in messages
            )

        transformations = ("meaning_preserving_scoped_alias",) if replacements else ()
        receipt_id = uuid4().hex
        policy_flags = self._policy_flags(destination_policy)
        prepared = PreparedDisclosure(
            messages=outbound_messages,
            replacements=tuple(_dedupe_replacements(replacements)),
            receipt_id=receipt_id,
            destination=destination_policy.name,
            endpoint=destination_policy.endpoint,
            model=model,
            purpose=purpose,
            mode=selected_mode,
            categories=tuple(sorted(categories)),
            transformations=transformations,
            decision_source=decision_source,
            policy_flags=MappingProxyType(policy_flags),
        )
        self._write_receipt(prepared, outcome="authorized")
        return prepared

    def complete(self, prepared: PreparedDisclosure, *, outcome: str) -> None:
        self._write_receipt(prepared, outcome=outcome)

    def _analyze_messages(self, messages: Sequence[Any]) -> list[PIIDetection]:
        detections: list[PIIDetection] = []
        for message in messages:
            for value in _message_values(message):
                detections.extend(self.scrubber.analyze(value))
        return detections

    def _protect_value(
        self,
        value: Any,
        scope: str,
        replacements: list[Replacement],
    ) -> Any:
        if isinstance(value, str):
            clean, found = self.scrubber.scrub(value)
            for item in found:
                token = self._alias(scope=scope, label=item.label, value=item.value)
                clean = clean.replace(item.token, token)
                replacements.append(Replacement(item.label, item.value, token))
            return clean
        if isinstance(value, list):
            return [self._protect_value(item, scope, replacements) for item in value]
        if isinstance(value, tuple):
            return tuple(self._protect_value(item, scope, replacements) for item in value)
        if isinstance(value, dict):
            return {
                key: self._protect_value(item, scope, replacements)
                for key, item in value.items()
            }
        return value

    def _alias(self, *, scope: str, label: str, value: str) -> str:
        digest = hmac.new(
            self._alias_key,
            f"{scope}\0{label}\0{value.casefold()}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        natural = _natural_surrogate(label, digest, value)
        if natural is not None and natural.casefold() != value.casefold():
            return natural
        return f"[{label}_{digest.hex()[:8].upper()}]"

    @staticmethod
    def _policy_flags(destination: DestinationPolicy) -> dict[str, Any]:
        return {
            "tls": True,
            "data_collection": destination.data_collection,
            "zdr": destination.zdr,
            "prompt_logging": destination.prompt_logging,
            "response_caching": destination.response_caching,
        }

    def _grant_permits(
        self,
        grant: DisclosureGrant | None,
        *,
        mode: ProtectionMode,
        destination: str,
        purpose: str,
        thread_id: str,
        categories: frozenset[str],
    ) -> bool:
        return bool(
            grant
            and grant.permits(
                mode=mode,
                destination=destination,
                purpose=purpose,
                thread_id=thread_id,
                categories=categories,
                now=datetime.now(UTC),
            )
        )

    def _approval_block(
        self,
        destination_policy: DestinationPolicy,
        destination: str,
        model: str,
        purpose: str,
        mode: ProtectionMode,
        categories: frozenset[str],
    ) -> None:
        self._block(
            destination=destination,
            model=model,
            purpose=purpose,
            mode=mode,
            categories=categories,
            reason="approval_required",
            destination_policy=destination_policy,
        )
        raise DisclosureBlocked("external disclosure requires scoped approval")

    def _block(
        self,
        *,
        destination: str,
        model: str,
        purpose: str,
        mode: ProtectionMode,
        categories: Sequence[str],
        reason: str,
        destination_policy: DestinationPolicy | None = None,
    ) -> None:
        record = {
            "receipt_id": uuid4().hex,
            "timestamp": datetime.now(UTC).isoformat(),
            "destination": destination,
            "endpoint": destination_policy.endpoint if destination_policy else "",
            "model": model,
            "purpose": purpose,
            "mode": mode.value,
            "categories": sorted(categories),
            "transformations": [],
            "decision_source": f"policy:{reason}",
            "policy": (
                self._policy_flags(destination_policy)
                if destination_policy is not None
                else {}
            ),
            "outcome": "blocked",
        }
        self._append_receipt(record)

    def _write_receipt(self, prepared: PreparedDisclosure, *, outcome: str) -> None:
        self._append_receipt(
            {
                "receipt_id": prepared.receipt_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "destination": prepared.destination,
                "endpoint": prepared.endpoint,
                "model": prepared.model,
                "purpose": prepared.purpose,
                "mode": prepared.mode.value,
                "categories": list(prepared.categories),
                "transformations": list(prepared.transformations),
                "decision_source": prepared.decision_source,
                "policy": dict(prepared.policy_flags),
                "outcome": outcome,
            }
        )

    def _append_receipt(self, record: Mapping[str, Any]) -> None:
        path = self.policy.receipt_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(dict(record), sort_keys=True, separators=(",", ":"))
            with self._receipt_lock, path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            raise DisclosureBlocked("privacy receipt could not be recorded") from exc


@dataclass(frozen=True)
class DisclosureModelAdapter:
    """Apply disclosure policy at the last in-process seam before model I/O."""

    adapter: Any
    broker: DisclosureBroker

    @property
    def provider(self) -> str:
        return self.adapter.provider

    def build_model(self, *, target: Any, thread_id: str, **kwargs: Any) -> Any:
        model = self.adapter.build_model(target=target, **kwargs)
        return _ProtectedModel(
            model=model,
            broker=self.broker,
            destination=self.provider,
            model_id=target.model,
            thread_id=thread_id,
        )


@dataclass(frozen=True)
class _ProtectedModel:
    model: Any
    broker: DisclosureBroker
    destination: str
    model_id: str
    thread_id: str

    def bind_tools(self, tools: list[Any]) -> "_ProtectedModel":
        return _ProtectedModel(
            model=self.model.bind_tools(tools),
            broker=self.broker,
            destination=self.destination,
            model_id=self.model_id,
            thread_id=self.thread_id,
        )

    async def ainvoke(self, messages: Sequence[Any], **kwargs: Any) -> Any:
        prepared = self._prepare(messages, kwargs)
        try:
            result = await self.model.ainvoke(list(prepared.messages), **kwargs)
        except BaseException:
            self.broker.complete(prepared, outcome="failed")
            raise
        self.broker.complete(prepared, outcome="success")
        return prepared.restore_message(result)

    async def astream(
        self,
        messages: Sequence[Any],
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        prepared = self._prepare(messages, kwargs)
        restorer = _StreamRestorer(prepared)
        try:
            async for chunk in self.model.astream(list(prepared.messages), **kwargs):
                yield restorer.restore(chunk)
            trailing = restorer.flush()
            if trailing is not None:
                yield trailing
        except BaseException:
            self.broker.complete(prepared, outcome="failed")
            raise
        self.broker.complete(prepared, outcome="success")

    def _prepare(
        self,
        messages: Sequence[Any],
        kwargs: dict[str, Any],
    ) -> PreparedDisclosure:
        mode = kwargs.pop("privacy_mode", None)
        grant = kwargs.pop("disclosure_grant", None)
        purpose = kwargs.pop("disclosure_purpose", "chat")
        return self.broker.prepare_messages(
            messages,
            destination=self.destination,
            model=self.model_id,
            purpose=purpose,
            thread_id=self.thread_id,
            mode=mode,
            grant=grant,
        )


class _StreamRestorer:
    """Restore aliases while preserving tokens split across streamed chunks."""

    def __init__(self, prepared: PreparedDisclosure) -> None:
        self.prepared = prepared
        self.pending = ""
        self.last_chunk: Any | None = None
        self.tokens = tuple(item.token for item in prepared.replacements)

    def restore(self, chunk: Any) -> Any:
        self.last_chunk = chunk
        restored = self.prepared.restore_message(chunk)
        content = getattr(chunk, "content", None)
        if not isinstance(content, str) or not self.tokens:
            return restored

        combined = self.pending + content
        suffix_length = self._partial_token_suffix_length(combined)
        if suffix_length:
            visible = combined[:-suffix_length]
            self.pending = combined[-suffix_length:]
        else:
            visible = combined
            self.pending = ""
        return restored.model_copy(
            update={"content": _restore_value(visible, self.prepared.replacements)},
            deep=True,
        )

    def flush(self) -> Any | None:
        if not self.pending or self.last_chunk is None:
            return None
        content = _restore_value(self.pending, self.prepared.replacements)
        self.pending = ""
        update: dict[str, Any] = {"content": content}
        fields = getattr(self.last_chunk.__class__, "model_fields", {})
        for field_name in ("tool_calls", "tool_call_chunks"):
            if field_name in fields:
                update[field_name] = []
        return self.last_chunk.model_copy(update=update, deep=True)

    def _partial_token_suffix_length(self, value: str) -> int:
        longest = 0
        for token in self.tokens:
            upper_bound = min(len(value), len(token) - 1)
            for length in range(upper_bound, longest, -1):
                if value.endswith(token[:length]):
                    longest = length
                    break
        return longest


def _message_values(message: Any) -> list[str]:
    values: list[str] = []
    for field_name in ("content", "additional_kwargs", "tool_calls", "tool_call_chunks"):
        if hasattr(message, field_name):
            values.extend(_string_values(getattr(message, field_name)))
    return values


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for value_item in value for item in _string_values(value_item)]
    if isinstance(value, dict):
        return [item for value_item in value.values() for item in _string_values(value_item)]
    return []


def _copy_message(message: Any, transform) -> Any:
    update: dict[str, Any] = {}
    fields = getattr(message.__class__, "model_fields", {})
    for field_name in ("content", "additional_kwargs", "tool_calls", "tool_call_chunks"):
        if field_name in fields:
            update[field_name] = transform(getattr(message, field_name))
    if not update:
        return message
    return message.model_copy(update=update, deep=True)


def _restore_value(value: Any, replacements: Sequence[Replacement]) -> Any:
    if isinstance(value, str):
        restored = value
        mapping = {item.token: item.value for item in replacements}
        for token in sorted(mapping, key=len, reverse=True):
            restored = restored.replace(token, mapping[token])
        return restored
    if isinstance(value, list):
        return [_restore_value(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(_restore_value(item, replacements) for item in value)
    if isinstance(value, dict):
        return {key: _restore_value(item, replacements) for key, item in value.items()}
    return value


def _dedupe_replacements(replacements: Sequence[Replacement]) -> list[Replacement]:
    unique: dict[str, Replacement] = {}
    for item in replacements:
        unique.setdefault(item.token, item)
    return list(unique.values())
