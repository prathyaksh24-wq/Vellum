# LLM Routing and Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every Vellum LLM call through one durable backend that applies OpenRouter inference-provider policy, rotates OpenRouter/OpenAI credentials, and performs safe turn-scoped model fallback while preserving the existing model picker.

**Architecture:** Add a focused `agent.llm.routing` package containing domain models, SQLite persistence, OS-backed secret resolution, credential leasing, provider adapters, the routing engine, and a LangChain-compatible chat-model wrapper. Wire both LangGraph builders and the legacy OpenRouter helper to the shared runtime, expose redacted management APIs, then add a minimal settings panel.

**Tech Stack:** Python 3.11, Pydantic, SQLite/aiosqlite, keyring, LangChain `BaseChatModel`/`ChatOpenAI`, FastAPI, React-in-HTML, Vitest, pytest.

---

## File map

- Create `backend/agent/llm/routing/models.py`: validated policy, credential, target, attempt, and failure domain types.
- Create `backend/agent/llm/routing/store.py`: schema migrations and transactional policy/credential/attempt persistence.
- Create `backend/agent/llm/routing/secrets.py`: environment and OS-keyring secret references.
- Create `backend/agent/llm/routing/pool.py`: selection strategies, leases, cooldowns, and reconciliation.
- Create `backend/agent/llm/routing/adapters.py`: OpenRouter/OpenAI client construction and normalized error classification.
- Create `backend/agent/llm/routing/engine.py`: retry, credential rotation, fallback, and streaming boundary orchestration.
- Create `backend/agent/llm/routing/chat_model.py`: LangChain-compatible routed model and tool binding.
- Create `backend/agent/llm/routing/runtime.py`: lazy process runtime and legacy migration.
- Create `backend/agent/llm/routing/api.py`: versioned redacted FastAPI management endpoints.
- Create `backend/agent/llm/routing/__init__.py`: public routing exports.
- Modify `backend/agent/config.py`: routing database/keyring/retry settings.
- Modify `backend/agent/graph/agent.py`: use the routed chat model in both builders.
- Modify `backend/agent/llm/openrouter.py`: delegate legacy calls to the shared runtime.
- Modify `backend/agent/api.py`: include routing API and invalidate routed state where required.
- Modify `backend/pyproject.toml`: add `keyring`.
- Create `backend/tests/test_routing_models.py`.
- Create `backend/tests/test_routing_store.py`.
- Create `backend/tests/test_routing_secrets.py`.
- Create `backend/tests/test_credential_pool.py`.
- Create `backend/tests/test_routing_adapters.py`.
- Create `backend/tests/test_routing_engine.py`.
- Create `backend/tests/test_routed_chat_model.py`.
- Create `backend/tests/test_routing_api.py`.
- Modify `backend/tests/test_openrouter.py`, `backend/tests/test_api_models.py`, and `backend/tests/test_api.py` for integration/migration expectations.
- Modify `frontend/ui/api/settings.js` and `frontend/ui/api/settings.test.js`: routing-management API client.
- Modify `frontend/ui/vellum-default.html`: minimal LLM Routing settings tab.
- Create `frontend/ui/vellum-default-routing.test.js`: settings status and redaction behavior.

### Task 1: Domain models and deterministic policy merge

**Files:**
- Create: `backend/agent/llm/routing/__init__.py`
- Create: `backend/agent/llm/routing/models.py`
- Test: `backend/tests/test_routing_models.py`

- [ ] **Step 1: Write failing policy and fallback validation tests**

```python
from pydantic import ValidationError
import pytest

from agent.llm.routing.models import FallbackTarget, ProviderRoutingPolicy, merge_policy


def test_model_policy_replaces_global_lists_and_keeps_privacy_floor():
    global_policy = ProviderRoutingPolicy(
        sort="latency", order=["Fireworks", "DeepInfra"], data_collection="deny", zdr=True
    )
    override = ProviderRoutingPolicy(sort="price", order=["Together"])

    merged = merge_policy(global_policy, override)

    assert merged.sort == "price"
    assert merged.order == ["Together"]
    assert merged.data_collection == "deny"
    assert merged.zdr is True


def test_policy_rejects_provider_in_only_and_ignore():
    with pytest.raises(ValidationError):
        ProviderRoutingPolicy(only=["Fireworks"], ignore=["fireworks"])


def test_fallback_requires_supported_provider_and_model():
    assert FallbackTarget(provider="openrouter", model="qwen/qwen3.5-35b-a3b").provider == "openrouter"
    with pytest.raises(ValidationError):
        FallbackTarget(provider="anthropic", model="claude")
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend; pytest tests/test_routing_models.py -q`

