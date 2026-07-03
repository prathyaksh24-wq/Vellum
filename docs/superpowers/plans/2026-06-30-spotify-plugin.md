# Spotify Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Hermes-compatible Spotify plugin that gives Vellum full Spotify Web API control through natural-language tools and a compact player in the approved HTML UI.

**Architecture:** A portable plugin under `plugins/connectors/spotify/` owns schemas, handlers, PKCE, token storage, and Spotify HTTP behavior. Vellum extends its Hermes-style wrapper to register those tools with LangGraph, while FastAPI exposes setup and player endpoints backed by the same plugin service. UI changes are confined to `design/Velllum/uploads/Vellum Default Re-designed.html`.

**Tech Stack:** Python 3.12, FastAPI, LangGraph/LangChain, Pydantic, httpx, pytest, React 18 JSX embedded in HTML, Spotify Web API, OAuth 2.0 Authorization Code with PKCE.

---

## File map

**Create**

- `plugins/connectors/spotify/plugin.yaml` — Hermes/Vellum manifest superset.
- `plugins/connectors/spotify/__init__.py` — registers the connector and seven tools.
- `plugins/connectors/spotify/schemas.py` — exact JSON schemas visible to the model.
- `plugins/connectors/spotify/tools.py` — JSON-string Hermes handlers.
- `plugins/connectors/spotify/client.py` — Spotify HTTP requests, refresh, normalization, and errors.
- `plugins/connectors/spotify/auth.py` — PKCE, atomic local state/token persistence, and logout.
- `plugins/connectors/spotify/errors.py` — sanitized domain exceptions.
- `plugins/connectors/spotify/README.md` — installation, Spotify app setup, and limitations.
- `plugins/connectors/spotify/skills/spotify/SKILL.md` — canonical tool-use patterns.
- `backend/agent/plugins/spotify_runtime.py` — Vellum adapter for loading the plugin service.
- `backend/tests/test_spotify_auth.py` — PKCE and token-store tests.
- `backend/tests/test_spotify_client.py` — Spotify HTTP/refresh/error tests.
- `backend/tests/test_spotify_tools.py` — all seven handler groups.
- `backend/tests/test_spotify_api.py` — setup, status, logout, and player API tests.
- `backend/tests/test_spotify_agent.py` — dynamic LangGraph tool registration tests.

**Modify**

- `backend/agent/plugins/portable.py` — package-safe loading and Hermes `register_tool()` support.
- `backend/agent/graph/agent.py` — append authenticated portable tools to both agent builders and invalidate cached agents.
- `backend/agent/api.py` — Spotify OAuth/status/player endpoints.
- `backend/tests/test_portable_plugins.py` — portable tool and relative-import coverage.
- `backend/tests/test_agent_prompt.py` — authenticated/unauthenticated tool-list coverage.
- `backend/tests/test_api.py` — catalog metadata coverage for Spotify.
- `design/Velllum/uploads/Vellum Default Re-designed.html` — connection wizard and global player; no other UI file changes.

## Task 1: Make portable plugins load real Hermes tool packages

**Files:**

- Modify: `backend/agent/plugins/portable.py`
- Modify: `backend/tests/test_portable_plugins.py`

- [ ] **Step 1: Write failing tests for relative imports and tool registration**

Add tests that build a temporary plugin containing `plugin.yaml`, `schemas.py`, `tools.py`, and `__init__.py` with `from . import schemas, tools`:

