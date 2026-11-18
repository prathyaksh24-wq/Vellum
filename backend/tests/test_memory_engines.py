import base64
import json
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.memory.engines import llm_routing
from agent.memory.engines.embeddings_route import router as embeddings_router
from agent.memory.engines.llm_routing import hindsight_llm_env, honcho_llm_env, memory_engine_llm
from agent.memory.engines.postgres import EnginePostgres
from agent.memory.engines.supervisor import EngineNotReady, EngineSpec, EngineSupervisor


# -- embeddings route ----------------------------------------------------------

class FakeEmbedder:
    dimensions = 3
    model_name = "embeddinggemma-2:270m-q8_0-text"
    fingerprint = "fp-123"

    def embed_batch(self, texts):
        return [[float(len(text)), 0.5, -1.0] for text in texts]


@pytest.fixture
def embeddings_client(monkeypatch):
    from agent.rag import embedder

    monkeypatch.setattr(embedder, "get_embedder", lambda: FakeEmbedder())
    app = FastAPI()
    app.include_router(embeddings_router, prefix="/api")
    return TestClient(app)


def test_embeddings_route_speaks_the_openai_shape(embeddings_client):
    response = embeddings_client.post("/api/v1/embeddings", json={"input": ["hi", "hello"], "model": "x"})
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list" and body["model"] == "embeddinggemma-2:270m-q8_0-text"
    assert [item["index"] for item in body["data"]] == [0, 1]
    assert body["data"][1]["embedding"] == [5.0, 0.5, -1.0]
    assert response.headers["X-Vellum-Embedding-Fingerprint"] == "fp-123"


def test_embeddings_route_supports_base64_and_rejects_wrong_dimensions(embeddings_client):
    body = embeddings_client.post("/api/v1/embeddings", json={"input": "abc", "encoding_format": "base64"}).json()
    decoded = struct.unpack("<3f", base64.b64decode(body["data"][0]["embedding"]))
    assert decoded == pytest.approx((3.0, 0.5, -1.0))
    wrong = embeddings_client.post("/api/v1/embeddings", json={"input": "abc", "dimensions": 1536})
    assert wrong.status_code == 400 and "3 dimensions" in wrong.json()["detail"]


def test_embeddings_route_refuses_other_computers(monkeypatch):
    from agent.rag import embedder

    monkeypatch.setattr(embedder, "get_embedder", lambda: FakeEmbedder())
    app = FastAPI()
    app.include_router(embeddings_router, prefix="/api")
    remote = TestClient(app, client=("203.0.113.9", 5000))
    assert remote.post("/api/v1/embeddings", json={"input": "hi"}).status_code == 403


# -- LLM routing -----------------------------------------------------------------

def _settings(**keys):
    base = {"memory_engine_provider": "", "memory_engine_model": "", "memory_llm_model": "gemma4:12b",
            "ollama_base_url": "http://127.0.0.1:11434"}
    for provider in ("openrouter", "groq", "openai", "anthropic", "google"):
        base[f"{provider}_api_key"] = keys.get(provider, "")
    base.update({k: v for k, v in keys.items() if k.startswith("memory_")})
    return SimpleNamespace(**base)


def _registry(active: str, picker: str = ""):
    return SimpleNamespace(current_model=lambda: SimpleNamespace(id=active), picker_provider=lambda: picker)


def test_local_users_reuse_their_chat_model():
    llm = memory_engine_llm(_settings(), _registry("ollama/qwen3.5:9b", "ollama"))
    assert (llm.provider, llm.model, llm.base_url, llm.ready) == ("ollama", "qwen3.5:9b",
                                                                  "http://127.0.0.1:11434/v1", True)
    env = hindsight_llm_env(llm)
    assert env["HINDSIGHT_API_LLM_PROVIDER"] == "ollama"
    assert env["HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS"] == "16000"
    honcho = honcho_llm_env(llm)
    assert honcho["DERIVER_MODEL_CONFIG__OVERRIDES__BASE_URL"] == "http://127.0.0.1:11434/v1"
    assert json.loads(honcho["DERIVER_MODEL_CONFIG__OVERRIDES__PROVIDER_PARAMS"]) == {
        "extra_body": {"reasoning_effort": "none"}}