Expected: collection fails because `agent.llm.routing.models` does not exist.

- [ ] **Step 3: Implement the domain types and merge contract**

Implement strict Pydantic models with `extra="forbid"`:

```python
class ProviderRoutingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sort: Literal["price", "latency", "throughput"] | None = None
    only: list[str] | None = None
    ignore: list[str] | None = None
    order: list[str] | None = None
    require_parameters: bool | None = None
    allow_fallbacks: bool | None = None
    data_collection: Literal["deny"] = "deny"
    zdr: Literal[True] = True


class FallbackTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid4().hex)
    provider: Literal["openrouter", "openai"]
    model: str = Field(min_length=1)


def merge_policy(base: ProviderRoutingPolicy, override: ProviderRoutingPolicy | None) -> ProviderRoutingPolicy:
    values = base.model_dump()
    if override is not None:
        values.update(override.model_dump(exclude_unset=True))
    values["data_collection"] = "deny"
    values["zdr"] = True
    return ProviderRoutingPolicy(**values)
```

Add case-insensitive duplicate/collision validation, `CredentialStrategy`, `CredentialStatus`, `CredentialRecord`, `CredentialLease`, `FailureKind`, `ProviderFailure`, `RoutingAttempt`, and `RoutingTerminalError`. The terminal error exposes a correlation ID and normalized summaries only.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `cd backend; pytest tests/test_routing_models.py -q`

Expected: all routing-model tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/llm/routing backend/tests/test_routing_models.py
git commit -m "feat: define llm routing domain models"
```

### Task 2: Durable SQLite policy and telemetry store

**Files:**
- Create: `backend/agent/llm/routing/store.py`
- Create: `backend/tests/test_routing_store.py`
- Modify: `backend/agent/config.py`

- [ ] **Step 1: Write failing persistence and atomic-replacement tests**

```python
def test_policy_fallback_and_cooldown_survive_store_reopen(tmp_path):
    path = tmp_path / "routing.db"
    store = RoutingStore(path)
    store.set_global_policy(ProviderRoutingPolicy(sort="price"))
    store.replace_fallbacks([FallbackTarget(provider="openrouter", model="qwen/test")])
    credential = store.upsert_credential(provider="openrouter", label="primary", source="env:OPENROUTER_API_KEY", fingerprint="fp1")
    store.set_credential_state(credential.id, status="cooldown", cooldown_until="2030-01-01T00:00:00+00:00")

    reopened = RoutingStore(path)

    assert reopened.get_global_policy().sort == "price"
    assert reopened.list_fallbacks()[0].model == "qwen/test"
    assert reopened.get_credential(credential.id).cooldown_until.year == 2030