```python
def test_portable_plugin_supports_relative_imports_and_register_tool(tmp_path):
    plugin_dir = tmp_path / "plugins" / "connectors" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "id: demo\nname: Demo\ntype: connector\ncategory: Connectors\n"
        "provides_tools:\n  - demo_echo\ncapabilities:\n  - demo.echo\n",
        encoding="utf-8",
    )
    (plugin_dir / "schemas.py").write_text(
        "ECHO = {'name': 'demo_echo', 'description': 'Echo text', "
        "'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, "
        "'required': ['text']}}\n",
        encoding="utf-8",
    )
    (plugin_dir / "tools.py").write_text(
        "import json\ndef echo(args, **kwargs): return json.dumps({'text': args['text']})\n",
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "from . import schemas, tools\n"
        "def register(ctx):\n"
        "    ctx.register_tool(name='demo_echo', toolset='demo', "
        "schema=schemas.ECHO, handler=tools.echo)\n",
        encoding="utf-8",
    )

    ctx = PortablePluginContext()
    load_portable_plugin(plugin_dir).register(ctx)

    assert ctx.tools["demo_echo"].toolset == "demo"
    assert ctx.tools["demo_echo"].handler({"text": "hello"}) == '{"text": "hello"}'


def test_register_tool_rejects_duplicate_names():
    ctx = PortablePluginContext()
    schema = {"name": "same", "description": "x", "parameters": {"type": "object"}}
    ctx.register_tool(name="same", toolset="one", schema=schema, handler=lambda args: "{}")
    with pytest.raises(ValueError, match="already registered"):
        ctx.register_tool(name="same", toolset="two", schema=schema, handler=lambda args: "{}")
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest backend/tests/test_portable_plugins.py -v`

Expected: the relative import fails or `PortablePluginContext` has no `register_tool`/`tools` member.

- [ ] **Step 3: Add the portable tool record and package-safe loader**

Implement this public shape in `portable.py`:

```python
@dataclass(frozen=True)
class PortableRegisteredTool:
    name: str
    toolset: str
    schema: dict[str, Any]
    handler: Callable[..., str]


class PortablePluginContext:
    def __init__(self) -> None:
        self.connectors: dict[str, dict[str, Any]] = {}
        self.system_plugins: dict[str, dict[str, Any]] = {}
        self.memory_providers: dict[str, dict[str, Any]] = {}
        self.tools: dict[str, PortableRegisteredTool] = {}

    def register_tool(self, *, name: str, toolset: str, schema: dict[str, Any], handler: Callable[..., str]) -> None:
        if name in self.tools:
            raise ValueError(f"{name} is already registered")
        if schema.get("name") != name or not callable(handler):
            raise ValueError(f"Invalid portable tool registration: {name}")
        self.tools[name] = PortableRegisteredTool(name, toolset, dict(schema), handler)
```

Change `load_portable_plugin()` to create a real package:

```python
module_name = "vellum_portable_plugin_" + manifest.id.replace("-", "_")
spec = importlib.util.spec_from_file_location(
    module_name,
    init_path,
    submodule_search_locations=[str(plugin_dir)],
)
if spec is None or spec.loader is None:
    raise ImportError(f"Cannot load portable plugin: {plugin_dir}")
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
try:
    spec.loader.exec_module(module)
except Exception:
    sys.modules.pop(module_name, None)
    raise
```

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest backend/tests/test_portable_plugins.py -v`

Expected: all portable-plugin tests pass.

- [ ] **Step 5: Commit the adapter foundation**

```bash
git add backend/agent/plugins/portable.py backend/tests/test_portable_plugins.py
git commit -m "feat: support Hermes portable tool registration"
```

## Task 2: Add the Spotify manifest, schemas, and bundled skill

**Files:**

- Create: `plugins/connectors/spotify/plugin.yaml`
- Create: `plugins/connectors/spotify/schemas.py`
- Create: `plugins/connectors/spotify/skills/spotify/SKILL.md`
- Create: `plugins/connectors/spotify/README.md`
- Modify: `backend/tests/test_portable_plugins.py`

- [ ] **Step 1: Write a failing manifest/schema discovery test**

```python
def test_spotify_manifest_declares_full_hermes_toolset():
    manifests = {item.id: item for item in discover_portable_plugins(Path("plugins"))}
    spotify = manifests["spotify"]
    assert spotify.type == "connector"
    assert spotify.category == "Connectors"
    assert spotify.capabilities == [
        "spotify.playback", "spotify.devices", "spotify.queue", "spotify.search",
        "spotify.playlists", "spotify.albums", "spotify.library",
    ]
```

- [ ] **Step 2: Run the test and verify it fails with missing Spotify manifest**

Run: `python -m pytest backend/tests/test_portable_plugins.py::test_spotify_manifest_declares_full_hermes_toolset -v`

Expected: FAIL because `spotify` is absent.

- [ ] **Step 3: Create the manifest**

```yaml
id: spotify
name: Spotify
type: connector
category: Connectors
version: 1.0.0
description: Full Spotify Web API control through a Hermes-compatible Vellum plugin.
provides_tools:
  - spotify_playback
  - spotify_devices
  - spotify_queue
  - spotify_search
  - spotify_playlists
  - spotify_albums
  - spotify_library
