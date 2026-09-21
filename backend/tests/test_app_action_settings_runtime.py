from datetime import datetime, timezone
from types import SimpleNamespace

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.app_actions.settings_runtime import (
    DEFAULT_MODEL_SET_ACTION_ID,
    DEVICE_SETTINGS_UPDATE_ACTION_ID,
    MEMORY_SETTINGS_UPDATE_ACTION_ID,
    MEMORY_ENTRY_CREATE_ACTION_ID,
    MEMORY_ENTRY_DELETE_ACTION_ID,
    MEMORY_ENTRY_PIN_ACTION_ID,
    MEMORY_DREAMING_RUN_ACTION_ID,
    MEMORY_CONVERSATIONS_IMPORT_ACTION_ID,
    PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID,
    ROUTING_CREDENTIAL_ADD_ACTION_ID,
    ROUTING_CREDENTIAL_REMOVE_ACTION_ID,
    ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID,
    ROUTING_FALLBACKS_SET_ACTION_ID,
    ROUTING_POLICY_SET_ACTION_ID,
    ROUTING_MODEL_POLICY_REMOVE_ACTION_ID,
    ROUTING_MODEL_POLICY_SET_ACTION_ID,
    ROUTING_POOL_RESET_ACTION_ID,
    SettingsRuntimeActionService,
)
from agent.llm.routing.models import CredentialRecord, CredentialStrategy, ProviderRoutingPolicy


class FakeMemoryStore:
    def __init__(self) -> None:
        self.settings = {
            "memory_enabled": True,
            "dreaming_enabled": False,
            "reference_history_enabled": True,
            "save_new_memories": True,
            "auto_archive_enabled": True,
            "use_archived_memories": False,
        }
        self.update_calls = []
        self.memories = {}
        self.next_id = 1

    def get_settings(self):
        return dict(self.settings)

    def update_settings(self, patch):
        self.update_calls.append(dict(patch))
        self.settings.update(patch)
        return dict(self.settings)

    def save_memory(self, *, kind, text, source_thread_id, confidence, scope):
        memory_id = self.next_id
        self.next_id += 1
        self.memories[memory_id] = {
            "id": memory_id, "kind": kind, "text": text, "source_thread_id": source_thread_id,
            "confidence": confidence, "scope": scope, "pinned": False, "archived": False,
        }
        return memory_id

    def get_memory(self, memory_id):
        return dict(self.memories[memory_id])

    def update(self, memory_id, *, text=None, kind=None):
        if memory_id not in self.memories:
            raise KeyError(memory_id)
        if text is not None:
            self.memories[memory_id]["text"] = text
        if kind is not None:
            self.memories[memory_id]["kind"] = kind
        return self.get_memory(memory_id)

    def pin(self, memory_id, pinned):
        if memory_id not in self.memories:
            raise KeyError(memory_id)
        self.memories[memory_id]["pinned"] = pinned
        return self.get_memory(memory_id)

    def archive(self, memory_id):
        if memory_id not in self.memories:
            raise KeyError(memory_id)
        self.memories[memory_id]["archived"] = True
        return self.get_memory(memory_id)

    def delete(self, memory_id):
        if memory_id not in self.memories:
            raise KeyError(memory_id)
        del self.memories[memory_id]


class FakeProviderRegistry:
    def __init__(self) -> None:
        self.models = {
            "google/gemma-4-31b-it": SimpleNamespace(
                id="google/gemma-4-31b-it",
                label="Gemma 4 31B",
                provider="google",
                open_weights=True,
            ),
            "openai/gpt-5.6-sol": SimpleNamespace(
                id="openai/gpt-5.6-sol",
                label="GPT-5.6 Sol",
                provider="openai",
                open_weights=False,
            ),
        }
        self.active = self.models["google/gemma-4-31b-it"]

    def current_model(self):
        return self.active

    def set_active(self, query):
        normalized = str(query).casefold()
        entry = next(
            (
                item
                for item in self.models.values()
                if normalized in {item.id.casefold(), item.label.casefold()}
            ),
            None,
        )
        if entry is None:
            raise ValueError(f"Unknown model: {query}")
        self.active = entry
        return entry


