"""App Actions over Vellum's canonical settings and LLM runtime owners."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.llm.providers import canonical_model_id
from agent.llm.routing.models import CredentialStrategy, FallbackTarget, ProviderRoutingPolicy
from agent.tools.registry import CapabilityAccess


DEFAULT_MODEL_SET_ACTION_ID = "settings.default_model.set"
DEVICE_SETTINGS_UPDATE_ACTION_ID = "settings.device.update"
MEMORY_SETTINGS_UPDATE_ACTION_ID = "memory.settings.update"
MEMORY_ENTRY_CREATE_ACTION_ID = "memory.entry.create"
MEMORY_ENTRY_UPDATE_ACTION_ID = "memory.entry.update"
MEMORY_ENTRY_PIN_ACTION_ID = "memory.entry.pin"
MEMORY_ENTRY_ARCHIVE_ACTION_ID = "memory.entry.archive"
MEMORY_ENTRY_DELETE_ACTION_ID = "memory.entry.delete"
MEMORY_DREAMING_RUN_ACTION_ID = "memory.dreaming.run"
MEMORY_CONVERSATIONS_IMPORT_ACTION_ID = "memory.conversations.import"
PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID = "provider.credential.configure"
ROUTING_POLICY_SET_ACTION_ID = "llm.routing.policy.set"
ROUTING_FALLBACKS_SET_ACTION_ID = "llm.routing.fallbacks.set"
ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID = "llm.routing.credential_strategy.set"
ROUTING_POOL_RESET_ACTION_ID = "llm.routing.pool.reset"

SETTINGS_RUNTIME_ACTION_IDS = frozenset({
    DEFAULT_MODEL_SET_ACTION_ID,
    DEVICE_SETTINGS_UPDATE_ACTION_ID,
    MEMORY_SETTINGS_UPDATE_ACTION_ID,
    MEMORY_ENTRY_CREATE_ACTION_ID,
    MEMORY_ENTRY_UPDATE_ACTION_ID,
    MEMORY_ENTRY_PIN_ACTION_ID,
    MEMORY_ENTRY_ARCHIVE_ACTION_ID,
    MEMORY_ENTRY_DELETE_ACTION_ID,
    MEMORY_DREAMING_RUN_ACTION_ID,
    MEMORY_CONVERSATIONS_IMPORT_ACTION_ID,
    PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID,
    ROUTING_POLICY_SET_ACTION_ID,
    ROUTING_FALLBACKS_SET_ACTION_ID,
    ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID,
    ROUTING_POOL_RESET_ACTION_ID,
})

CONFIRMED_SETTINGS_RUNTIME_ACTION_IDS = frozenset({
    MEMORY_SETTINGS_UPDATE_ACTION_ID,
    PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID,
    MEMORY_ENTRY_DELETE_ACTION_ID,
    MEMORY_DREAMING_RUN_ACTION_ID,
    MEMORY_CONVERSATIONS_IMPORT_ACTION_ID,
})

_MEMORY_SETTING_KEYS = frozenset({
    "memory_enabled",
    "dreaming_enabled",
    "reference_history_enabled",
    "save_new_memories",
    "auto_archive_enabled",
    "use_archived_memories",
})
_CREDENTIAL_PROVIDERS = frozenset({"openrouter", "openai", "anthropic", "google"})
_ROUTING_PROVIDERS = frozenset({"openrouter", "openai"})
_DEVICE_SETTING_KEYS = frozenset({
    "background",
    "accent",
    "dock_position",
    "dock_locked",
    "computer_use_preview",
    "personalization",
})
_PERSONALIZATION_TEXT_KEYS = frozenset({"custom", "nickname", "occupation", "about"})
_PERSONALIZATION_TOGGLE_KEYS = frozenset({
    "fastAnswers",
    "recordHist",
    "webSearch",
    "canvas",
    "voice",
    "advVoice",
    "connector",
})
_PERSONALIZATION_CHOICE_KEYS = frozenset({"baseStyle", "warm", "enthusiastic", "headers", "emoji"})


class SettingsRuntimeActionError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


class SettingsRuntimeActionService:
    """Translate settings actions without becoming a second state owner."""

    def __init__(
        self,
        *,
        memory_store_provider: Callable[[], Any],
        provider_registry_provider: Callable[[], Any],
        routing_runtime_provider: Callable[[], Any],
        credential_writer: Callable[[str, str], None],
        memory_dreaming_runner: Callable[[], dict[str, Any]],
        conversation_memory_importer: Callable[[int | None], dict[str, int]],
    ) -> None:
        self._memory_store_provider = memory_store_provider
        self._provider_registry_provider = provider_registry_provider
        self._routing_runtime_provider = routing_runtime_provider
        self._credential_writer = credential_writer
        self._memory_dreaming_runner = memory_dreaming_runner
        self._conversation_memory_importer = conversation_memory_importer

    def execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        _context: AppActionContext,
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if action_id == DEFAULT_MODEL_SET_ACTION_ID:
            return self._set_default_model(arguments)
        if action_id == DEVICE_SETTINGS_UPDATE_ACTION_ID:
            return self._update_device_settings(arguments, _context)
        if action_id == MEMORY_SETTINGS_UPDATE_ACTION_ID:
            self._require_confirmation(confirmed)
            return self._update_memory_settings(arguments)
        if action_id == MEMORY_ENTRY_CREATE_ACTION_ID:
            return self._create_memory(arguments)
        if action_id == MEMORY_ENTRY_UPDATE_ACTION_ID:
            return self._update_memory(arguments)
        if action_id == MEMORY_ENTRY_PIN_ACTION_ID:
            return self._pin_memory(arguments)
        if action_id == MEMORY_ENTRY_ARCHIVE_ACTION_ID:
            return self._archive_memory(arguments)
        if action_id == MEMORY_ENTRY_DELETE_ACTION_ID:
            self._require_confirmation(confirmed)
            return self._delete_memory(arguments)
        if action_id == MEMORY_DREAMING_RUN_ACTION_ID:
            self._require_confirmation(confirmed)
            return self._run_memory_dreaming()
        if action_id == MEMORY_CONVERSATIONS_IMPORT_ACTION_ID:
            self._require_confirmation(confirmed)
            return self._import_conversation_memories(arguments)
        if action_id == PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID:
            return self._configure_provider_credential(arguments, confirmed=confirmed)
        if action_id == ROUTING_POLICY_SET_ACTION_ID:
            return self._set_routing_policy(arguments)
        if action_id == ROUTING_FALLBACKS_SET_ACTION_ID:
            return self._set_fallbacks(arguments)
        if action_id == ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID:
            return self._set_credential_strategy(arguments)
        if action_id == ROUTING_POOL_RESET_ACTION_ID:
            return self._reset_credential_pool(arguments)
        raise SettingsRuntimeActionError(
            "ACTION_UNAVAILABLE",
            f"{action_id} is unavailable.",
            unavailable=True,
        )

    @staticmethod
    def _require_confirmation(confirmed: bool) -> None:
        if not confirmed:
            raise SettingsRuntimeActionError(
                "CONFIRMATION_REQUIRED",
                "Confirm this settings change before it is applied.",
            )

    def _set_default_model(self, arguments: dict[str, Any]) -> dict[str, Any]:
        requested = str(arguments.get("model_id") or arguments.get("model") or "").strip()
        if not requested:
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "model is required")
        registry = self._provider_registry_provider()
        previous = registry.current_model()
        try:
            selected = registry.set_active(requested)
        except ValueError as exc:
            raise SettingsRuntimeActionError("MODEL_UNAVAILABLE", str(exc), unavailable=True) from exc
        return {
            "changed": previous.id != selected.id,
            "model": self._public_model(selected),
            "previous_model_id": previous.id,
            "_target_kind": "application_setting",
            "_target_id": "default-model",
            "_message": f"Default model set to {selected.label}.",
        }

    def _update_device_settings(
        self,
        arguments: dict[str, Any],
        context: AppActionContext,
    ) -> dict[str, Any]:
        raw_patch = arguments.get("patch")
        patch = dict(raw_patch) if isinstance(raw_patch, dict) else dict(arguments)
        if not patch:
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "At least one device setting is required.")
        unknown = set(patch) - _DEVICE_SETTING_KEYS
        if unknown:
            raise SettingsRuntimeActionError(
                "INVALID_ACTION_ARGUMENTS",
                "Unknown device setting: " + ", ".join(sorted(unknown)),
            )
        normalized = self._validate_device_patch(patch)
        snapshot = context.device_settings if isinstance(context.device_settings, dict) else {}
        version = int(snapshot.get("version") or 1)
        revision = int(snapshot.get("revision") or 0)
        current = dict(snapshot.get("values") or {})
        next_values = dict(current)
        for key, value in normalized.items():
            if key == "personalization":
                next_values[key] = {**dict(current.get(key) or {}), **value}
            else:
                next_values[key] = value
        changed = next_values != current
        next_revision = revision + (1 if changed else 0)
        changed_values = {
            key: next_values[key]
            for key in normalized
            if key != "personalization" and current.get(key) != next_values[key]
        }
        if "personalization" in normalized:
            changed_personalization = {
                key: value
                for key, value in normalized["personalization"].items()
                if dict(current.get("personalization") or {}).get(key) != value
            }
            if changed_personalization:
                changed_values["personalization"] = changed_personalization
        return {
            "changed": changed,
            "device_settings_patch": {
                "version": version,
                "base_revision": revision,
                "revision": next_revision,
                "values": changed_values,
            },
            "_target_kind": "device_setting",
            "_target_id": context.device_id,
            "_message": "Device settings updated." if changed else "Device settings were already set.",
        }

    @staticmethod
    def _validate_device_patch(patch: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in patch.items():
            if key in {"dock_locked", "computer_use_preview"}:
                if not isinstance(value, bool):
                    raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", f"{key} must be true or false")
                normalized[key] = value
            elif key == "dock_position":
                position = str(value or "").strip().casefold()
                if position not in {"auto", "top", "right", "bottom", "left"}:
                    raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "Unsupported dock position.")
                normalized[key] = position
            elif key == "accent":
                accent = str(value or "").strip().casefold()
                if accent not in {
                    "default", "blue-eclipse", "winter-chill", "autumn-leaves", "eucalyptus",
                    "frozen-lake", "siltstone", "moonlight", "quiet-luxury", "neon-noir",
                    "cool-revival", "matrix",
                }:
                    raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "Unsupported accent palette.")
                normalized[key] = accent
            elif key == "background":
                background = str(value or "").strip().casefold()
                if background not in {
                    "galaxy", "liquid-metal", "drifting-clouds", "god-rays", "grain-pastel",
                    "rocket-blast", "ember-clouds", "teal-horizon", "serenox-home",
                }:
                    raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "Unsupported background.")
                normalized[key] = background
            elif key == "personalization":
                if not isinstance(value, dict) or not value:
                    raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "personalization must be a non-empty object")
                allowed = _PERSONALIZATION_TEXT_KEYS | _PERSONALIZATION_TOGGLE_KEYS | _PERSONALIZATION_CHOICE_KEYS
                unknown = set(value) - allowed
                if unknown:
                    raise SettingsRuntimeActionError(
                        "INVALID_ACTION_ARGUMENTS",
                        "Unknown personalization setting: " + ", ".join(sorted(unknown)),
                    )
                personal: dict[str, Any] = {}
                for personal_key, personal_value in value.items():
                    if personal_key in _PERSONALIZATION_TOGGLE_KEYS:
                        if not isinstance(personal_value, bool):
                            raise SettingsRuntimeActionError(
                                "INVALID_ACTION_ARGUMENTS",
                                f"{personal_key} must be true or false",
                            )
                        personal[personal_key] = personal_value
                    else:
                        text = str(personal_value or "").strip() if personal_key not in _PERSONALIZATION_TEXT_KEYS else str(personal_value or "")
                        if personal_key == "baseStyle" and text not in {
                            "default", "professional", "friendly", "candid", "quirky", "efficient", "cynical",
                        }:
                            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "Unsupported base style.")
                        if personal_key in {"warm", "enthusiastic", "headers", "emoji"} and text not in {
                            "more", "default", "less",
                        }:
                            raise SettingsRuntimeActionError(
                                "INVALID_ACTION_ARGUMENTS",
                                f"{personal_key} must be more, default, or less",
                            )
                        limit = 4000 if personal_key == "custom" else 500
                        if len(text) > limit:
                            raise SettingsRuntimeActionError(
                                "INVALID_ACTION_ARGUMENTS",
                                f"{personal_key} is too long",
                            )
                        personal[personal_key] = text
                normalized[key] = personal
        return normalized

    def _update_memory_settings(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_patch = arguments.get("patch")
        patch = dict(raw_patch) if isinstance(raw_patch, dict) else {
            key: value for key, value in arguments.items() if key in _MEMORY_SETTING_KEYS
        }
        if not patch:
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "At least one memory setting is required.")
        unknown = set(patch) - _MEMORY_SETTING_KEYS
        if unknown:
            raise SettingsRuntimeActionError(
                "INVALID_ACTION_ARGUMENTS",
                "Unknown memory setting: " + ", ".join(sorted(unknown)),
            )
        invalid = [key for key, value in patch.items() if not isinstance(value, bool)]
        if invalid:
            raise SettingsRuntimeActionError(
                "INVALID_ACTION_ARGUMENTS",
                "Memory settings must be true or false: " + ", ".join(sorted(invalid)),
            )
        store = self._memory_store_provider()
        if store is None:
            raise SettingsRuntimeActionError(
                "MEMORY_SETTINGS_UNAVAILABLE",
                "Memory settings are unavailable.",
                unavailable=True,
            )
        previous = dict(store.get_settings())
        changed_patch = {key: value for key, value in patch.items() if previous.get(key) != value}
        settings = dict(store.update_settings(changed_patch)) if changed_patch else previous
        return {
            "changed": bool(changed_patch),
            "settings": settings,
            "changed_keys": sorted(changed_patch),
            "_target_kind": "user_setting",
            "_target_id": "memory",
            "_message": "Memory settings updated." if changed_patch else "Memory settings were already set.",
        }

    def _memory_store(self) -> Any:
        store = self._memory_store_provider()
        if store is None:
            raise SettingsRuntimeActionError(
                "MEMORY_UNAVAILABLE",
                "Memory is unavailable.",
                unavailable=True,
            )
        return store

    def _create_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        text = str(arguments.get("text") or "").strip()
        if not text:
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "memory text is required")
        store = self._memory_store()
        memory_id = store.save_memory(
            kind=str(arguments.get("kind") or "manual").strip() or "manual",
            text=text,
            source_thread_id=str(arguments.get("source_thread_id") or "manual").strip() or "manual",
            confidence=float(arguments.get("confidence", 1.0)),
            scope=str(arguments.get("scope") or "global").strip() or "global",
        )
        return {
            "changed": True,
            "memory": store.get_memory(memory_id),
            "_target_kind": "memory_entry",
            "_target_id": str(memory_id),
            "_message": "Memory saved.",
        }

    def _update_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = self._memory_id(arguments)
        text = arguments.get("text")
        kind = arguments.get("kind")
        if text is None and kind is None:
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "text or kind is required")
        try:
            memory = self._memory_store().update(
                memory_id,
                text=str(text).strip() if text is not None else None,
                kind=str(kind).strip() if kind is not None else None,
            )
        except KeyError as exc:
            raise SettingsRuntimeActionError("MEMORY_NOT_FOUND", "Memory not found.", unavailable=True) from exc
        except ValueError as exc:
            raise SettingsRuntimeActionError("MEMORY_UPDATE_CONFLICT", str(exc)) from exc
        return {
            "changed": True,
            "memory": memory,
            "_target_kind": "memory_entry",
            "_target_id": str(memory_id),
            "_message": "Memory updated.",
        }

    def _pin_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = self._memory_id(arguments)
        pinned = arguments.get("pinned")
        if not isinstance(pinned, bool):
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "pinned must be true or false")
        try:
            memory = self._memory_store().pin(memory_id, pinned)
        except KeyError as exc:
            raise SettingsRuntimeActionError("MEMORY_NOT_FOUND", "Memory not found.", unavailable=True) from exc
        return {
            "changed": True,
            "memory": memory,
            "_target_kind": "memory_entry",
            "_target_id": str(memory_id),
            "_message": "Memory pinned." if pinned else "Memory unpinned.",
        }

    def _archive_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = self._memory_id(arguments)
        try:
            memory = self._memory_store().archive(memory_id)
        except KeyError as exc:
            raise SettingsRuntimeActionError("MEMORY_NOT_FOUND", "Memory not found.", unavailable=True) from exc
        return {
            "changed": True,
            "memory": memory,
            "_target_kind": "memory_entry",
            "_target_id": str(memory_id),
            "_message": "Memory archived.",
        }

    def _delete_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = self._memory_id(arguments)
        try:
            self._memory_store().delete(memory_id)
        except KeyError as exc:
            raise SettingsRuntimeActionError("MEMORY_NOT_FOUND", "Memory not found.", unavailable=True) from exc
        except ValueError as exc:
            raise SettingsRuntimeActionError("MEMORY_DELETE_CONFLICT", str(exc)) from exc
        return {
            "changed": True,
            "deleted": True,
            "memory_id": memory_id,
            "_target_kind": "memory_entry",
            "_target_id": str(memory_id),
            "_message": "Memory deleted.",
        }

    def _run_memory_dreaming(self) -> dict[str, Any]:
        try:
            result = dict(self._memory_dreaming_runner() or {})
        except (OSError, RuntimeError, ValueError) as exc:
            raise SettingsRuntimeActionError("MEMORY_DREAMING_FAILED", "Memory dreaming failed.") from exc
        counts = {
            key: len(result.get(key) or [])
            for key in ("new_memories", "updated_memories", "archived_memories", "contradictions")
        }
        imported = dict(result.get("conversation_import") or {})
        if imported:
            counts["imported_conversation_turns"] = int(imported.get("indexed_turns") or 0)
        return {
            "changed": any(counts.values()),
            "counts": counts,
            "completed": True,
            "_target_kind": "memory_runtime",
            "_target_id": "dreaming",
            "_message": "Memory dreaming completed.",
        }

    def _import_conversation_memories(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_limit = arguments.get("limit")
        limit = None
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError) as exc:
                raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "limit must be an integer") from exc
            if limit < 1 or limit > 100_000:
                raise SettingsRuntimeActionError(
                    "INVALID_ACTION_ARGUMENTS",
                    "limit must be between 1 and 100000",
                )
        try:
            result = dict(self._conversation_memory_importer(limit) or {})
        except (OSError, RuntimeError, ValueError) as exc:
            raise SettingsRuntimeActionError("MEMORY_IMPORT_FAILED", "Conversation import failed.") from exc
        counts = {
            key: int(result.get(key) or 0)
            for key in ("indexed_turns", "skipped_turns", "scanned_turns")
        }
        return {
            "changed": counts["indexed_turns"] > 0,
            "counts": counts,
            "_target_kind": "memory_runtime",
            "_target_id": "conversation-import",
            "_message": "Conversation memories imported.",
        }

    @staticmethod
    def _memory_id(arguments: dict[str, Any]) -> int:
        raw = arguments.get("memory_id", arguments.get("id"))
        try:
            memory_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "memory_id must be an integer") from exc
        if memory_id < 1:
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "memory_id must be positive")
        return memory_id

    def _configure_provider_credential(
        self,
        arguments: dict[str, Any],
        *,
        confirmed: bool,
    ) -> dict[str, Any]:
        provider = self._credential_provider(arguments)
        secret = str(arguments.get("secret") or arguments.get("api_key") or "").strip()
        if not secret:
            return {
                "changed": False,
                "provider": provider,
                "configured": False,
                "client_effect": {
                    "type": "settings.open",
                    "tab": "configuration",
                    "focus": f"provider-key-{provider}",
                },
                "_target_kind": "application_setting",
                "_target_id": f"provider-credential:{provider}",
                "_message": f"Open Settings to enter the {provider} key securely.",
            }
        self._require_confirmation(confirmed)
        try:
            self._credential_writer(provider, secret)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SettingsRuntimeActionError(
                "PROVIDER_CREDENTIAL_SAVE_FAILED",
                "The provider credential could not be saved.",
            ) from exc
        return {
            "changed": True,
            "provider": provider,
            "configured": True,
            "_target_kind": "application_credential",
            "_target_id": f"provider-credential:{provider}",
            "_message": f"{provider} credential configured.",
        }

    def _set_routing_policy(self, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime = self._routing_runtime_provider()
        current = runtime.store.get_global_policy()
        values = current.model_dump()
        allowed = {"sort", "only", "ignore", "order", "require_parameters", "allow_fallbacks"}
        patch = arguments.get("patch") if isinstance(arguments.get("patch"), dict) else arguments
        unknown = set(patch) - allowed
        if unknown:
            raise SettingsRuntimeActionError(
                "INVALID_ACTION_ARGUMENTS",
                "Unknown routing setting: " + ", ".join(sorted(unknown)),
            )
        values.update({key: value for key, value in patch.items() if key in allowed})
        values["data_collection"] = "deny"
        values["zdr"] = True
        try:
            policy = ProviderRoutingPolicy.model_validate(values)
        except ValueError as exc:
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", str(exc)) from exc
        changed = policy != current
        if changed:
            runtime.store.set_global_policy(policy)
        return {
            "changed": changed,
            "global_policy": policy.model_dump(mode="json"),
            "_target_kind": "llm_routing",
            "_target_id": "global-policy",
            "_message": "Provider routing updated." if changed else "Provider routing was already set.",
        }

    def _set_fallbacks(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_models = arguments.get("models")
        if not isinstance(raw_models, list):
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "models must be a list")
        models = [canonical_model_id(str(model).strip()) for model in raw_models if str(model).strip()]
        if len(models) != len(set(model.casefold() for model in models)):
            raise SettingsRuntimeActionError("INVALID_ACTION_ARGUMENTS", "Fallback models must be unique.")
        runtime = self._routing_runtime_provider()
        previous = runtime.store.list_fallbacks()
        targets = [FallbackTarget(provider="openrouter", model=model) for model in models]
        changed = [item.identity for item in previous] != [item.identity for item in targets]
        if changed:
            runtime.store.replace_fallbacks(targets)
        return {
            "changed": changed,
            "fallbacks": [item.model_dump(mode="json") for item in runtime.store.list_fallbacks()],
            "_target_kind": "llm_routing",
            "_target_id": "fallbacks",
            "_message": "Model fallbacks updated." if changed else "Model fallbacks were already set.",
        }

    def _set_credential_strategy(self, arguments: dict[str, Any]) -> dict[str, Any]:
        provider = self._routing_provider(arguments)
        raw_strategy = str(arguments.get("strategy") or "").strip().casefold().replace("-", "_").replace(" ", "_")
        try:
            strategy = CredentialStrategy(raw_strategy)
        except ValueError as exc:
            raise SettingsRuntimeActionError(
                "INVALID_ACTION_ARGUMENTS",
                "strategy must be fill_first, round_robin, least_used, or random",
            ) from exc
        runtime = self._routing_runtime_provider()
        previous = runtime.store.get_pool_state(provider)[0]
        changed = previous != strategy
        if changed:
            runtime.pool.set_strategy(provider, strategy)
        return {
            "changed": changed,
            "provider": provider,
            "strategy": strategy.value,
            "_target_kind": "llm_routing",
            "_target_id": f"credential-strategy:{provider}",
            "_message": f"{provider} credential strategy set to {strategy.value}.",
        }

    def _reset_credential_pool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        provider = self._routing_provider(arguments)
        self._routing_runtime_provider().pool.reset_provider(provider)
        return {
            "changed": True,
            "provider": provider,
            "reset": True,
            "_target_kind": "llm_routing",
            "_target_id": f"credential-pool:{provider}",
            "_message": f"{provider} credential pool reset.",
        }

    @staticmethod
    def _public_model(entry: Any) -> dict[str, Any]:
        return {
            "id": entry.id,
            "label": entry.label,
            "provider": entry.provider,
            "open_weights": bool(entry.open_weights),
        }

    @staticmethod
    def _credential_provider(arguments: dict[str, Any]) -> str:
        provider = str(arguments.get("provider") or "").strip().casefold().replace("-", "_")
        if provider not in _CREDENTIAL_PROVIDERS:
            raise SettingsRuntimeActionError(
                "PROVIDER_UNAVAILABLE",
                f"{provider or 'That provider'} is not supported for credential configuration.",
                unavailable=True,
            )
        return provider

    @staticmethod
    def _routing_provider(arguments: dict[str, Any]) -> str:
        provider = str(arguments.get("provider") or "openrouter").strip().casefold()
        if provider not in _ROUTING_PROVIDERS:
            raise SettingsRuntimeActionError(
                "PROVIDER_UNAVAILABLE",
                f"{provider or 'That provider'} does not have a credential pool.",
                unavailable=True,
            )
        return provider


def settings_runtime_action_definitions() -> list[AppActionDefinition]:
    specs = [
        (
            DEVICE_SETTINGS_UPDATE_ACTION_ID,
            "Update device settings",
            "Update device-local appearance, personalization, or preview controls.",
            "device",
            "none",
            {
                "patch": {"type": "object"},
                "background": {"type": "string"},
                "accent": {"type": "string"},
                "dock_position": {"type": "string"},
                "dock_locked": {"type": "boolean"},
                "computer_use_preview": {"type": "boolean"},
                "personalization": {"type": "object"},
            },
            "settings-device",
        ),
        (
            DEFAULT_MODEL_SET_ACTION_ID,
            "Set the default model",
            "Set the process default model without changing an existing chat override.",
            "process",
            "none",
            {"model": {"type": "string"}, "model_id": {"type": "string"}},
            "settings-model",
        ),
        (
            MEMORY_SETTINGS_UPDATE_ACTION_ID,
            "Update memory privacy settings",
            "Update user-wide memory, history, dreaming, saving, and archive behavior.",
            "user",
            "operation_bound",
            {
                "patch": {"type": "object"},
                **{key: {"type": "boolean"} for key in sorted(_MEMORY_SETTING_KEYS)},
            },
            "settings-memory",
        ),
        (
            MEMORY_ENTRY_CREATE_ACTION_ID,
            "Save a memory",
            "Save an explicit user memory through the canonical memory store.",
            "user",
            "none",
            {"text": {"type": "string"}, "kind": {"type": "string"}, "scope": {"type": "string"}, "source_thread_id": {"type": "string"}, "confidence": {"type": "number"}},
            "settings-memory",
        ),
        (
            MEMORY_ENTRY_UPDATE_ACTION_ID,
            "Update a memory",
            "Update the text or kind of a saved memory.",
            "user",
            "none",
            {"memory_id": {"type": "integer"}, "text": {"type": "string"}, "kind": {"type": "string"}},
            "settings-memory",
        ),
        (
            MEMORY_ENTRY_PIN_ACTION_ID,
            "Pin a memory",
            "Pin or unpin a saved memory.",
            "user",
            "none",
            {"memory_id": {"type": "integer"}, "pinned": {"type": "boolean"}},
            "settings-memory",
        ),
        (
            MEMORY_ENTRY_ARCHIVE_ACTION_ID,
            "Archive a memory",
            "Move a saved memory to the memory archive.",
            "user",
            "none",
            {"memory_id": {"type": "integer"}},
            "settings-memory",
        ),
        (
            MEMORY_ENTRY_DELETE_ACTION_ID,
            "Delete a memory",
            "Permanently delete a saved or archived memory after confirmation.",
            "user",
            "operation_bound",
            {"memory_id": {"type": "integer"}},
            "settings-memory",
        ),
        (
            MEMORY_DREAMING_RUN_ACTION_ID,
            "Run memory dreaming",
            "Consolidate recent conversations into durable memories without returning memory content.",
            "user",
            "operation_bound",
            {},
            "memory-dreaming",
        ),
        (
            MEMORY_CONVERSATIONS_IMPORT_ACTION_ID,
            "Import conversation memories",
            "Index existing local conversation turns into memory without returning their content.",
            "user",
            "operation_bound",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 100000}},
            "memory-import",
        ),
        (
            PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID,
            "Configure a provider credential",
            "Open the secure credential control or save a credential entered there. Secrets are never returned.",
            "device",
            "operation_bound",
            {
                "provider": {"type": "string"},
                "secret": {"type": "string", "writeOnly": True},
                "api_key": {"type": "string", "writeOnly": True},
            },
            "settings-provider-credentials",
        ),
        (
            ROUTING_POLICY_SET_ACTION_ID,
            "Set provider routing",
            "Update the global provider routing policy while preserving Vellum's privacy floor.",
            "process",
            "none",
            {
                "sort": {"enum": ["price", "latency", "throughput", None]},
                "only": {"type": ["array", "null"], "items": {"type": "string"}},
                "ignore": {"type": ["array", "null"], "items": {"type": "string"}},
                "order": {"type": ["array", "null"], "items": {"type": "string"}},
                "require_parameters": {"type": ["boolean", "null"]},
                "allow_fallbacks": {"type": ["boolean", "null"]},
            },
            "settings-routing",
        ),
        (
            ROUTING_FALLBACKS_SET_ACTION_ID,
            "Set model fallbacks",
            "Replace the ordered OpenRouter model fallback chain.",
            "process",
            "none",
            {"models": {"type": "array", "items": {"type": "string"}}},
            "settings-routing",
        ),
        (
            ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID,
            "Set credential strategy",
            "Set how a provider credential pool chooses credentials.",
            "process",
            "none",
            {
                "provider": {"enum": sorted(_ROUTING_PROVIDERS)},
                "strategy": {"enum": [item.value for item in CredentialStrategy]},
            },
            "settings-routing",
        ),
        (
            ROUTING_POOL_RESET_ACTION_ID,
            "Reset a credential pool",
            "Clear transient health and cooldown state for a provider credential pool.",
            "process",
            "none",
            {"provider": {"enum": sorted(_ROUTING_PROVIDERS)}},
            "settings-routing",
        ),
    ]
    return [
        AppActionDefinition(
            id=action_id,
            version="1",
            owner="settings-runtime",
            title=title,
            description=description,
            scope=scope,
            access_class=CapabilityAccess.WRITE.value,
            confirmation_rule=confirmation,
            executor_location="server_and_client" if action_id == PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID else "server",
            supports_undo=False,
            idempotent=action_id != ROUTING_POOL_RESET_ACTION_ID,
            argument_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
            },
            result_schema={"type": "object", "required": ["changed"]},
            ui_reference=ui_reference,
            audit_label=action_id,
        )
        for action_id, title, description, scope, confirmation, properties, ui_reference in specs
    ]