def test_invalid_fallback_replacement_does_not_destroy_existing_chain(tmp_path):
    store = RoutingStore(tmp_path / "routing.db")
    store.replace_fallbacks([FallbackTarget(provider="openrouter", model="one/model")])
    with pytest.raises(ValueError):
        store.replace_fallbacks([
            FallbackTarget(provider="openrouter", model="dup/model"),
            FallbackTarget(provider="openrouter", model="dup/model"),
        ])
    assert [item.model for item in store.list_fallbacks()] == ["one/model"]
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; pytest tests/test_routing_store.py -q`

Expected: import failure for `RoutingStore`.

- [ ] **Step 3: Implement schema version 1 and store methods**

Create tables `routing_policy`, `model_policy`, `fallback_target`, `credential`, `pool_state`, `credential_lease`, and `routing_attempt`. Use WAL mode, foreign keys, a 5-second busy timeout, UTC ISO timestamps, and transactions for replacements/state transitions. Add indexes on credential provider/status, lease expiry, and attempt timestamp/correlation ID.

Add settings:

```python
llm_routing_db_path: Path = Field(default=Path("data/llm-routing/routing.db"), alias="LLM_ROUTING_DB_PATH")
llm_routing_keyring_service: str = Field(default="vellum.llm", alias="LLM_ROUTING_KEYRING_SERVICE")
llm_routing_max_targets: int = Field(default=4, alias="LLM_ROUTING_MAX_TARGETS")
llm_routing_max_transient_retries: int = Field(default=2, alias="LLM_ROUTING_MAX_TRANSIENT_RETRIES")
```

Resolve the database path against the repository and validate positive limits.

- [ ] **Step 4: Run store and config tests**

Run: `cd backend; pytest tests/test_routing_store.py tests/test_config.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/llm/routing/store.py backend/agent/config.py backend/tests/test_routing_store.py
git commit -m "feat: persist llm routing policy and health"
```

### Task 3: Secret resolver and legacy credential migration

**Files:**
- Create: `backend/agent/llm/routing/secrets.py`
- Create: `backend/tests/test_routing_secrets.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Write failing redaction, keyring, and environment-reference tests**

```python
def test_environment_secret_is_resolved_but_never_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-value")
    store = RoutingStore(tmp_path / "routing.db")
    resolver = SecretResolver(store=store, keyring_backend=FakeKeyring())

    resolver.reconcile_environment({"openrouter": "OPENROUTER_API_KEY"})
    record = store.list_credentials("openrouter")[0]

    assert record.source == "env:OPENROUTER_API_KEY"
    assert resolver.resolve(record) == "secret-value"
    assert "secret-value" not in (tmp_path / "routing.db").read_bytes().decode("latin1")


def test_manual_secret_round_trips_only_through_keyring(tmp_path):
    keyring = FakeKeyring()
    resolver = SecretResolver(RoutingStore(tmp_path / "routing.db"), keyring)
    record = resolver.add_manual("openrouter", "backup", "manual-secret")
    assert keyring.get_password("vellum.llm", record.id) == "manual-secret"
    assert resolver.public_record(record).model_dump_json().find("manual-secret") == -1
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; pytest tests/test_routing_secrets.py -q`

Expected: import failure for `SecretResolver`.

- [ ] **Step 3: Add keyring and implement secret references**

Add `"keyring>=25.0.0"` to project dependencies. Implement `SecretResolver` with an injected backend, `hmac.compare_digest`-safe keyed fingerprints, `env:` and `keyring:` sources, atomic add/remove ordering, and a `SecretUnavailable` exception that never contains the secret. Use a stable local fingerprint salt stored in keyring under `__fingerprint_salt__`; tests inject a fixed salt.

Reconciliation seeds `OPENROUTER_API_KEY` and `OPENAI_API_KEY`, refreshes fingerprints, marks missing env entries unavailable after leases expire, and leaves manual entries untouched.

- [ ] **Step 4: Run secret tests and dependency validation**

Run: `cd backend; pytest tests/test_routing_secrets.py -q; python -c "import keyring"`

Expected: tests pass and keyring imports.

- [ ] **Step 5: Commit**

```powershell
git add backend/pyproject.toml backend/agent/llm/routing/secrets.py backend/tests/test_routing_secrets.py
git commit -m "feat: store llm secrets in os keyring"
```

### Task 4: Credential selection, leases, and cooldown state machine

**Files:**
- Create: `backend/agent/llm/routing/pool.py`
- Create: `backend/tests/test_credential_pool.py`

- [ ] **Step 1: Write failing strategy and cooldown tests**