class FakeRoutingStore:
    def __init__(self) -> None:
        self.policy = ProviderRoutingPolicy(sort="price", allow_fallbacks=True)
        self.fallbacks = []
        self.strategies = {"openrouter": CredentialStrategy.fill_first, "openai": CredentialStrategy.fill_first}
        self.model_policies = {}

    def get_global_policy(self):
        return self.policy

    def set_global_policy(self, policy):
        self.policy = policy

    def get_model_policy(self, model_id):
        return self.model_policies.get(model_id)

    def set_model_policy(self, model_id, policy):
        self.model_policies[model_id] = policy

    def delete_model_policy(self, model_id):
        return self.model_policies.pop(model_id, None) is not None

    def list_fallbacks(self):
        return list(self.fallbacks)

    def replace_fallbacks(self, targets):
        self.fallbacks = list(targets)

    def get_pool_state(self, provider):
        return self.strategies[provider], 0


class FakeRoutingPool:
    def __init__(self, store) -> None:
        self.store = store
        self.resets = []

    def set_strategy(self, provider, strategy):
        self.store.strategies[provider] = strategy

    def reset_provider(self, provider):
        self.resets.append(provider)
        return 1


class FakeRoutingSecrets:
    def __init__(self) -> None:
        self.records = {}

    def add_manual(self, provider, label, secret):
        record = CredentialRecord(
            id="credential-1",
            provider=provider,
            label=label,
            source="manual",
            fingerprint="0123456789abcdef0123456789abcdef",
        )
        self.records[record.id] = (record, secret)
        return record

    def remove_manual(self, credential_id):
        if credential_id not in self.records:
            raise KeyError(credential_id)
        del self.records[credential_id]


def make_runtime():
    memory = FakeMemoryStore()
    providers = FakeProviderRegistry()
    routing_store = FakeRoutingStore()
    routing = SimpleNamespace(
        store=routing_store,
        pool=FakeRoutingPool(routing_store),
        secrets=FakeRoutingSecrets(),
    )
    written_credentials = []
    maintenance_calls = []
    service = SettingsRuntimeActionService(
        memory_store_provider=lambda: memory,
        memory_creator=lambda **values: (
            memory.save_memory(**values) and memory.get_memory(max(memory.memories))
        ),
        provider_registry_provider=lambda: providers,
        routing_runtime_provider=lambda: routing,
        credential_writer=lambda provider, secret: written_credentials.append((provider, secret)),
        memory_dreaming_runner=lambda: maintenance_calls.append("dream") or {
            "new_memories": [{"text": "private memory text"}],
            "updated_memories": [],
            "archived_memories": [],
            "contradictions": [],
            "conversation_import": {"indexed_turns": 2},
        },
        conversation_memory_importer=lambda limit: maintenance_calls.append(("import", limit)) or {
            "indexed_turns": 3,
            "skipped_turns": 1,
            "scanned_turns": 4,
        },
        obsidian_memory_importer=lambda: {"imported_count": 0, "skipped_count": 0},
    )
    runtime = AppActionRuntime(
        clock=lambda: datetime(2026, 9, 18, tzinfo=timezone.utc),
        confirmation_token_factory=lambda: "confirm-setting",
        settings_runtime_handler=service.execute,
    )
    return runtime, memory, providers, routing, written_credentials, maintenance_calls


def context(source="nlp"):
    return AppActionContext(source=source, invocation_conversation_id="chat-1")