capabilities:
  - spotify.playback
  - spotify.devices
  - spotify.queue
  - spotify.search
  - spotify.playlists
  - spotify.albums
  - spotify.library
```

- [ ] **Step 4: Define all seven model-facing schemas**

In `schemas.py`, define `SPOTIFY_PLAYBACK`, `SPOTIFY_DEVICES`, `SPOTIFY_QUEUE`, `SPOTIFY_SEARCH`, `SPOTIFY_PLAYLISTS`, `SPOTIFY_ALBUMS`, and `SPOTIFY_LIBRARY`. Each schema must use an action enum matching the approved design and must make action-specific identifiers optional at the JSON-schema layer so handlers can return sanitized validation errors. Export:

```python
ALL_SCHEMAS = [
    SPOTIFY_PLAYBACK,
    SPOTIFY_DEVICES,
    SPOTIFY_QUEUE,
    SPOTIFY_SEARCH,
    SPOTIFY_PLAYLISTS,
    SPOTIFY_ALBUMS,
    SPOTIFY_LIBRARY,
]
```

The playback action enum is exactly:

```python
[
    "get_state", "get_currently_playing", "play", "pause", "next", "previous",
    "seek", "set_repeat", "set_shuffle", "set_volume", "recently_played",
]
```

- [ ] **Step 5: Write the bundled skill and README**

The skill must state these deterministic rules:

- Search once, select the strongest exact match, then play its URI.
- Do not call `get_state` before an explicit pause/next/previous command.
- List devices only when the user names a device or Spotify reports no active device.
- Never expose tokens, Client IDs, local paths, or raw Spotify error bodies.
- Treat 204 currently-playing responses as a valid inactive state.
- Explain Premium requirements only when Spotify rejects a mutating action.

The README must document the redirect URI, Premium boundary, active-device requirement, local token path, and the seven tools.

- [ ] **Step 6: Run the manifest test and commit**

Run: `python -m pytest backend/tests/test_portable_plugins.py -v`

Expected: PASS.

```bash
git add plugins/connectors/spotify backend/tests/test_portable_plugins.py
git commit -m "feat: define Spotify portable plugin contract"
```

## Task 3: Implement PKCE and local credential storage

**Files:**

- Create: `plugins/connectors/spotify/auth.py`
- Create: `plugins/connectors/spotify/errors.py`
- Create: `backend/tests/test_spotify_auth.py`

- [ ] **Step 1: Write failing PKCE and persistence tests**

Cover deterministic challenge generation, state expiry, atomic token writes, state mismatch, and logout:

```python
def test_pkce_challenge_uses_s256():
    verifier = "a" * 64
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert pkce_challenge(verifier) == expected


def test_complete_flow_rejects_wrong_state(tmp_path):
    store = SpotifyAuthStore(tmp_path)
    store.save_flow({"state": "expected", "code_verifier": "v", "created_at": time.time()})
    with pytest.raises(SpotifyAuthError, match="state"):
        store.consume_flow("wrong")


def test_logout_removes_tokens_and_flow(tmp_path):
    store = SpotifyAuthStore(tmp_path)
    store.save_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 1})
    store.save_flow({"state": "s", "code_verifier": "v", "created_at": time.time()})
    store.logout()
    assert not store.auth_path.exists()
    assert not store.flow_path.exists()
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest backend/tests/test_spotify_auth.py -v`

Expected: import failure because the auth module does not exist.

- [ ] **Step 3: Implement errors, PKCE, URLs, and stores**

Define sanitized exceptions:

```python
class SpotifyError(RuntimeError):
    code = "spotify_error"

class SpotifyAuthError(SpotifyError):
    code = "spotify_auth_error"

class SpotifyPremiumRequired(SpotifyError):
    code = "premium_required"

class SpotifyNoActiveDevice(SpotifyError):
    code = "no_active_device"

class SpotifyRateLimited(SpotifyError):
    code = "rate_limited"

    def __init__(self, retry_after: int):
        super().__init__("Spotify rate limit reached")
        self.retry_after = retry_after