```python
def test_round_robin_skips_cooling_and_model_ineligible_credentials(pool, clock):
    first = pool.add("openrouter", "one", models=["google/model"])
    second = pool.add("openrouter", "two")
    third = pool.add("openrouter", "three")
    pool.set_strategy("openrouter", "round_robin")
    pool.cooldown(second.id, until=clock.now() + timedelta(hours=1))

    assert pool.lease("openrouter", "google/model").credential_id == first.id
    assert pool.lease("openrouter", "google/model").credential_id == third.id


def test_expired_lease_is_reaped_and_success_resets_429_state(pool, clock):
    credential = pool.add("openrouter", "one")
    lease = pool.lease("openrouter", "model", ttl=timedelta(seconds=30))
    pool.mark_generic_429(lease)
    clock.advance(seconds=31)
    replacement = pool.lease("openrouter", "model")
    pool.mark_success(replacement)
    assert pool.get(credential.id).consecutive_429 == 0
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; pytest tests/test_credential_pool.py -q`

Expected: import failure for `CredentialPool`.

- [ ] **Step 3: Implement the transactional pool**

Implement `lease()`, `release()`, `mark_success()`, `mark_auth_invalid()`, `mark_billing_exhausted()`, `mark_generic_429()`, `mark_plan_exhausted()`, `reset_provider()`, and selection for all four strategies. Inject `clock`, `random`, and lease TTL. Never hold an SQLite transaction or async lock while making a network request.

Use a short process-local `asyncio.Lock` around select-and-insert lease operations. Store round-robin cursor in `pool_state`. Allow concurrent leases of one credential while tracking active count; removal rejects active manual credentials with HTTP-conflict-compatible domain error.

- [ ] **Step 4: Run pool and store tests**

Run: `cd backend; pytest tests/test_credential_pool.py tests/test_routing_store.py -q`

Expected: all pass, including concurrent `asyncio.gather` lease tests.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/llm/routing/pool.py backend/tests/test_credential_pool.py
git commit -m "feat: rotate and cool down llm credentials"
```

### Task 5: Provider adapters and normalized failures

**Files:**
- Create: `backend/agent/llm/routing/adapters.py`
- Create: `backend/tests/test_routing_adapters.py`

- [ ] **Step 1: Write failing OpenRouter-body and classification tests**

```python
def test_openrouter_adapter_builds_effective_provider_body():
    adapter = OpenRouterAdapter(base_url="https://openrouter.ai/api/v1")
    model = adapter.build_model(
        target=FallbackTarget(provider="openrouter", model="google/test"),
        secret="key",
        temperature=0.2,
        policy=ProviderRoutingPolicy(sort="price", ignore=["Together"], require_parameters=True),
    )
    assert model.extra_body["provider"] == {
        "sort": "price", "ignore": ["Together"], "require_parameters": True,
        "data_collection": "deny", "zdr": True,
    }


@pytest.mark.parametrize((status, message, kind), [
    (401, "expired", FailureKind.AUTH),
    (402, "credits exhausted", FailureKind.BILLING),
    (404, "model not found", FailureKind.MODEL_UNAVAILABLE),
    (429, "daily quota exceeded", FailureKind.PLAN_EXHAUSTED),
    (429, "rate limited", FailureKind.RATE_LIMIT),
    (503, "overloaded", FailureKind.SERVER),
])
def test_error_classifier(status, message, kind):
    assert classify_provider_exception(FakeStatusError(status, message)).kind is kind
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; pytest tests/test_routing_adapters.py -q`

Expected: import failure for provider adapters.

- [ ] **Step 3: Implement adapters and sanitized classifier**

`OpenRouterAdapter.build_model()` and `OpenAIAdapter.build_model()` return configured `ChatOpenAI` instances. OpenRouter uses `extra_body={"provider": policy.to_openrouter_body()}`, existing referer/title headers, and the selected credential. OpenAI strips the `openai/` prefix.

`classify_provider_exception()` inspects typed OpenAI/httpx exceptions, status code, `Retry-After`, and a bounded lower-cased message for known quota phrases. It returns `ProviderFailure` with a sanitized summary and never retains the original response, headers, request, or body.

- [ ] **Step 4: Run adapter and existing payload tests**

Run: `cd backend; pytest tests/test_routing_adapters.py tests/test_openrouter.py::test_openrouter_payload_enforces_privacy_policy -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/llm/routing/adapters.py backend/tests/test_routing_adapters.py
git commit -m "feat: normalize openrouter and openai routing"
```

### Task 6: Routing engine retry, rotation, and fallback

**Files:**
- Create: `backend/agent/llm/routing/engine.py`
- Create: `backend/tests/test_routing_engine.py`

- [ ] **Step 1: Write failing end-to-end attempt-order tests**

```python
async def test_pool_rotation_precedes_model_fallback(runtime_fixture):
    engine, adapter = runtime_fixture(
        credentials=[("openrouter", "key-1"), ("openrouter", "key-2")],
        fallbacks=[("openrouter", "qwen/fallback")],
        outcomes=[AuthFailure(), Success("primary on second key")],
    )
    result = await engine.ainvoke(messages=[HumanMessage("hello")], primary_model="google/primary")
    assert result.content == "primary on second key"
    assert adapter.calls == [
        ("google/primary", "key-1"),
        ("google/primary", "key-2"),
    ]