def test_matcher_distinguishes_global_settings_from_chat_and_casual_questions() -> None:
    runtime, *_ = make_runtime()

    assert runtime.match_submission("set the default model to GPT-5.6 Sol").action_id == DEFAULT_MODEL_SET_ACTION_ID
    assert runtime.match_submission("set the accent palette to Blue Eclipse").arguments == {
        "patch": {"accent": "blue-eclipse"}
    }
    assert runtime.match_submission("change the background to Gold Rays").arguments == {
        "patch": {"background": "god-rays"}
    }
    assert runtime.match_submission("set warmth to More").arguments == {
        "patch": {"personalization": {"warm": "more"}}
    }
    assert runtime.match_submission("turn web search off").arguments == {
        "patch": {"personalization": {"webSearch": False}}
    }
    assert runtime.match_submission("enable computer use preview").arguments == {
        "patch": {"computer_use_preview": True}
    }
    assert runtime.match_submission("enable computer use") is None
    assert runtime.match_submission("turn memory off everywhere").arguments == {"patch": {"memory_enabled": False}}
    assert runtime.match_submission("turn reference history off").action_id == MEMORY_SETTINGS_UPDATE_ACTION_ID
    assert runtime.match_submission("remember that I prefer short answers").action_id == MEMORY_ENTRY_CREATE_ACTION_ID
    assert runtime.match_submission("pin memory 12").arguments == {"memory_id": 12, "pinned": True}
    assert runtime.match_submission("delete memory 12").action_id == MEMORY_ENTRY_DELETE_ACTION_ID
    assert runtime.match_submission("run memory dreaming").action_id == MEMORY_DREAMING_RUN_ACTION_ID
    assert runtime.match_submission("import old chats into memory").action_id == MEMORY_CONVERSATIONS_IMPORT_ACTION_ID
    assert runtime.match_submission("set OpenRouter API key to secret-value").arguments == {"provider": "openrouter"}
    assert runtime.match_submission("sort providers by latency").arguments == {"sort": "latency"}
    assert runtime.match_submission("set model fallbacks to alpha/model, beta/model").arguments == {
        "models": ["alpha/model", "beta/model"]
    }
    assert runtime.match_submission("what is the best default model?") is None
    assert runtime.match_submission("what do you remember about me?") is None


def test_default_model_uses_process_registry_not_chat_state() -> None:
    runtime, _memory, providers, _routing, _credentials, _maintenance = make_runtime()

    receipt = runtime.dispatch(
        AppActionRequest(action_id=DEFAULT_MODEL_SET_ACTION_ID, arguments={"model": "GPT-5.6 Sol"}),
        context(),
    )

    assert receipt.status == "applied"
    assert receipt.target.kind == "application_setting"
    assert receipt.result["model"]["id"] == "openai/gpt-5.6-sol"
    assert providers.current_model().id == "openai/gpt-5.6-sol"


def test_device_settings_return_revisioned_patch_for_client_owned_persistence() -> None:
    runtime, *_ = make_runtime()
    action_context = context("ui").model_copy(update={
        "device_settings": {
            "version": 1,
            "revision": 4,
            "values": {"accent": "default", "personalization": {"warm": "default"}},
        }
    })

    receipt = runtime.dispatch(
        AppActionRequest(
            action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
            arguments={"patch": {"accent": "blue-eclipse", "personalization": {"warm": "more"}}},
        ),
        action_context,
    )

    assert receipt.status == "applied"
    assert receipt.target.kind == "device_setting"
    assert receipt.result["device_settings_patch"] == {
        "version": 1,
        "base_revision": 4,
        "revision": 5,
        "values": {"accent": "blue-eclipse", "personalization": {"warm": "more"}},
    }


def test_device_settings_advance_context_between_actions_in_one_turn() -> None:
    runtime, *_ = make_runtime()
    action_context = context("ui").model_copy(update={
        "device_settings": {
            "version": 1,
            "revision": 4,
            "values": {"accent": "default", "personalization": {"warm": "default"}},
        }
    })

    receipts = runtime.dispatch_many(
        [
            AppActionRequest(
                action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {"accent": "blue-eclipse"}},
            ),
            AppActionRequest(
                action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {"personalization": {"warm": "more"}}},
            ),
        ],
        action_context,
    )

    assert [receipt.result["device_settings_patch"]["base_revision"] for receipt in receipts] == [4, 5]
    assert [receipt.result["device_settings_patch"]["revision"] for receipt in receipts] == [5, 6]


def test_memory_privacy_change_requires_confirmation_and_persists_to_memory_owner() -> None:
    runtime, memory, *_ = make_runtime()
    request = AppActionRequest(
        action_id=MEMORY_SETTINGS_UPDATE_ACTION_ID,
        arguments={"patch": {"memory_enabled": False, "reference_history_enabled": False}},
    )

    pending = runtime.dispatch(request, context())

    assert pending.status == "confirmation_required"
    assert memory.update_calls == []

    applied = runtime.confirm("confirm-setting", request, context())

    assert applied.status == "applied"
    assert applied.result["changed_keys"] == ["memory_enabled", "reference_history_enabled"]
    assert memory.settings["memory_enabled"] is False
    assert memory.settings["reference_history_enabled"] is False


