"""Vellum runtime adapter for the portable YouTube connector."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from agent.config import REPO_ROOT, get_settings
from agent.knowledge.ingestion import IngestionCoordinator, IngestionResult
from agent.knowledge.models import ExternalPolicy, IngestionJobInput, Sensitivity, SourceItemInput
from agent.knowledge.runtime import get_knowledge_core
from agent.plugins.portable import load_portable_plugin


PLUGIN_DIR = REPO_ROOT / "plugins" / "connectors" / "youtube"
AUTH_DIR = REPO_ROOT / "data" / "plugins" / "youtube"


@lru_cache(maxsize=1)
def youtube_plugin():
    return load_portable_plugin(PLUGIN_DIR)


_youtube_module = youtube_plugin().module
YouTubeAuthError = _youtube_module.errors.YouTubeAuthError
YouTubeAPIError = _youtube_module.errors.YouTubeAPIError


def youtube_store(*, keyring_backend: Any | None = None):
    settings = get_settings()
    return _youtube_module.auth.YouTubeAuthStore(
        AUTH_DIR,
        keyring_backend=keyring_backend,
        keyring_service=settings.youtube_oauth_keyring_service,
        account_label=settings.youtube_oauth_account_label,
    )


def youtube_client(*, store: Any | None = None, request_backend: Any | None = None):
    settings = get_settings()
    return _youtube_module.client.YouTubeClient(
        client_id=settings.youtube_oauth_client_id,
        client_secret=settings.youtube_oauth_client_secret,
        store=store or youtube_store(),
        request_backend=request_backend,
    )


def youtube_authorization_url(**kwargs: Any) -> str:
    return _youtube_module.auth.authorization_url(**kwargs)


def youtube_pkce_pair() -> tuple[str, str]:
    return _youtube_module.auth.new_pkce_pair()


def youtube_status() -> dict[str, Any]:
    settings = get_settings()
    store = youtube_store()
    try:
        connected = bool(store.load_tokens(required=False))
        metadata = store.load_metadata()
        credential_status = "ready" if connected else "not_connected"
    except YouTubeAuthError:
        connected = False
        metadata = {}
        credential_status = "keyring_unavailable"
    return {
        "configured": bool(settings.youtube_oauth_client_id),
        "connected": connected,
        "status": credential_status if settings.youtube_oauth_client_id else "not_configured",
        "account_label": settings.youtube_oauth_account_label,
        "channel_id": str(metadata.get("channel_id") or ""),
        "channel_title": str(metadata.get("channel_title") or ""),
        "scopes": str(metadata.get("scope") or "").split(),
    }


def portable_youtube_status() -> dict[str, Any]:
    status = youtube_status()
    connected = bool(status["connected"])
    return {
        "id": "youtube",
        "name": "YouTube",
        "type": "connector",
        "category": "Connectors",
        "configured": bool(status["configured"]),
        "status": str(status["status"]),
        "notes": (
            f"Connected to {status['channel_title'] or 'the primary YouTube channel'}."
            if connected
            else "Connect a YouTube account for read-only subscription synchronization."
        ),
        "capabilities": ["youtube.account", "youtube.subscriptions", "youtube.liked_videos"],
    }


class YouTubeKnowledgeSync:
    def __init__(self, *, client: Any | None = None, core: Any | None = None) -> None:
        self.client = client or youtube_client()
        self.core = core or get_knowledge_core()

    def run(self, *, idempotency_key: str, requested_by: str = "user") -> dict[str, Any]:
        profile = self.client.get_my_channel()
        channel_id = str(profile["channel_id"])
        self.client.store.save_profile(profile)
        coordinator = IngestionCoordinator(self.core.store)
        return coordinator.run(
            IngestionJobInput(
                connector="youtube_oauth",
                account_id=channel_id,
                job_type="subscription_snapshot",
                idempotency_key=idempotency_key,
                requested_by=requested_by,
                lease_seconds=900,
            ),
            operation=lambda _cursor: self._sync_snapshot(profile),
        )

    def _sync_snapshot(self, profile: dict[str, Any]) -> IngestionResult:
        channel_id = str(profile["channel_id"])
        subscriptions = self.client.list_subscriptions()
        profile_result = self.core.store.upsert_source(
            SourceItemInput(
                kind="youtube_account",
                external_id=f"youtube:channel:{channel_id}",
                account_id=channel_id,
                title=str(profile.get("title") or "YouTube account"),
                uri=f"https://www.youtube.com/channel/{channel_id}",
                content=_canonical_json(profile),
                sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                external_policy=ExternalPolicy.DENY_RAW,
                trust="official_oauth",
                metadata={"connector": "youtube_oauth", "evidence_role": "account_identity"},
            )
        )

        created = int(profile_result["created"])
        versions = int(profile_result["version_created"])
        reactivated = 0
        active_source_ids: set[str] = set()
        existing = {
            str(source["external_id"]): source
            for source in self._existing_subscriptions()
            if str(source.get("account_id") or "") == channel_id
        }
        for subscription in subscriptions:
            subscribed_channel_id = str(subscription["channel_id"])
            external_id = f"youtube:subscription:{channel_id}:{subscribed_channel_id}"
            prior = existing.get(external_id)
            result = self.core.store.upsert_source(
                SourceItemInput(
                    kind="youtube_subscription",
                    external_id=external_id,
                    account_id=channel_id,
                    title=str(subscription.get("title") or subscribed_channel_id),
                    uri=str(subscription.get("channel_url") or ""),
                    content=_canonical_json(subscription),
                    sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                    external_policy=ExternalPolicy.DENY_RAW,
                    trust="official_oauth",
                    status="active",
                    metadata={
                        "connector": "youtube_oauth",
                        "subscribed_channel_id": subscribed_channel_id,
                        "evidence_role": "subscription",
                    },
                )
            )
            active_source_ids.add(str(result["source_id"]))
            created += int(result["created"])
            versions += int(result["version_created"])
            if prior and str(prior.get("status") or "") != "active":
                reactivated += 1

        deactivated = 0
        for source in existing.values():
            source_id = str(source["id"])
            if source_id in active_source_ids or str(source.get("status") or "") != "active":
                continue
            if self.core.store.set_source_status(source_id, "inactive"):
                deactivated += 1

        completed_at = datetime.now(UTC).isoformat()
        return IngestionResult(
            stats={
                "account_sources": 1,
                "subscriptions": len(subscriptions),
                "sources_created": created,
                "versions_created": versions,
                "subscriptions_deactivated": deactivated,
                "subscriptions_reactivated": reactivated,
            },
            cursor=completed_at,
            cursor_state={
                "channel_id": channel_id,
                "subscription_count": len(subscriptions),
                "snapshot_completed_at": completed_at,
            },
        )

    def _existing_subscriptions(self) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for offset in range(0, 10_000, 500):
            page = self.core.store.list_sources(kind="youtube_subscription", limit=500, offset=offset)
            sources.extend(page)
            if len(page) < 500:
                return sources
        raise YouTubeAPIError("YouTube subscription reconciliation exceeded its safety limit")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