def test_openrouter_users_get_a_cheap_model_and_no_data_retention():
    llm = memory_engine_llm(_settings(openrouter="sk-or-test"), _registry("anthropic/claude", "openrouter"))
    assert (llm.provider, llm.model, llm.api_key) == ("openrouter", "google/gemma-3-12b-it", "sk-or-test")
    env = hindsight_llm_env(llm)
    assert json.loads(env["HINDSIGHT_API_LLM_EXTRA_BODY"]) == {"provider": {"data_collection": "deny"}}
    honcho = honcho_llm_env(llm)
    assert honcho["LLM_OPENAI_API_KEY"] == "sk-or-test"
    for level in ("minimal", "low", "medium", "high", "max"):
        assert honcho[f"DIALECTIC_LEVELS__{level}__MODEL_CONFIG__OVERRIDES__BASE_URL"] == "https://openrouter.ai/api/v1"


def test_groq_free_tier_needs_on_demand_service_tier():
    llm = memory_engine_llm(_settings(groq="gsk-test", memory_engine_provider="groq"), _registry("x"))
    env = hindsight_llm_env(llm)
    assert env["HINDSIGHT_API_LLM_GROQ_SERVICE_TIER"] == "on_demand"
    assert honcho_llm_env(llm)["SUMMARY_MODEL_CONFIG__OVERRIDES__BASE_URL"] == "https://api.groq.com/openai/v1"


@pytest.mark.parametrize("provider,transport,key_env", [
    ("anthropic", "anthropic", "LLM_ANTHROPIC_API_KEY"),
    ("google", "gemini", "LLM_GEMINI_API_KEY"),
    ("openai", "openai", "LLM_OPENAI_API_KEY"),
])
def test_bring_your_own_key_providers_use_native_transports(provider, transport, key_env):
    llm = memory_engine_llm(_settings(**{provider: "key-1", "memory_engine_provider": provider}), _registry("x"))
    honcho = honcho_llm_env(llm)
    assert honcho["DERIVER_MODEL_CONFIG__TRANSPORT"] == transport and honcho[key_env] == "key-1"
    assert "DERIVER_MODEL_CONFIG__OVERRIDES__BASE_URL" not in honcho
    assert hindsight_llm_env(llm)["HINDSIGHT_API_LLM_MODEL"] == llm_routing.DEFAULT_CLOUD_MODELS[provider]


def test_missing_key_or_model_is_reported_not_guessed():
    llm = memory_engine_llm(_settings(memory_engine_provider="anthropic"), _registry("x"))
    assert not llm.ready and "anthropic API key" in llm.reason
    local = memory_engine_llm(_settings(memory_llm_model=""), _registry("openai/gpt", "ollama"))
    assert not local.ready and local.reason == "No local model is installed yet"


# -- embedded Postgres wrapper -------------------------------------------------------