def test_invalid_memory_patch_fails_without_partial_mutation() -> None:
    runtime, memory, *_ = make_runtime()
    request = AppActionRequest(
        action_id=MEMORY_SETTINGS_UPDATE_ACTION_ID,
        arguments={"patch": {"memory_enabled": False, "unknown": True}},
    )

    pending = runtime.dispatch(request, context())
    failed = runtime.confirm("confirm-setting", request, context())

    assert pending.status == "confirmation_required"
    assert failed.error_code == "INVALID_ACTION_ARGUMENTS"
    assert memory.update_calls == []
    assert memory.settings["memory_enabled"] is True


def test_memory_entry_controls_share_the_canonical_store_and_confirm_deletion() -> None:
    runtime, memory, *_ = make_runtime()
    created = runtime.dispatch(
        AppActionRequest(
            action_id=MEMORY_ENTRY_CREATE_ACTION_ID,
            arguments={"text": "Prefer concise answers", "kind": "manual", "scope": "global"},
        ),
        context(),
    )
    memory_id = created.result["memory"]["id"]
    pinned = runtime.dispatch(
        AppActionRequest(action_id=MEMORY_ENTRY_PIN_ACTION_ID, arguments={"memory_id": memory_id, "pinned": True}),
        context(),
    )
    delete_request = AppActionRequest(action_id=MEMORY_ENTRY_DELETE_ACTION_ID, arguments={"memory_id": memory_id})
    pending = runtime.dispatch(delete_request, context())

    assert created.status == "applied"
    assert pinned.result["memory"]["pinned"] is True
    assert pending.status == "confirmation_required"
    assert memory_id in memory.memories

    deleted = runtime.confirm("confirm-setting", delete_request, context())

    assert deleted.status == "applied"
    assert deleted.result == {"changed": True, "deleted": True, "memory_id": memory_id}
    assert memory_id not in memory.memories


def test_provider_secret_is_confirmation_bound_and_absent_from_receipts() -> None:
    runtime, _memory, _providers, _routing, written, _maintenance = make_runtime()
    secret = "sk-private-value"
    request = AppActionRequest(
        action_id=PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID,
        arguments={"provider": "openrouter", "secret": secret},
    )

    pending = runtime.dispatch(request, context("ui"))
    assert pending.status == "confirmation_required"
    assert secret not in pending.model_dump_json()
    assert written == []

    applied = runtime.confirm("confirm-setting", request, context("ui"))

    assert applied.status == "applied"
    assert applied.result == {"changed": True, "provider": "openrouter", "configured": True}
    assert secret not in applied.model_dump_json()
    assert written == [("openrouter", secret)]


def test_chat_credential_request_opens_secure_settings_without_accepting_a_secret() -> None:
    runtime, _memory, _providers, _routing, written, _maintenance = make_runtime()

    receipt = runtime.dispatch(
        AppActionRequest(action_id=PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID, arguments={"provider": "openrouter"}),
        context(),
    )

    assert receipt.status == "applied"
    assert receipt.result["client_effect"] == {
        "type": "settings.open",
        "tab": "configuration",
        "focus": "provider-key-openrouter",
    }
    assert written == []


def test_memory_maintenance_is_confirmed_and_receipts_contain_counts_only() -> None:
    runtime, _memory, _providers, _routing, _credentials, calls = make_runtime()
    dream_request = AppActionRequest(action_id=MEMORY_DREAMING_RUN_ACTION_ID)
    import_request = AppActionRequest(
        action_id=MEMORY_CONVERSATIONS_IMPORT_ACTION_ID,
        arguments={"limit": 50},
    )

    pending_dream = runtime.dispatch(dream_request, context())
    applied_dream = runtime.confirm("confirm-setting", dream_request, context())
    pending_import = runtime.dispatch(import_request, context())
    applied_import = runtime.confirm("confirm-setting", import_request, context())

    assert pending_dream.status == "confirmation_required"
    assert pending_import.status == "confirmation_required"
    assert applied_dream.result == {
        "changed": True,
        "counts": {
            "new_memories": 1,
            "updated_memories": 0,
            "archived_memories": 0,
            "contradictions": 0,
            "imported_conversation_turns": 2,
        },
        "completed": True,
    }
    assert "private memory text" not in applied_dream.model_dump_json()
    assert applied_import.result["counts"] == {
        "indexed_turns": 3,
        "skipped_turns": 1,
        "scanned_turns": 4,
    }
    assert calls == ["dream", ("import", 50)]