```

Implement `SpotifyAuthStore(root: Path)`, `new_pkce_pair()`, `pkce_challenge()`, `authorization_url()`, `save_tokens()`, `load_tokens()`, `save_flow()`, `consume_flow()`, and `logout()`. Use `tempfile.NamedTemporaryFile(delete=False, dir=target.parent)` followed by `os.replace()` for atomic JSON writes. Flow state expires after ten minutes.

- [ ] **Step 4: Run auth tests and commit**

Run: `python -m pytest backend/tests/test_spotify_auth.py -v`

Expected: PASS.

```bash
git add plugins/connectors/spotify/auth.py plugins/connectors/spotify/errors.py backend/tests/test_spotify_auth.py
git commit -m "feat: add Spotify PKCE credential store"
```

## Task 4: Implement the Spotify Web API client

**Files:**

- Create: `plugins/connectors/spotify/client.py`
- Create: `backend/tests/test_spotify_client.py`

- [ ] **Step 1: Write failing HTTP behavior tests**

Use `httpx.MockTransport` to verify authorization headers, one refresh/retry on 401, 204 normalization, 403 mapping, and `Retry-After` handling:

```python
def test_401_refreshes_and_retries_once(auth_store, mock_transport):
    client = SpotifyClient(auth_store=auth_store, transport=mock_transport)
    result = client.request("GET", "/me/player")
    assert result["is_playing"] is True
    assert mock_transport.calls == ["GET /me/player", "POST /api/token", "GET /me/player"]


def test_204_is_inactive_state(auth_store):
    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    result = SpotifyClient(auth_store=auth_store, transport=transport).request("GET", "/me/player/currently-playing")
    assert result == {"is_playing": False, "item": None}


def test_429_uses_retry_after(auth_store):
    transport = httpx.MockTransport(lambda request: httpx.Response(429, headers={"Retry-After": "12"}))
    with pytest.raises(SpotifyRateLimited) as caught:
        SpotifyClient(auth_store=auth_store, transport=transport).request("GET", "/me/player")
    assert caught.value.retry_after == 12
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest backend/tests/test_spotify_client.py -v`

Expected: import failure because `SpotifyClient` does not exist.

- [ ] **Step 3: Implement request, refresh, and normalized errors**

Implement these entry points:

```python
class SpotifyClient:
    API_BASE = "https://api.spotify.com/v1"
    TOKEN_URL = "https://accounts.spotify.com/api/token"

    def __init__(self, auth_store: SpotifyAuthStore, transport: httpx.BaseTransport | None = None):
        self.auth_store = auth_store
        self.transport = transport

    def request(self, method: str, path: str, *, params=None, json_body=None, content=None) -> dict:
        return self._request(method, path, params=params, json_body=json_body, content=content, retried=False)

    def exchange_code(self, *, client_id: str, code: str, code_verifier: str, redirect_uri: str) -> dict:
        return self._token_request({
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        })

    def refresh(self) -> dict:
        saved = self.auth_store.load_tokens()
        refreshed = self._token_request({
            "client_id": saved["client_id"],
            "grant_type": "refresh_token",
            "refresh_token": saved["refresh_token"],
        })
        refreshed.setdefault("refresh_token", saved["refresh_token"])
        self.auth_store.save_tokens({**saved, **refreshed})
        return refreshed