class FakePg:
    instances: list["FakePg"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.port = kwargs.get("port")
        self.running = False
        self.sql: list[tuple[str, ...]] = []
        self.stopped = False
        FakePg.instances.append(self)

    def info(self):
        return SimpleNamespace(running=self.running, port=self.port)

    def start(self):
        self.running = True
        return SimpleNamespace(running=True, port=self.port)

    def psql(self, *args):
        self.sql.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def stop(self):
        self.stopped = True


def test_postgres_uses_its_own_port_and_workspace_data_dir(tmp_path: Path):
    FakePg.instances.clear()
    pg = EnginePostgres(tmp_path / "engines", pg_factory=FakePg, port_picker=lambda: 54329)
    uri = pg.start()
    started = FakePg.instances[-1]
    assert started.kwargs["data_dir"] == str(tmp_path / "engines" / "postgres")
    assert started.port == 54329 and uri.startswith("postgresql://vellum:") and uri.endswith("@127.0.0.1:54329/postgres")
    assert len(pg.state.password) >= 20

    honcho_uri = pg.ensure_database("honcho")
    assert honcho_uri.endswith("/honcho")
    assert ("-d", pg.uri("postgres"), "-c", 'CREATE DATABASE "honcho"') in started.sql
    assert ("-d", pg.uri("honcho"), "-c", "CREATE EXTENSION IF NOT EXISTS vector") in started.sql
    with pytest.raises(ValueError):
        pg.ensure_database("bad; drop")

    again = EnginePostgres(tmp_path / "engines", pg_factory=FakePg, port_picker=lambda: 1)
    assert (again.state.port, again.state.password) == (54329, pg.state.password)
    pg.stop()
    assert started.stopped


# -- supervisor ---------------------------------------------------------------------------

class FakeProcess:
    _next_pid = 100

    def __init__(self, argv, **kwargs):
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self.argv = argv
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


def _spec(name):
    return EngineSpec(name=name, argv=[name], env={}, health_url=f"http://x/{name}/health", url=f"http://x/{name}",
                      ready_timeout=5)


def test_supervisor_starts_in_order_reports_status_and_stops_in_reverse():
    order, processes = [], []

    def popen(argv, **kwargs):
        process = FakeProcess(argv)
        processes.append(process)
        order.append(("start", argv[0]))
        return process

    supervisor = EngineSupervisor(health_check=lambda url: True, popen=popen, sleep=lambda s: None)
    supervisor.before_all(lambda: order.append(("db", "start")))
    supervisor.after_all(lambda: order.append(("db", "stop")))
    supervisor.add_engine("hindsight", lambda: _spec("hindsight"))
    supervisor.add_engine("honcho", lambda: (_ for _ in ()).throw(EngineNotReady("needs_model", "Add a key")))
    for hook in supervisor._before_all:
        hook()
    for name, factory in supervisor._factories:
        supervisor._launch(name, factory)

    status = supervisor.status()
    assert status["hindsight"]["state"] == "ready" and supervisor.url("hindsight") == "http://x/hindsight"
    assert status["honcho"] == {**status["honcho"], "state": "needs_model", "reason": "Add a key"}
    supervisor.stop()
    assert order == [("db", "start"), ("start", "hindsight"), ("db", "stop")]
    assert processes[0].terminated and supervisor.status()["hindsight"]["state"] == "stopped"


def test_engine_that_exits_during_startup_is_an_error_not_a_hang():
    def popen(argv, **kwargs):
        process = FakeProcess(argv)
        process.returncode = 3
        return process

    supervisor = EngineSupervisor(health_check=lambda url: False, popen=popen, sleep=lambda s: None)
    supervisor.add_engine("hindsight", lambda: _spec("hindsight"))
    assert supervisor._launch("hindsight", lambda: _spec("hindsight")) is False
    assert supervisor.status()["hindsight"]["reason"] == "Exited during startup (code 3)"


# -- embedded Hindsight ---------------------------------------------------------------

def test_hindsight_spec_wires_database_embeddings_reranker_and_llm(tmp_path: Path, monkeypatch):
    from agent.memory.engines import hindsight_engine
    from agent.memory.engines.runtime import EngineContext
    from agent.rag import embedder

    python = tmp_path / "python.exe"
    python.write_text("")
    monkeypatch.setattr(hindsight_engine, "engine_python", lambda name: python)
    monkeypatch.setattr(hindsight_engine, "memory_engine_llm",
                        lambda: memory_engine_llm(_settings(groq="gsk-1", memory_engine_provider="groq"), _registry("x")))
    monkeypatch.setattr(embedder, "get_embedder", lambda: FakeEmbedder())
    FakePg.instances.clear()
    pg = EnginePostgres(tmp_path / "engines", pg_factory=FakePg, port_picker=lambda: 54400)
    pg.start()
    spec = hindsight_engine.build_spec(EngineContext(tmp_path / "engines", pg, "http://127.0.0.1:8000"))

    env = spec.env
    assert spec.argv == [str(python), "-c", "from hindsight_api.main import main; main()"]
    assert env["HINDSIGHT_API_DATABASE_URL"].endswith("@127.0.0.1:54400/hindsight")
    assert env["HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL"] == "http://127.0.0.1:8000/api/v1"
    assert env["HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS"] == "3"
    assert env["HINDSIGHT_API_RERANKER_PROVIDER"] == "flashrank"
    assert env["HINDSIGHT_API_LLM_GROQ_SERVICE_TIER"] == "on_demand"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert spec.health_url == f"{spec.url}/health" and spec.url.startswith("http://127.0.0.1:")
    assert "OPENROUTER_API_KEY" not in env  # Vellum's own secrets are not inherited


def test_hindsight_engine_reports_why_it_cannot_start(tmp_path: Path, monkeypatch):
    from agent.memory.engines import hindsight_engine
    from agent.memory.engines.runtime import EngineContext

    context = EngineContext(tmp_path, EnginePostgres(tmp_path, pg_factory=FakePg), "http://127.0.0.1:8000")
    monkeypatch.setattr(hindsight_engine, "engine_python", lambda name: None)
    with pytest.raises(EngineNotReady) as missing:
        hindsight_engine.build_spec(context)
    assert missing.value.state == "off"

    monkeypatch.setattr(hindsight_engine, "engine_python", lambda name: tmp_path / "python.exe")
    monkeypatch.setattr(hindsight_engine, "memory_engine_llm",
                        lambda: memory_engine_llm(_settings(memory_engine_provider="anthropic"), _registry("x")))
    with pytest.raises(EngineNotReady) as no_key:
        hindsight_engine.build_spec(context)
    assert no_key.value.state == "needs_model" and "anthropic API key" in no_key.value.reason


def test_vellum_client_follows_the_embedded_engine(monkeypatch):
    from agent.memory import provider_extensions

    monkeypatch.setattr(provider_extensions, "_embedded_engine_url", lambda: "http://127.0.0.1:54171")
    monkeypatch.delenv("MEMORY_EXTENSION_PROVIDERS", raising=False)
    provider = provider_extensions.HindsightProviderExtension()
    assert provider.is_enabled() and provider.is_configured()
    assert provider.base_url == "http://127.0.0.1:54171"


def test_supervisor_shows_starting_before_its_thread_runs():
    supervisor = EngineSupervisor(health_check=lambda url: False, popen=FakeProcess, sleep=lambda s: None)
    supervisor.add_engine("hindsight", lambda: (_ for _ in ()).throw(EngineNotReady("off", "not installed")))
    supervisor._thread = SimpleNamespace(is_alive=lambda: False)
    supervisor._run = lambda: None  # don't actually run in this test
    import threading as _threading

    original = _threading.Thread
    try:
        _threading.Thread = lambda **kwargs: SimpleNamespace(start=lambda: None, is_alive=lambda: True)
        supervisor.start()
    finally:
        _threading.Thread = original
    assert supervisor.status()["hindsight"]["state"] == "starting"


# -- embedded Honcho ---------------------------------------------------------------------

def _honcho_context(tmp_path: Path, monkeypatch):
    from agent.memory.engines import honcho_engine
    from agent.memory.engines.runtime import EngineContext
    from agent.rag import embedder

    python = tmp_path / "py" / "python.exe"
    python.parent.mkdir()
    python.write_text("")
    source = tmp_path / "src"
    source.mkdir()
    monkeypatch.setattr(honcho_engine, "engine_python", lambda name: python)
    monkeypatch.setattr(honcho_engine, "honcho_source", lambda: source)
    monkeypatch.setattr(honcho_engine, "memory_engine_llm",
                        lambda: memory_engine_llm(_settings(openrouter="sk-or-1"), _registry("x", "openrouter")))
    monkeypatch.setattr(embedder, "get_embedder", lambda: FakeEmbedder())
    FakePg.instances.clear()
    pg = EnginePostgres(tmp_path / "engines", pg_factory=FakePg, port_picker=lambda: 54500)
    pg.start()
    return honcho_engine, EngineContext(tmp_path / "engines", pg, "http://127.0.0.1:8000"), python, source


def test_honcho_api_spec_runs_migrations_then_sizes_embeddings_once(tmp_path: Path, monkeypatch):
    honcho_engine, context, python, source = _honcho_context(tmp_path, monkeypatch)
    spec = honcho_engine.build_api_spec(context)
    env = spec.env
    assert env["DB_CONNECTION_URI"].startswith("postgresql+psycopg://vellum:")
    assert env["DB_CONNECTION_URI"].endswith("@127.0.0.1:54500/honcho")
    assert env["EMBEDDING_VECTOR_DIMENSIONS"] == "3"
    assert env["EMBEDDING_MODEL_CONFIG__OVERRIDES__BASE_URL"] == "http://127.0.0.1:8000/api/v1"
    assert (env["AUTH_USE_AUTH"], env["CACHE_ENABLED"], env["METRICS_ENABLED"]) == ("false", "false", "false")
    assert env["PEER_CARD_MODEL_CONFIG__OVERRIDES__BASE_URL"] == "https://openrouter.ai/api/v1"
    assert spec.cwd == str(source) and spec.argv[1].endswith("honcho_launcher.py") and spec.argv[2] == "api"
    assert spec.before_start[0] == [str(python), "-m", "alembic", "upgrade", "head"]
    assert spec.before_start[1][-2:] == ["scripts/configure_embeddings.py", "--yes"]

    spec.on_ready()  # first start succeeded: embeddings are sized
    again = honcho_engine.build_api_spec(context)
    assert len(again.before_start) == 1  # only migrations on later starts


def test_honcho_deriver_is_a_worker_without_a_port(tmp_path: Path, monkeypatch):
    honcho_engine, context, _python, _source = _honcho_context(tmp_path, monkeypatch)
    spec = honcho_engine.build_deriver_spec(context)
    assert spec.health_url == "" and spec.argv[2] == "deriver"
    assert spec.env["DB_CONNECTION_URI"].endswith("/honcho")


def test_worker_counts_as_ready_once_it_stays_up(monkeypatch):
    import agent.memory.engines.supervisor as supervisor_module

    clock = {"now": 1000.0}
    monkeypatch.setattr(supervisor_module.time, "time", lambda: clock["now"])

    def sleep(seconds):
        clock["now"] += 2

    supervisor = EngineSupervisor(health_check=lambda url: False, popen=FakeProcess, sleep=sleep)
    spec = EngineSpec(name="worker", argv=["w"], env={}, health_url="", settle_seconds=5)
    supervisor.add_engine("worker", lambda: spec)
    assert supervisor._launch("worker", lambda: spec) is True
    assert supervisor.status()["worker"]["state"] == "ready"


def test_honcho_client_follows_the_embedded_engine(monkeypatch):
    from agent.memory import honcho_client

    honcho = honcho_client.HonchoMemory(base_url="http://localhost:8001", app_id="vellum", user_id="default")
    assert honcho.base_url == "http://localhost:8001"
    monkeypatch.setattr(honcho_client, "embedded_honcho_url", lambda: "http://127.0.0.1:61000")
    assert honcho.base_url == "http://127.0.0.1:61000"


def test_engines_restart_when_the_user_switches_model():
    launches = []

    def popen(argv, **kwargs):
        launches.append(argv[0])
        return FakeProcess(argv)

    choice = {"value": ("ollama", "qwen3.5:9b", "", "")}
    supervisor = EngineSupervisor(health_check=lambda url: True, popen=popen, sleep=lambda s: None)
    supervisor.add_engine("hindsight", lambda: _spec("hindsight"))
    supervisor.add_engine("honcho", lambda: _spec("honcho"))
    supervisor.watch_config(lambda: choice["value"], interval=0)
    supervisor._config_seen = choice["value"]
    for name, factory in supervisor._factories:
        supervisor._launch(name, factory)
    assert launches == ["hindsight", "honcho"]

    assert supervisor._config_changed() is False  # unchanged: no restart
    choice["value"] = ("openrouter", "google/gemma-3-12b-it", "https://openrouter.ai/api/v1", "abc")
    assert supervisor._config_changed() is True
    supervisor.restart_all()
    assert launches == ["hindsight", "honcho", "hindsight", "honcho"]
    assert supervisor._config_changed() is False  # settles on the new choice


def test_memory_llm_signature_tracks_provider_model_and_key(monkeypatch):
    from agent.memory.engines import llm_routing, runtime

    monkeypatch.setattr(llm_routing, "memory_engine_llm",
                        lambda: llm_routing.EngineLLM(provider="groq", model="m", api_key="secret-key"))
    signature = runtime.memory_llm_signature()
    assert signature[:2] == ("groq", "m") and signature[3] and "secret-key" not in str(signature)