def test_routing_actions_mutate_only_the_canonical_routing_runtime() -> None:
    runtime, _memory, _providers, routing, _credentials, _maintenance = make_runtime()

    receipts = runtime.dispatch_many(
        [
            AppActionRequest(action_id=ROUTING_POLICY_SET_ACTION_ID, arguments={"sort": "latency"}),
            AppActionRequest(
                action_id=ROUTING_FALLBACKS_SET_ACTION_ID,
                arguments={"models": ["google/gemma-4-31b-it", "openai/gpt-5.6-sol"]},
            ),
            AppActionRequest(
                action_id=ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID,
                arguments={"provider": "openrouter", "strategy": "round robin"},
            ),
            AppActionRequest(action_id=ROUTING_POOL_RESET_ACTION_ID, arguments={"provider": "openrouter"}),
        ],
        context(),
    )

    assert [receipt.status for receipt in receipts] == ["applied"] * 4
    assert routing.store.policy.sort == "latency"
    assert [item.model for item in routing.store.fallbacks] == [
        "google/gemma-4-31b-it",
        "openai/gpt-5.6-sol",
    ]
    assert routing.store.strategies["openrouter"] == CredentialStrategy.round_robin
    assert routing.pool.resets == ["openrouter"]


def test_model_policy_and_credential_pool_writes_share_confirmation_and_redaction() -> None:
    runtime, _memory, _providers, routing, _credentials, _maintenance = make_runtime()
    model_id = "openai/gpt-5.6-sol"
    policy = runtime.dispatch(
        AppActionRequest(
            action_id=ROUTING_MODEL_POLICY_SET_ACTION_ID,
            arguments={"model_id": model_id, "policy": {"sort": "latency"}},
        ),
        context(),
    )
    remove_policy_request = AppActionRequest(
        action_id=ROUTING_MODEL_POLICY_REMOVE_ACTION_ID,
        arguments={"model_id": model_id},
    )
    pending_remove_policy = runtime.dispatch(remove_policy_request, context())
    removed_policy = runtime.confirm("confirm-setting", remove_policy_request, context())

    secret = "routing-secret-sentinel"
    add_request = AppActionRequest(
        action_id=ROUTING_CREDENTIAL_ADD_ACTION_ID,
        arguments={"provider": "openrouter", "label": "backup", "secret": secret},
    )
    pending_add = runtime.dispatch(add_request, context("ui"))
    added = runtime.confirm("confirm-setting", add_request, context("ui"))
    remove_request = AppActionRequest(
        action_id=ROUTING_CREDENTIAL_REMOVE_ACTION_ID,
        arguments={"credential_id": "credential-1"},
    )
    pending_remove = runtime.dispatch(remove_request, context("ui"))
    removed = runtime.confirm("confirm-setting", remove_request, context("ui"))

    assert policy.status == "applied"
    assert policy.result["policy"]["data_collection"] == "deny"
    assert pending_remove_policy.status == "confirmation_required"
    assert removed_policy.result["removed"] is True
    assert pending_add.status == "confirmation_required"
    assert secret not in pending_add.model_dump_json()
    assert secret not in added.model_dump_json()
    assert added.result["credential"]["fingerprint"] == "0123456789abcdef"
    assert pending_remove.status == "confirmation_required"
    assert removed.result["removed"] is True
    assert routing.secrets.records == {}


def test_pool_reset_receipt_is_truthful_when_no_state_changes() -> None:
    runtime, _memory, _providers, routing, _credentials, _maintenance = make_runtime()
    routing.pool.reset_provider = lambda _provider: 0

    receipt = runtime.dispatch(
        AppActionRequest(action_id=ROUTING_POOL_RESET_ACTION_ID, arguments={"provider": "openrouter"}),
        context(),
    )

    assert receipt.status == "applied"
    assert receipt.result == {
        "changed": False,
        "provider": "openrouter",
        "reset": False,
        "reset_count": 0,
    }


def test_unwired_settings_actions_are_truthfully_unavailable() -> None:
    runtime = AppActionRuntime()
    ids = {definition.id for definition in runtime.catalog().actions}

    assert DEFAULT_MODEL_SET_ACTION_ID not in ids
    receipt = runtime.dispatch(AppActionRequest(action_id=DEFAULT_MODEL_SET_ACTION_ID), context())
    assert (receipt.status, receipt.error_code) == ("unavailable", "ACTION_UNAVAILABLE")