async def test_exhausted_pool_uses_ordered_fallback_and_does_not_mutate_primary(runtime_fixture):
    engine, adapter = runtime_fixture(
        credentials=[("openrouter", "key-1")],
        fallbacks=[("openrouter", "qwen/fallback")],
        outcomes=[ModelUnavailable(), Success("fallback")],
    )
    assert (await engine.ainvoke(messages=[HumanMessage("one")], primary_model="google/primary")).content == "fallback"
    assert (await engine.ainvoke(messages=[HumanMessage("two")], primary_model="google/primary")).content
    assert adapter.calls[0][0] == "google/primary"
    assert adapter.calls[2][0] == "google/primary"
```

Also cover one retry for generic 429, immediate rotation for 402/plan exhaustion, bounded 5xx backoff, no fallback for invalid requests, attempt caps, `Retry-After`, terminal sanitization, and telemetry-write failure not blocking success.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; pytest tests/test_routing_engine.py -q`

Expected: import failure for `RoutingEngine`.

- [ ] **Step 3: Implement immutable attempt plans and state transitions**

Implement:

```python
async def ainvoke(self, *, messages, primary_model, tools=(), temperature=0.3, thread_id="background", **kwargs):
    plan = self.build_plan(primary_model)
    for target_index, target in enumerate(plan.targets[: self.max_targets]):
        result = await self._attempt_target(...)
        if result.is_success:
            return result.message
        if result.failure.kind is FailureKind.INVALID_REQUEST:
            raise self._terminal(plan, result.failure)
    raise self._terminal(plan, last_failure)
```

Keep retry decisions in a pure `RecoveryPolicy.decide(failure, state) -> RecoveryAction` so every branch is unit-testable. Record one content-free attempt row per network attempt. Use injected `async_sleep`, clock, and jitter.

- [ ] **Step 4: Run engine, pool, adapter, and telemetry tests**

Run: `cd backend; pytest tests/test_routing_engine.py tests/test_credential_pool.py tests/test_routing_adapters.py tests/test_telemetry_ledger.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/llm/routing/engine.py backend/tests/test_routing_engine.py
git commit -m "feat: orchestrate llm retries and fallback"
```

### Task 7: Streaming boundary and LangChain routed model

**Files:**
- Create: `backend/agent/llm/routing/chat_model.py`
- Create: `backend/tests/test_routed_chat_model.py`

- [ ] **Step 1: Write failing tool-binding and stream-safety tests**

```python
async def test_routed_model_binds_tools_and_returns_chat_result(fake_engine):
    model = RoutedChatModel(engine=fake_engine, primary_model=lambda: "google/primary")
    bound = model.bind_tools([{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}])
    result = await bound.ainvoke([HumanMessage("use lookup")])
    assert result.tool_calls[0]["name"] == "lookup"
    assert fake_engine.last_tools[0]["function"]["name"] == "lookup"


async def test_stream_falls_back_before_first_chunk_but_not_after_visible_chunk(fake_stream_engine):
    fake_stream_engine.outcomes = [FailureBeforeFirstChunk(), Chunks(["fallback"])]
    assert await collect(fake_stream_engine.astream(primary_model="primary")) == "fallback"

    fake_stream_engine.outcomes = [ChunksThenFailure(["partial"]), Chunks(["must-not-run"])]
    with pytest.raises(RoutingStreamInterrupted):
        await collect(fake_stream_engine.astream(primary_model="primary"))
    assert "must-not-run" not in fake_stream_engine.emitted_attempt_models
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; pytest tests/test_routed_chat_model.py -q`