```

Map 403 messages to `SpotifyPremiumRequired` or `SpotifyNoActiveDevice` using only status and safe reason matching. Never return raw response bodies from exceptions.

- [ ] **Step 4: Add small endpoint helpers and normalization**

Add `get_profile()`, `get_player()`, `get_devices()`, and `get_queue()` helpers. Normalize player payloads into stable fields: `is_playing`, `progress_ms`, `duration_ms`, `track`, `artists`, `album`, `artwork_url`, `device`, `shuffle`, and `repeat`.

- [ ] **Step 5: Run client tests and commit**

Run: `python -m pytest backend/tests/test_spotify_client.py -v`

Expected: PASS.

```bash
git add plugins/connectors/spotify/client.py backend/tests/test_spotify_client.py
git commit -m "feat: add resilient Spotify Web API client"
```

## Task 5: Implement and register all seven Hermes handlers

**Files:**

- Create: `plugins/connectors/spotify/tools.py`
- Create: `plugins/connectors/spotify/__init__.py`
- Create: `backend/tests/test_spotify_tools.py`

- [ ] **Step 1: Write parameterized failing handler tests**

Test every action-to-endpoint mapping and JSON-string return contract. Include at least these representative assertions:

```python
@pytest.mark.parametrize(
    ("handler", "args", "method", "path"),
    [
        (spotify_playback, {"action": "pause"}, "PUT", "/me/player/pause"),
        (spotify_playback, {"action": "next"}, "POST", "/me/player/next"),
        (spotify_devices, {"action": "list"}, "GET", "/me/player/devices"),
        (spotify_queue, {"action": "get"}, "GET", "/me/player/queue"),
        (spotify_search, {"query": "Kind of Blue"}, "GET", "/search"),
        (spotify_playlists, {"action": "list"}, "GET", "/me/playlists"),
        (spotify_albums, {"action": "get", "album_id": "a1"}, "GET", "/albums/a1"),
        (spotify_library, {"kind": "tracks", "action": "list"}, "GET", "/me/tracks"),
    ],
)
def test_handler_routes(handler, args, method, path, fake_service):
    result = json.loads(handler(args, service=fake_service))
    assert result["ok"] is True
    assert fake_service.last_request[:2] == (method, path)
```

Also verify missing required action-specific arguments return `{"ok": false, "error": {"code": "invalid_arguments"}}` and that exceptions never propagate.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/test_spotify_tools.py -v`

Expected: handler imports fail.

- [ ] **Step 3: Implement shared handler utilities**

Use one boundary for all results:

```python
def _result(call: Callable[[], dict]) -> str:
    try:
        return json.dumps({"ok": True, "data": call()}, ensure_ascii=False)
    except SpotifyRateLimited as exc:
        return json.dumps({"ok": False, "error": {"code": exc.code, "retry_after": exc.retry_after}})
    except SpotifyError as exc:
        return json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}})
    except Exception:
        return json.dumps({"ok": False, "error": {"code": "unreachable", "message": "Unreachable."}})


def _need(args: dict, *names: str) -> str | None:
    missing = [name for name in names if args.get(name) in (None, "", [])]
    return ", ".join(missing) if missing else None
```

- [ ] **Step 4: Implement all action maps**

Implement every action listed in the approved specification. Use Spotify's documented endpoint semantics, including `uris` query values for library save/remove, `snapshot_id` for playlist removal, `position_ms` for seek, `state` for repeat, and a JSON boolean array for transfer playback.

Export the seven public handlers under these exact names and verify the binding table at import time:

```python
HANDLERS = {
    "spotify_playback": spotify_playback,
    "spotify_devices": spotify_devices,
    "spotify_queue": spotify_queue,
    "spotify_search": spotify_search,
    "spotify_playlists": spotify_playlists,
    "spotify_albums": spotify_albums,
    "spotify_library": spotify_library,
}

if any(not callable(handler) for handler in HANDLERS.values()):
    raise RuntimeError("Spotify handler registration is incomplete")
```

Each handler accepts `(args: dict, **kwargs) -> str`, resolves `kwargs.get("service") or get_spotify_service()`, validates action-specific fields with `_need`, and returns through `_result`.

- [ ] **Step 5: Register the connector and schemas**

`__init__.py` imports `schemas` and `tools`, registers connector status/service factories, then registers each pair from a fixed tuple:

```python
TOOL_BINDINGS = (
    (schemas.SPOTIFY_PLAYBACK, tools.spotify_playback),
    (schemas.SPOTIFY_DEVICES, tools.spotify_devices),
    (schemas.SPOTIFY_QUEUE, tools.spotify_queue),
    (schemas.SPOTIFY_SEARCH, tools.spotify_search),
    (schemas.SPOTIFY_PLAYLISTS, tools.spotify_playlists),
    (schemas.SPOTIFY_ALBUMS, tools.spotify_albums),
    (schemas.SPOTIFY_LIBRARY, tools.spotify_library),
)

def register(ctx) -> None:
    ctx.register_connector(
        id="spotify",
        name="Spotify",
        category="Connectors",
        status_factory=spotify_status,
        service_factory=get_spotify_service,
        capabilities=[schema["name"] for schema, _handler in TOOL_BINDINGS],
    )
    for schema, handler in TOOL_BINDINGS:
        ctx.register_tool(name=schema["name"], toolset="spotify", schema=schema, handler=handler)
```

