from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import time
from urllib.parse import parse_qs, urlparse

import pytest

from agent.knowledge.store import KnowledgeStore
from agent.plugins.portable import PortablePluginContext, load_portable_plugin
from agent.plugins.youtube_runtime import YouTubeKnowledgeSync


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload


def youtube_module():
    return load_portable_plugin(Path("plugins/connectors/youtube")).module


def test_youtube_manifest_registers_read_only_connector() -> None:
    plugin = load_portable_plugin(Path("plugins/connectors/youtube"))
    context = PortablePluginContext()

    plugin.register(context)

    assert plugin.manifest.capabilities == ["youtube.account", "youtube.subscriptions", "youtube.liked_videos"]
    assert context.connectors["youtube"]["capabilities"] == [
        "youtube.account",
        "youtube.subscriptions",
        "youtube.liked_videos",
    ]


def test_youtube_auth_url_uses_readonly_scope_and_pkce() -> None:
    module = youtube_module()
    url = module.auth.authorization_url(
        client_id="desktop-client",
        redirect_uri="http://127.0.0.1:8000/callback",
        state="state-value",
        code_challenge="challenge-value",
    )
    query = parse_qs(urlparse(url).query)

    assert query["scope"] == ["https://www.googleapis.com/auth/youtube.readonly"]
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["state-value"]


def test_youtube_auth_store_keeps_tokens_out_of_runtime_files(tmp_path: Path) -> None:
    module = youtube_module()
    keyring = FakeKeyring()
    store = module.auth.YouTubeAuthStore(tmp_path, keyring_backend=keyring)

    store.save_tokens(
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/youtube.readonly",
        }
    )
    store.save_profile({"channel_id": "UC-primary", "title": "Primary channel"})

    persisted = store.metadata_path.read_text(encoding="utf-8")
    assert "access-secret" not in persisted
    assert "refresh-secret" not in persisted
    assert store.load_tokens()["refresh_token"] == "refresh-secret"
    assert store.load_metadata()["channel_id"] == "UC-primary"


def test_youtube_auth_flow_is_single_use_and_state_checked(tmp_path: Path) -> None:
    module = youtube_module()
    store = module.auth.YouTubeAuthStore(tmp_path, keyring_backend=FakeKeyring())
    store.save_flow({"state": "expected", "created_at": time.time(), "code_verifier": "verifier"})

    with pytest.raises(module.errors.YouTubeAuthError, match="did not match"):
        store.consume_flow("wrong", max_age_seconds=1000)

    flow = store.consume_flow("expected", max_age_seconds=1000)
    assert flow["code_verifier"] == "verifier"
    assert not store.flow_path.exists()


def test_youtube_client_refreshes_and_paginates_subscriptions(tmp_path: Path) -> None:
    module = youtube_module()
    store = module.auth.YouTubeAuthStore(tmp_path, keyring_backend=FakeKeyring())
    store.save_tokens(
        {
            "access_token": "expired-access",
            "refresh_token": "refresh-token",
            "expires_at": 1,
        }
    )
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if url == module.auth.TOKEN_URL:
            return FakeResponse({"access_token": "fresh-access", "expires_in": 3600})
        page_token = str(kwargs.get("params", {}).get("pageToken") or "")
        if not page_token:
            return FakeResponse(
                {
                    "items": [
                        {
                            "id": "sub-1",
                            "snippet": {
                                "title": "Channel One",
                                "resourceId": {"channelId": "UC-one"},
                            },
                        }
                    ],
                    "nextPageToken": "next",
                }
            )
        return FakeResponse(
            {
                "items": [
                    {
                        "id": "sub-2",
                        "snippet": {
                            "title": "Channel Two",
                            "resourceId": {"channelId": "UC-two"},
                        },
                    }
                ]
            }
        )

    client = module.client.YouTubeClient(
        client_id="client",
        client_secret="secret",
        store=store,
        request_backend=request,
        clock=lambda: 100.0,
    )

    subscriptions = client.list_subscriptions()

    assert [item["channel_id"] for item in subscriptions] == ["UC-one", "UC-two"]
    assert store.load_tokens()["access_token"] == "fresh-access"
    assert calls[0]["data"]["refresh_token"] == "refresh-token"
    assert calls[1]["headers"]["Authorization"] == "Bearer fresh-access"
    assert calls[2]["params"]["pageToken"] == "next"