Expected: import failure for `RoutedChatModel`.

- [ ] **Step 3: Implement `BaseChatModel` compatibility**

Implement `_generate`, `_agenerate`, `_stream`, `_astream`, `_llm_type`, and `bind_tools`. Wrap `AIMessage` as `ChatGeneration`/`ChatResult` and `AIMessageChunk` as `ChatGenerationChunk`. Preserve response metadata, usage metadata, tool-call chunks, stop sequences, callbacks, tags, and configurable thread ID.

The engine's stream loop may move to another credential/target only if no chunk containing text or tool-call data has been yielded. Empty metadata chunks do not close the fallback window. Once visible content is yielded, any failure raises `RoutingStreamInterrupted` with correlation ID.

- [ ] **Step 4: Run wrapper and agent-wiring tests**

Run: `cd backend; pytest tests/test_routed_chat_model.py tests/test_openrouter.py::test_react_agent_wiring_uses_system_prompt_and_tools -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/llm/routing/chat_model.py backend/tests/test_routed_chat_model.py
git commit -m "feat: expose routed langchain chat model"
```

### Task 8: Runtime composition, migration, and production chat wiring

**Files:**
- Create: `backend/agent/llm/routing/runtime.py`
- Modify: `backend/agent/llm/routing/__init__.py`
- Modify: `backend/agent/graph/agent.py`
- Modify: `backend/agent/llm/openrouter.py`
- Modify: `backend/tests/test_openrouter.py`
- Modify: `backend/tests/test_api_models.py`

- [ ] **Step 1: Replace obsolete exact-model test with failing routed-runtime assertions**

```python
def test_agent_builders_use_shared_routed_model(monkeypatch):
    class FakeRoutedModel:
        def __init__(self):
            self._model = None

        def select_primary(self, model):
            self._model = model
            return self

        def primary_model(self):
            return self._model

    routed = FakeRoutedModel()
    monkeypatch.setattr(react_agent, "get_routed_chat_model", lambda: routed)
    monkeypatch.setattr(react_agent, "build_checkpointer", lambda: "checkpointer")
    monkeypatch.setattr(react_agent, "create_react_agent", capture_create)
    react_agent.build_agent("deepseek/deepseek-v4-pro")
    assert captured["model"] is routed
    assert routed.primary_model() == "deepseek/deepseek-v4-pro"


def test_legacy_fallback_model_seeds_chain_only_when_chain_empty(tmp_path, settings):
    runtime = build_routing_runtime(settings=settings, db_path=tmp_path / "routing.db")
    assert runtime.store.list_fallbacks()[0].model == settings.fallback_model
    runtime.store.replace_fallbacks([FallbackTarget(provider="openrouter", model="custom/fallback")])
    runtime.reconcile_legacy_settings()
    assert runtime.store.list_fallbacks()[0].model == "custom/fallback"
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; pytest tests/test_openrouter.py tests/test_api_models.py -q`

Expected: routed-model assertions fail while builders still construct direct `ChatOpenAI`.

- [ ] **Step 3: Compose and wire the singleton runtime**

`runtime.py` constructs the store, resolver, pool, adapters, engine, and routed model lazily. It reconciles environment credentials and legacy fallback once at startup. Expose cache-reset hooks for tests and settings changes.

Change `build_llm()` to return a routed model whose primary-model callable reads the active registry at invocation time. Remove production use of `build_llm_with_fallback`; keep a deprecated compatibility alias returning the routed model. Make the legacy `openrouter_chat()` convert system/user strings to messages and call the same engine rather than maintain an independent retry implementation.

- [ ] **Step 4: Run all LLM and model-selection tests**

Run: `cd backend; pytest tests/test_openrouter.py tests/test_providers.py tests/test_api_models.py tests/test_chat_stream_sources.py -q`