- [ ] **Step 6: Run all handler tests and commit**

Run: `python -m pytest backend/tests/test_spotify_tools.py backend/tests/test_portable_plugins.py -v`

Expected: PASS.

```bash
git add plugins/connectors/spotify backend/tests/test_spotify_tools.py backend/tests/test_portable_plugins.py
git commit -m "feat: implement full Spotify Hermes toolset"
```

## Task 6: Inject authenticated plugin tools into Vellum's agents

**Files:**

- Create: `backend/agent/plugins/spotify_runtime.py`
- Modify: `backend/agent/graph/agent.py`
- Create: `backend/tests/test_spotify_agent.py`
- Modify: `backend/tests/test_agent_prompt.py`

- [ ] **Step 1: Write failing dynamic-tool tests**

```python
def test_spotify_tools_absent_when_not_authenticated(monkeypatch):
    monkeypatch.setattr(spotify_runtime, "spotify_is_authenticated", lambda: False)
    assert not any(tool.name.startswith("spotify_") for tool in agent_graph.portable_agent_tools())


def test_spotify_tools_present_when_authenticated(monkeypatch):
    monkeypatch.setattr(spotify_runtime, "spotify_is_authenticated", lambda: True)
    names = {tool.name for tool in agent_graph.portable_agent_tools()}
    assert names == {
        "spotify_playback", "spotify_devices", "spotify_queue", "spotify_search",
        "spotify_playlists", "spotify_albums", "spotify_library",
    }
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/test_spotify_agent.py -v`

Expected: `portable_agent_tools` is missing.

- [ ] **Step 3: Build LangChain tools from Hermes registrations**

Load and register the Spotify plugin through `PortablePluginContext`. Convert each registered tool using `StructuredTool.from_function` with the JSON schema's `parameters` dictionary as `args_schema`:

```python
def _as_langchain_tool(record: PortableRegisteredTool) -> StructuredTool:
    def invoke(**kwargs):
        return record.handler(kwargs)
    return StructuredTool.from_function(
        func=invoke,
        name=record.name,
        description=str(record.schema["description"]),
        args_schema=dict(record.schema["parameters"]),
    )
```

`portable_agent_tools()` returns an empty list until `spotify_is_authenticated()` succeeds, then returns all seven tools.

- [ ] **Step 4: Append tools to both agent builders and add invalidation**

Define `core_tools()` once to prevent sync/async drift. Both `build_agent()` and `build_async_agent()` use `tools=[*core_tools(), *portable_agent_tools()]`.

Add:

```python
class LazyAgent:
    def invalidate(self) -> None:
        self._agent = None
        self._async_agent = None
```

OAuth completion and logout will call `agent.invalidate()`.

- [ ] **Step 5: Run agent tests and commit**

Run: `python -m pytest backend/tests/test_spotify_agent.py backend/tests/test_agent_prompt.py -v`

Expected: PASS and both builders contain identical Spotify tool names.

```bash
git add backend/agent/plugins/spotify_runtime.py backend/agent/graph/agent.py backend/tests/test_spotify_agent.py backend/tests/test_agent_prompt.py
git commit -m "feat: route Spotify tools through Vellum agent"
```

## Task 7: Add Spotify OAuth, status, and player APIs

**Files:**