def test_youtube_client_lists_liked_videos_from_related_playlist(tmp_path: Path) -> None:
    module = youtube_module()
    store = module.auth.YouTubeAuthStore(tmp_path, keyring_backend=FakeKeyring())
    store.save_tokens({"access_token": "access", "expires_at": 10_000})

    def request(_method: str, url: str, **kwargs):
        if url.endswith("/channels"):
            return FakeResponse(
                {
                    "items": [
                        {
                            "id": "UC-primary",
                            "snippet": {"title": "Primary channel"},
                            "contentDetails": {"relatedPlaylists": {"likes": "LL-primary"}},
                        }
                    ]
                }
            )
        assert url.endswith("/playlistItems")
        assert kwargs["params"]["playlistId"] == "LL-primary"
        return FakeResponse(
            {
                "items": [
                    {
                        "id": "playlist-item-1",
                        "snippet": {
                            "title": "A liked video",
                            "description": "Description",
                            "publishedAt": "2026-07-20T12:00:00Z",
                            "videoOwnerChannelId": "UC-owner",
                            "videoOwnerChannelTitle": "Owner channel",
                            "resourceId": {"videoId": "liked123456"},
                        },
                        "contentDetails": {"videoId": "liked123456", "videoPublishedAt": "2026-07-19T12:00:00Z"},
                    }
                ]
            }
        )

    client = module.client.YouTubeClient(
        client_id="client",
        client_secret="secret",
        store=store,
        request_backend=request,
        clock=lambda: 100.0,
    )

    videos = client.list_liked_videos(max_results=10)

    assert videos == [
        {
            "playlist_item_id": "playlist-item-1",
            "video_id": "liked123456",
            "title": "A liked video",
            "description": "Description",
            "channel_id": "UC-owner",
            "channel_title": "Owner channel",
            "published_at": "2026-07-19T12:00:00Z",
            "added_at": "2026-07-20T12:00:00Z",
            "url": "https://www.youtube.com/watch?v=liked123456",
        }
    ]


def test_youtube_code_exchange_requires_readonly_scope(tmp_path: Path) -> None:
    module = youtube_module()
    store = module.auth.YouTubeAuthStore(tmp_path, keyring_backend=FakeKeyring())

    def request(_method: str, _url: str, **_kwargs):
        return FakeResponse(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": "openid",
            }
        )

    client = module.client.YouTubeClient(
        client_id="client",
        client_secret="secret",
        store=store,
        request_backend=request,
    )

    with pytest.raises(module.errors.YouTubeAuthError, match="read-only permission"):
        client.exchange_code(code="code", redirect_uri="http://127.0.0.1:8000", code_verifier="verifier")

    assert store.load_tokens(required=False) == {}


class FakeProfileStore:
    def __init__(self) -> None:
        self.profile = None

    def save_profile(self, profile: dict) -> None:
        self.profile = dict(profile)


class FakeYouTubeClient:
    def __init__(self) -> None:
        self.store = FakeProfileStore()
        self.subscriptions = [
            {"channel_id": "UC-one", "title": "Channel One", "channel_url": "https://youtube.test/one"},
            {"channel_id": "UC-two", "title": "Channel Two", "channel_url": "https://youtube.test/two"},
        ]

    def get_my_channel(self) -> dict:
        return {"channel_id": "UC-primary", "title": "Primary channel", "description": ""}

    def list_subscriptions(self) -> list[dict]:
        return list(self.subscriptions)


def test_youtube_sync_is_idempotent_and_deactivates_missing_subscriptions(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")
    core = SimpleNamespace(store=store)
    client = FakeYouTubeClient()
    sync = YouTubeKnowledgeSync(client=client, core=core)

    first = sync.run(idempotency_key="snapshot-1")
    replay = sync.run(idempotency_key="snapshot-1")
    client.subscriptions = client.subscriptions[:1]
    second = sync.run(idempotency_key="snapshot-2")

    assert first["status"] == "completed"
    assert replay["should_run"] is False
    assert second["stats"]["subscriptions_deactivated"] == 1
    sources = store.list_sources(kind="youtube_subscription")
    assert len(sources) == 2
    statuses = {source["external_id"]: source["status"] for source in sources}
    assert statuses["youtube:subscription:UC-primary:UC-one"] == "active"
    assert statuses["youtube:subscription:UC-primary:UC-two"] == "inactive"
    assert first["stats"]["versions_created"] == 3
    assert second["stats"]["versions_created"] == 0
    assert client.store.profile["channel_id"] == "UC-primary"


def test_youtube_client_errors_do_not_include_provider_payload(tmp_path: Path) -> None:
    module = youtube_module()
    store = module.auth.YouTubeAuthStore(tmp_path, keyring_backend=FakeKeyring())

    def request(_method: str, _url: str, **_kwargs):
        return FakeResponse({"error": "refresh_token=provider-secret"}, status_code=400)

    client = module.client.YouTubeClient(
        client_id="client",
        client_secret="secret",
        store=store,
        request_backend=request,
    )

    with pytest.raises(module.errors.YouTubeAuthError) as error:
        client.exchange_code(code="code", redirect_uri="http://localhost", code_verifier="verifier")

    assert "provider-secret" not in str(error.value)