Expected: all pass and no test expects a direct `ChatOpenAI` production model.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/llm/routing backend/agent/graph/agent.py backend/agent/llm/openrouter.py backend/tests/test_openrouter.py backend/tests/test_api_models.py
git commit -m "feat: route every vellum llm call through resilience runtime"
```

### Task 9: Redacted management API

**Files:**
- Create: `backend/agent/llm/routing/api.py`
- Create: `backend/tests/test_routing_api.py`
- Modify: `backend/agent/api.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing API contract and secret-leak tests**

```python
def test_add_credential_never_echoes_or_logs_secret(client, caplog):
    response = client.post("/api/llm-routing/credentials", json={
        "provider": "openrouter", "label": "backup", "secret": "super-secret-key"
    })
    assert response.status_code == 201
    assert "super-secret-key" not in response.text
    assert "super-secret-key" not in caplog.text
    assert response.json()["fingerprint"]


def test_invalid_fallback_chain_is_atomic(client):
    client.put("/api/llm-routing/fallbacks", json={"targets": [{"provider": "openrouter", "model": "one/model"}]})
    rejected = client.put("/api/llm-routing/fallbacks", json={"targets": [
        {"provider": "openrouter", "model": "dup/model"},
        {"provider": "openrouter", "model": "dup/model"},
    ]})
    assert rejected.status_code == 422
    assert client.get("/api/llm-routing/fallbacks").json()["targets"][0]["model"] == "one/model"
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; pytest tests/test_routing_api.py -q`

Expected: 404 responses because the router is not registered.

- [ ] **Step 3: Implement and include the versioned router**

Create an `APIRouter(prefix="/llm-routing")` for status, policies, fallbacks, credentials, strategies, reset, and paginated attempts. Use strict request models and redacted response models. Map active-lease removal to 409, unknown IDs to 404, and validation to 422. Include it under Vellum's existing `/api` router.

Convert `/settings/provider-key` into a compatibility wrapper over `SecretResolver.add_or_replace_legacy()` and add `Deprecation: true` plus `Sunset` response headers without exposing credentials.

- [ ] **Step 4: Run routing and existing API tests**

Run: `cd backend; pytest tests/test_routing_api.py tests/test_api.py tests/test_api_models.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/llm/routing/api.py backend/agent/api.py backend/tests/test_routing_api.py backend/tests/test_api.py
git commit -m "feat: manage llm routing through redacted api"
```

### Task 10: Frontend routing API client

**Files:**
- Modify: `frontend/ui/api/settings.js`
- Modify: `frontend/ui/api/settings.test.js`

- [ ] **Step 1: Write failing client request tests**

```javascript
it("uses versioned routing endpoints", async () => {
  await api.routingStatus();
  await api.setFallbacks([{provider: "openrouter", model: "qwen/fallback"}]);
  await api.addCredential({provider: "openrouter", label: "backup", secret: "key"});
  expect(requests).toContainEqual(["/api/llm-routing/status", undefined]);
  expect(requests[1][0]).toBe("/api/llm-routing/fallbacks");
  expect(JSON.parse(requests[2][1].body).secret).toBe("key");
});
```

- [ ] **Step 2: Run and verify RED**

Run: `cd frontend; npm test -- ui/api/settings.test.js`

Expected: methods such as `routingStatus` do not exist.

- [ ] **Step 3: Add focused client methods**

Add `routingStatus`, `routingPolicies`, `setGlobalRoutingPolicy`, `setModelRoutingPolicy`, `routingFallbacks`, `setFallbacks`, `routingCredentials`, `addCredential`, `removeCredential`, `setCredentialStrategy`, `resetCredentialPool`, and `routingAttempts`. Keep secrets only in the local request payload; do not cache them.

- [ ] **Step 4: Run frontend API tests**