- Modify: `backend/agent/api.py`
- Create: `backend/tests/test_spotify_api.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Cover status without secrets, OAuth start/callback, mismatched state, logout invalidation, inactive player, direct controls, and plugin catalog metadata:

```python
def test_spotify_status_never_returns_credentials(client, connected_spotify):
    response = client.get("/api/plugins/spotify/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True
    serialized = json.dumps(payload).lower()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_id" not in serialized


def test_spotify_player_action_is_allowlisted(client, connected_spotify):
    response = client.post("/api/plugins/spotify/player/action", json={"action": "delete_playlist"})
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/test_spotify_api.py -v`

Expected: 404 responses.

- [ ] **Step 3: Add Pydantic request/response models**

Define `SpotifyOAuthStartRequest(client_id)`, `SpotifyOAuthStartResponse(authorization_url, redirect_uri)`, `SpotifyStatusResponse`, and `SpotifyPlayerActionRequest`. Player action is a `Literal` limited to `play`, `pause`, `next`, `previous`, `seek`, `set_volume`, `set_shuffle`, `set_repeat`, and `transfer`.

- [ ] **Step 4: Implement OAuth and status endpoints**

Use these routes exactly:

```text
GET  /api/plugins/spotify/status
POST /api/plugins/spotify/oauth/start
GET  /api/plugins/spotify/oauth/callback
POST /api/plugins/spotify/logout
```

The callback validates persisted state, exchanges the code in a worker thread, stores tokens, clears flow state, invalidates the lazy agent, and returns an HTML page that posts `vellum:spotify-oauth-complete` to its opener.

- [ ] **Step 5: Implement player endpoints through the shared service**

```text
GET  /api/plugins/spotify/player
POST /api/plugins/spotify/player/action
```

Map direct actions to the same handlers used by agent tools. Decode their JSON-string result and translate invalid arguments to HTTP 422, unauthenticated state to 401, rate limits to 429 with `Retry-After`, and Spotify availability failures to 503.

- [ ] **Step 6: Include Spotify in `/api/plugins`**

Return disconnected Spotify metadata even before authentication. `_attach_portable_plugin_metadata()` must attach its manifest path and seven capabilities without returning local paths to model prompts or audit entries.

- [ ] **Step 7: Run API tests and commit**

Run: `python -m pytest backend/tests/test_spotify_api.py backend/tests/test_api.py -v`

Expected: PASS.

```bash
git add backend/agent/api.py backend/tests/test_spotify_api.py backend/tests/test_api.py
git commit -m "feat: expose Spotify setup and player API"
```

## Task 8: Add the guided Spotify connection UI

**Files:**

- Modify: `design/Velllum/uploads/Vellum Default Re-designed.html`

- [ ] **Step 1: Add a local Spotify API helper inside the approved HTML**

Do not edit any `api/*.js` file. Add a small constant beside existing frontend helpers:

```javascript
const SpotifyAPI = {
  status: () => API.request('/plugins/spotify/status'),
  start: client_id => API.request('/plugins/spotify/oauth/start', {method:'POST', body:{client_id}}),
  logout: () => API.request('/plugins/spotify/logout', {method:'POST'}),
  player: () => API.request('/plugins/spotify/player'),
  action: body => API.request('/plugins/spotify/player/action', {method:'POST', body}),
};
```

Match the actual `API.request` signature already used by `api/client.js`; if it expects `json` instead of `body`, use that established key consistently.

- [ ] **Step 2: Add connection state to `App`**

Add `spotify`, `spotifyConnectOpen`, and `spotifyPlayerOpen` state. Fetch status at startup, listen for both `postMessage` and the localStorage completion marker from the OAuth popup, then refresh status and close the modal.

- [ ] **Step 3: Add Spotify to Plugins settings**

In the existing Plugins tab, render Spotify with one of four states: `not configured`, `connecting`, `connected`, or `reauthentication required`. Connected state shows the account display name and product tier. Actions are Connect/Reconnect and Disconnect.

- [ ] **Step 4: Implement the guided modal**

The modal must:

- Show `http://127.0.0.1:8000/api/plugins/spotify/oauth/callback` as the exact redirect URI.
- Open `https://developer.spotify.com/dashboard` in a new browser tab.
- Accept only a trimmed non-empty Client ID.
- Call `SpotifyAPI.start`, open the returned authorization URL, and show a waiting state.
- Explain that Premium is required for playback mutations and that an active Spotify Connect device is required.
- Never store the Client ID or OAuth tokens in localStorage.

- [ ] **Step 5: Validate the embedded JSX in a browser**

Run: `python -m http.server 8765 --directory design/Velllum/uploads`

Open: `http://127.0.0.1:8765/Vellum%20Default%20Re-designed.html`

Expected: Plugins opens, the Spotify modal renders, and no other UI file changes appear in `git diff --name-only`.

- [ ] **Step 6: Commit the connection UI**

```bash
git add "design/Velllum/uploads/Vellum Default Re-designed.html"
git commit -m "feat: add guided Spotify connection UI"
```

## Task 9: Add the compact global Spotify player

**Files:**

- Modify: `design/Velllum/uploads/Vellum Default Re-designed.html`

- [ ] **Step 1: Add visibility-aware player polling**

Poll every five seconds only when connected and `document.visibilityState === 'visible'`. On 204/inactive state, slow to fifteen seconds. On 429, use `Retry-After` before the next request. Clear every timer on unmount or disconnect.

- [ ] **Step 2: Render the title-bar Spotify pill**

Place the pill before theme/window controls. It contains artwork, truncated track/artist text, play/pause, and next. All icon buttons require accessible labels and stop propagation so they do not open the expanded panel.

- [ ] **Step 3: Render the expanded player panel**

Include previous, play/pause, next, progress/seek, volume, shuffle, repeat, device selector, and up to five queued tracks. Every control uses `SpotifyAPI.action` and refreshes player state after success.

- [ ] **Step 4: Add resilient responsive styles**

Use existing CSS variables. At narrow widths, hide text before controls, keep the pill under 180px, and prevent overlap with title-bar window controls. The panel must stay within the Vellum window and use existing modal/popover shadows and borders.

- [ ] **Step 5: Browser-test player states**

Verify disconnected, connected-idle, playing, paused, no-active-device, Premium-required, rate-limited, and reconnect-required states. Verify light/dark themes and widths of 1280px, 900px, and 640px.

- [ ] **Step 6: Commit the player UI**

```bash
git add "design/Velllum/uploads/Vellum Default Re-designed.html"
git commit -m "feat: add global Spotify player controls"
```

## Task 10: Security, privacy, regression, and packaging verification

**Files:**

- Modify: `backend/tests/test_spotify_auth.py`
- Modify: `backend/tests/test_spotify_client.py`
- Modify: `backend/tests/test_spotify_tools.py`
- Modify: `backend/tests/test_spotify_api.py`
- Modify: `plugins/connectors/spotify/README.md`

- [ ] **Step 1: Add secret-leak regression tests**

Assert that access tokens, refresh tokens, Client IDs, authorization codes, raw response bodies, and `D:\\`/Unix home paths are absent from handler errors, API responses, logs captured by `caplog`, and audit metadata.

- [ ] **Step 2: Add privacy classification tests for catalog entities**

Verify public artist/album/track terms remain usable as Spotify catalog query data while strings containing passwords, financial credentials, or explicit private identifiers are blocked before the Spotify request is sent.

- [ ] **Step 3: Run the focused Spotify suite**

Run:

```bash
python -m pytest \
  backend/tests/test_portable_plugins.py \
  backend/tests/test_spotify_auth.py \
  backend/tests/test_spotify_client.py \
  backend/tests/test_spotify_tools.py \
  backend/tests/test_spotify_agent.py \
  backend/tests/test_spotify_api.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Run backend regression tests**

Run: `python -m pytest backend/tests -q`

Expected: zero failures. Existing unrelated environmental skips are reported separately and are not converted into passes.

- [ ] **Step 5: Verify file scope**

Run: `git diff --name-only HEAD~10..HEAD`

Expected UI scope: the only path under `design/` or `frontend/` is `design/Velllum/uploads/Vellum Default Re-designed.html`.

- [ ] **Step 6: Perform a mocked end-to-end acceptance flow**

Exercise: connect with PKCE, search and play a track, pause, next, transfer device, set volume/shuffle/repeat, inspect/add queue, create/update a playlist, add/remove tracks, inspect album tracks, save/remove library items, and retrieve recent history.

Expected: every action uses a registered Spotify tool or the shared direct-control service; no credential appears in model-visible output.

- [ ] **Step 7: Final documentation and commit**

Update README commands and troubleshooting using verified behavior only, then commit:

```bash
git add plugins/connectors/spotify/README.md backend/tests/test_spotify_*.py
git commit -m "test: verify Spotify plugin privacy and parity"
```

## Completion gate

Before claiming completion:

- Run `git status --short` and preserve unrelated user changes.
- Run the complete focused and backend test commands above.
- Inspect the exact HTML in a browser and record console/network failures.
- Confirm the seven tools appear only after authentication.
- Confirm logout removes local credentials and removes Spotify tools on the next agent build.
- Confirm the UI file constraint was respected.
- Use `superpowers:verification-before-completion` before the final report.