Run: `cd frontend; npm test -- ui/api/settings.test.js`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/ui/api/settings.js frontend/ui/api/settings.test.js
git commit -m "feat: add llm routing settings api client"
```

### Task 11: Minimal LLM Routing settings UI

**Files:**
- Modify: `frontend/ui/vellum-default.html`
- Create: `frontend/ui/vellum-default-routing.test.js`

- [ ] **Step 1: Write failing UI structure and redaction tests**

```javascript
it("renders routing status without credential secrets", async () => {
  const source = readFileSync("ui/vellum-default.html", "utf8");
  expect(source).toContain("LLM Routing");
  expect(source).toContain("routingStatus");
  expect(source).toContain("Fallback chain");
  expect(source).toContain("Credential health");
  expect(source).not.toContain("credential.secret}");
});
```

Add behavior tests with mocked API responses for loading, saving a policy, replacing fallback order, adding a credential then clearing the input, removing a credential, changing strategy, resetting cooldowns, and displaying the last fallback reason.

- [ ] **Step 2: Run and verify RED**

Run: `cd frontend; npm test -- ui/vellum-default-routing.test.js`

Expected: required routing settings labels and behavior are absent.

- [ ] **Step 3: Add the compact settings section**

Add an `LLM Routing` settings tab/component using existing `set-row`, button, input, select, and status-pill styles. Load status only when the tab opens. Show active model/provider, effective OpenRouter policy, ordered fallbacks, per-provider health counts, and latest route. Provide plain controls for policy fields, fallback ordering, credential add/remove, strategy selection, and reset.

Clear the secret input immediately after the add request settles. Never store it in localStorage, parent state, toast text, errors, or rendered credential objects. Do not change the model picker.

- [ ] **Step 4: Run UI tests and production build**

Run: `cd frontend; npm test -- ui/vellum-default-routing.test.js ui/api/settings.test.js; npm run build`

Expected: tests pass and Vite build exits 0.

- [ ] **Step 5: Commit**

```powershell
git add frontend/ui/vellum-default.html frontend/ui/vellum-default-routing.test.js
git commit -m "feat: expose minimal llm routing settings"
```

### Task 12: Security, integration, and regression verification

**Files:**
- Modify: `backend/tests/test_routing_engine.py`
- Modify: `backend/tests/test_routing_api.py`
- Modify: `backend/tests/test_openrouter.py`
- Modify: `backend/tests/test_chat_stream_sources.py`
- Modify: `README.md`

- [ ] **Step 1: Add failing end-to-end resilience and leak-scan tests**

Add a mocked API-chat test exercising primary OpenRouter key auth failure, second-key quota failure, fallback model success, preserved thread ID/tool history, and next-turn primary restoration. Add a stream test proving a failure after a tool-call delta is not replayed. Add a database/log/API leak test using a unique sentinel secret.

- [ ] **Step 2: Run the new tests and verify they expose any remaining gaps**

Run: `cd backend; pytest tests/test_routing_engine.py tests/test_routing_api.py tests/test_openrouter.py tests/test_chat_stream_sources.py -q`

Expected: any missing integration behavior fails with an assertion tied to routing order, stream replay, or secret leakage.

- [ ] **Step 3: Make only the minimal integration corrections and document operations**

Update README configuration with the routing database path, keyring requirement, environment seeding, migration behavior, API overview, cooldown meanings, fallback scope, stream limitation, and recovery instructions. Do not document or print actual key values.

- [ ] **Step 4: Run full fresh verification**

Run:

```powershell
Set-Location D:\Vellum\backend
pytest -q
Set-Location D:\Vellum\frontend
npm test
npm run build
Set-Location D:\Vellum
git diff --check
git status --short
```

Expected: backend and frontend suites report zero failures, Vite exits 0, `git diff --check` emits nothing, and status contains only intended files.

- [ ] **Step 5: Commit the verified integration**

```powershell
git add README.md backend/tests frontend/ui
git commit -m "test: verify llm routing resilience end to end"
```

## Completion review

Before declaring completion:

- Confirm each acceptance criterion in `docs/superpowers/specs/2026-07-01-llm-routing-resilience-design.md` has a passing test or an explicitly verified operational check.
- Inspect `git diff HEAD~12..HEAD --stat` and every production diff for unrelated changes.
- Run a repository search for the sentinel test secret and confirm it appears only in test source, never generated data or logs.
- Confirm no endpoint returns `secret`, `api_key`, `access_token`, or `Authorization` fields.
- Confirm the active model registry remains unchanged after a fallback attempt.
- Confirm no fallback starts after visible stream text or tool-call content.
