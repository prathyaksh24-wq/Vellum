"""Product Hunt's official API, OS-owned credentials, and verified connection state.

Only fixed queries and confirmed follow mutations leave this module. App Actions receive an opaque staged
credential reference; token values never enter action requests or receipts.
"""
from datetime import datetime, timezone
from functools import lru_cache, wraps
import json
import secrets
from threading import RLock
import time

import httpx
from agent.plugins.credential_binding import credential_digest

from agent.contracts.product_hunt import (
    PLUGIN_ID, ProductHuntPost, ProductHuntRead, ProductHuntResult,
    ProductHuntStatus, ProductHuntTopic, ProductHuntUser, ProductHuntCollection, ProductHuntFollow,
)

ENDPOINT = "https://api.producthunt.com/v2/api/graphql"
DASHBOARD = "https://www.producthunt.com/v2/oauth/applications"
DOCS = "https://api.producthunt.com/v2/docs"
POST_FIELDS = "id name slug tagline url website votesCount commentsCount createdAt"
USER_FIELDS = "id username name url headline isFollowing isViewer followersCount followingCount"
PAGE_FIELDS = "pageInfo { hasNextPage endCursor }"
PROBE_QUERY = "query VellumConnectionCheck { posts(first: 1) { edges { node { id name } } } }"


class ProductHuntError(ValueError):
    def __init__(self, message, status="error"):
        super().__init__(message)
        self.status = status


def serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return run


class ProductHuntService:
    def __init__(self, *, keyring=None, client_factory=httpx.Client, enabled=None, clock=time.time):
        if keyring is None:
            import keyring as system_keyring
            keyring = system_keyring
        self.keyring = keyring
        self.client_factory = client_factory
        self.enabled = enabled or self._plugin_enabled
        self.clock = clock
        self._pending = {}
        self._lock = RLock()

    @staticmethod
    def _plugin_enabled():
        from agent.plugins.registry import get_plugin_registry
        return get_plugin_registry().is_enabled(PLUGIN_ID)

    def _load(self):
        try:
            raw = self.keyring.get_password("vellum.plugins.producthunt", "connection-v1")
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except Exception:
            raise ProductHuntError("Unlock the system credential store and retry.", "keyring_unavailable") from None

    def _save(self, data):
        try:
            self.keyring.set_password("vellum.plugins.producthunt", "connection-v1", json.dumps(data))
        except Exception:
            raise ProductHuntError("Product Hunt could not be saved in the system credential store.", "keyring_unavailable") from None

    def status(self):
        enabled = self.enabled()
        try:
            data = self._load()
        except ProductHuntError as exc:
            return ProductHuntStatus(enabled=enabled, status=exc.status, message=str(exc))
        configured = bool(data.get("token"))
        verified_at = data.get("verified_at")
        fresh = bool(data.get("checked_epoch") and 0 <= self.clock() - data["checked_epoch"] < 86400)
        state = data.get("status", "not_checked") if configured else "not_connected"
        if state == "ready" and not fresh:
            state = "not_checked"
        connected = configured and state == "ready"
        message = {
            "ready": "Verified access to the official Product Hunt API. Public reads only.",
            "not_checked": "A credential is saved. Verify the connection before using it.",
            "unauthorized": "Product Hunt rejected this credential. Reconnect with a valid developer token.",
            "rate_limited": "Product Hunt is rate limiting requests. Wait and verify again.",
            "unreachable": "Product Hunt could not be reached. Check the connection again.",
        }.get(state, "Connect Product Hunt to read launches, product details, and topics.")
        account_access = data.get("account_access", "not_checked")
        if connected and account_access == "available":
            message = "Verified Product Hunt connection. Account reads are available; writes require provider permission and confirmation."
        return ProductHuntStatus(enabled=enabled, configured=configured, connected=connected and enabled,
            status=state if enabled else "disabled", verified_at=verified_at, message=message,
            access="account_read" if account_access == "available" else "public_read",
            account_access=account_access, write_access=data.get("write_access", "not_verified"))

    def stage(self, token):
        token = token.strip()
        if not 8 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ProductHuntError("Enter a valid Product Hunt developer token.")
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if v[1] > self.clock()}
            if len(self._pending) >= 16:
                raise ProductHuntError("Too many pending connections. Wait a few minutes and retry.")
            reference = secrets.token_urlsafe(32)
            self._pending[reference] = (token, self.clock() + 600)
        return reference

    def discard(self, reference):
        with self._lock:
            self._pending.pop(reference, None)

    def _query(self, token, query, variables=None, *, access_context="public"):
        try:
            with self.client_factory(timeout=20, follow_redirects=False) as client:
                with client.stream("POST", ENDPOINT,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    json={"query": query, "variables": variables or {}}) as response:
                    if response.status_code == 403 and access_context != "public":
                        raise ProductHuntError("Product Hunt requires additional permission for this operation. Write access requires Product Hunt's application approval.", "approval_required" if access_context == "write" else "insufficient_scope")
                    if response.status_code in {401, 403}:
                        raise ProductHuntError("Product Hunt rejected the credential. Reconnect with a valid developer token.", "unauthorized")
                    if response.status_code == 429:
                        raise ProductHuntError("Product Hunt is rate limiting requests. Wait and retry.", "rate_limited")
                    if response.status_code != 200:
                        raise ProductHuntError("Product Hunt could not complete the request.", "unreachable")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 1024 * 1024:
                            raise ProductHuntError("Product Hunt returned too much data. Use a smaller request.")
                    payload = json.loads(body)
            if isinstance(payload, dict) and payload.get("errors") and access_context != "public":
                raise ProductHuntError("Product Hunt did not authorize or complete this account operation. Check the application's granted scopes and provider approval.", "approval_required" if access_context == "write" else "insufficient_scope")
            if not isinstance(payload, dict) or payload.get("errors") or not isinstance(payload.get("data"), dict):
                raise ProductHuntError("Product Hunt could not complete this API query. Check access and try again.")
            return payload["data"]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            if isinstance(exc, ProductHuntError):
                raise
            raise ProductHuntError("Product Hunt could not be reached or returned an invalid response.", "unreachable") from None

    def _verified(self, token):
        result = self._query(token, PROBE_QUERY)
        if not isinstance(result.get("posts"), dict) or not isinstance(result["posts"].get("edges"), list):
            raise ProductHuntError("Product Hunt did not return a valid connection check.")
        return {"token": token, "status": "ready", "checked_epoch": self.clock(),
            "verified_at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()}

    @serialized
    def connect(self, reference):
        self._require_enabled()
        with self._lock:
            pending = self._pending.pop(reference, None)
        if not pending or pending[1] <= self.clock():
            raise ProductHuntError("This connection request expired. Enter the token again.")
        # Do not replace an existing valid connection if verification fails.
        data = self._verified(pending[0])
        self._save(data)
        return self.status()

    @serialized
    def verify(self):
        self._require_enabled()
        data = self._load()
        if not data.get("token"):
            raise ProductHuntError("Connect Product Hunt first.", "not_connected")
        try:
            self._save({**data, **self._verified(data["token"])})
        except ProductHuntError as exc:
            data["status"] = exc.status
            self._save(data)
            raise
        return self.status()

    @serialized
    def disconnect(self):
        with self._lock:
            # An empty tombstone also invalidates pending connection attempts.
            self._save({})
            self._pending.clear()
        return self.status()

    def _require_enabled(self):
        if not self.enabled():
            raise ProductHuntError("Product Hunt is disabled. Enable it in Plugins first.", "disabled")

    @serialized
    def read(self, request: ProductHuntRead):
        self._require_enabled()
        data = self._load()
        token = data.get("token")
        if not token:
            raise ProductHuntError("Product Hunt is not connected. Open Plugins → Product Hunt to connect it.", "not_connected")
        account = request.operation in {"viewer", "account_posts", "account_collections"}
        if request.operation in {"viewer", "user"}:
            if request.operation == "viewer":
                query = f"query VellumAccount {{ viewer {{ user {{ {USER_FIELDS} }} }} }}"
                variables = {}
            else:
                query = f"query VellumUser($username: String!) {{ user(username: $username) {{ {USER_FIELDS} }} }}"
                variables = {"username": request.username}
        elif request.operation in {"account_posts", "account_collections"}:
            field = "followedCollections" if request.operation == "account_collections" else {"voted":"votedPosts", "made":"madePosts", "submitted":"submittedPosts"}[request.account_feed]
            fields = "id name url description" if request.operation == "account_collections" else POST_FIELDS
            query = f"query VellumAccountItems($first: Int!, $after: String) {{ viewer {{ user {{ {field}(first: $first, after: $after) {{ edges {{ node {{ {fields} }} }} {PAGE_FIELDS} }} }} }} }}"
            variables = {"first": request.limit, "after": request.after}
        elif request.operation == "post":
            query = f"query VellumPost($slug: String!) {{ post(slug: $slug) {{ {POST_FIELDS} description }} }}"
            variables = {"slug": request.slug}
        elif request.operation == "topics":
            query = f"query VellumTopics($first: Int!, $after: String) {{ topics(first: $first, after: $after) {{ edges {{ node {{ id name slug description }} }} {PAGE_FIELDS} }} }}"
            variables = {"first": request.limit, "after": request.after}
        else:
            query = f"query VellumLaunches($first: Int!, $after: String, $order: PostsOrder, $topic: String, $postedAfter: DateTime, $postedBefore: DateTime) {{ posts(first: $first, after: $after, order: $order, topic: $topic, postedAfter: $postedAfter, postedBefore: $postedBefore) {{ edges {{ node {{ {POST_FIELDS} }} }} {PAGE_FIELDS} }} }}"
            variables = {"first": request.limit, "after": request.after, "order": request.order, "topic": request.topic,
                "postedAfter": request.posted_after, "postedBefore": request.posted_before}
        try:
            result = self._query(token, query, variables, access_context="account" if account else "public")
            if request.operation in {"viewer", "user"}:
                value = (result.get("viewer") or {}).get("user") if account else result.get("user")
                if not isinstance(value, dict):
                    raise ProductHuntError("Product Hunt did not return this account or profile.", "insufficient_scope" if account else "not_found")
                answer = ProductHuntResult(operation=request.operation, user=ProductHuntUser.model_validate(value),
                    data_visibility="authenticated_account")
            elif request.operation == "post":
                if not isinstance(result.get("post"), dict):
                    raise ProductHuntError("No Product Hunt launch was found with that slug.", "not_found")
                answer = ProductHuntResult(operation="post", posts=[ProductHuntPost.model_validate(result["post"])])
            else:
                connection = result["viewer"]["user"][field] if account else result[request.operation]
                nodes = [edge["node"] for edge in connection["edges"]]
                page = connection["pageInfo"]
                answer = ProductHuntResult(operation=request.operation,
                    posts=[ProductHuntPost.model_validate(n) for n in nodes] if request.operation in {"posts", "account_posts"} else [],
                    topics=[ProductHuntTopic.model_validate(n) for n in nodes] if request.operation == "topics" else [],
                    collections=[ProductHuntCollection.model_validate(n) for n in nodes] if request.operation == "account_collections" else [],
                    account_feed=request.account_feed if request.operation == "account_posts" else None,
                    data_visibility="authenticated_account" if account else "public",
                    has_next_page=page["hasNextPage"], end_cursor=page.get("endCursor"))
        except ProductHuntError as exc:
            if exc.status == "insufficient_scope":
                self._save({**data, "account_access":"needs_permission"})
            elif exc.status != "not_found":
                data["status"] = exc.status
                self._save(data)
            raise
        except (ValueError, KeyError, TypeError):
            raise ProductHuntError("Product Hunt returned an invalid response.") from None
        self._save({**data, **({"account_access":"available"} if account else {}), "status": "ready", "checked_epoch": self.clock(),
            "verified_at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()})
        return answer

    @serialized
    def prepare_follow(self, username, *, following):
        self._require_enabled()
        target = self.read(ProductHuntRead(operation="user", username=username)).user
        actor = self.read(ProductHuntRead(operation="viewer")).user
        if target.id == actor.id:
            raise ProductHuntError("Choose another Product Hunt user; you cannot follow yourself.")
        token = self._load().get("token", "")
        return {"user_id":target.id, "username":target.username, "url":target.url, "actor_id":actor.id,
            "following":following, "token_digest":credential_digest(token,provider="producthunt"),
            "message":f"Confirm {'following' if following else 'unfollowing'} @{target.username} on Product Hunt. This changes your account's following list."}

    @serialized
    def set_following(self, request: ProductHuntFollow, *, following, binding, confirmed=False):
        self._require_enabled()
        if not confirmed or not binding:
            raise ProductHuntError("Review and confirm the exact Product Hunt user first.")
        data = self._load()
        token = data.get("token", "")
        if (not token or binding.get("username", "").casefold() != request.username.casefold()
                or binding.get("following") is not following
                or not secrets.compare_digest(binding.get("token_digest", ""), credential_digest(token,provider="producthunt"))):
            raise ProductHuntError("The Product Hunt connection or target changed. Review this action again.")
        actor = self.read(ProductHuntRead(operation="viewer")).user
        target = self.read(ProductHuntRead(operation="user",username=request.username)).user
        if actor.id != binding["actor_id"] or target.id != binding["user_id"]:
            raise ProductHuntError("The Product Hunt account or user changed. Review this action again.")
        if target.isFollowing == following:
            return {"changed":False, "user":target.model_dump(), "following":following,
                "_message":f"You already {'follow' if following else 'do not follow'} @{target.username}."}
        mutation = "userFollow" if following else "userFollowUndo"
        input_type = "UserFollowInput" if following else "UserFollowUndoInput"
        query = f"mutation VellumFollow($input: {input_type}!) {{ {mutation}(input: $input) {{ errors {{ message }} node {{ {USER_FIELDS} }} }} }}"
        try:
            result = self._query(token,query,{"input":{"userId":target.id}},access_context="write")
            payload = result.get(mutation) or {}
            if payload.get("errors"):
                raise ProductHuntError("Product Hunt rejected this change. Check your application's Write permission and provider approval.", "approval_required")
            user = ProductHuntUser.model_validate(payload.get("node"))
            if user.id != target.id or user.isFollowing != following:
                raise ProductHuntError("Product Hunt did not verify the requested follow state. Check the profile before retrying.")
        except ProductHuntError as exc:
            if exc.status == "approval_required":
                self._save({**self._load(), "write_access":"approval_required"})
            elif exc.status == "unauthorized":
                self._save({**self._load(), "status":"unauthorized"})
            raise
        except (ValueError, TypeError):
            raise ProductHuntError("Product Hunt returned an invalid follow result. Check the profile before retrying.") from None
        self._save({**self._load(), "write_access":"verified"})
        return {"changed":True, "user":user.model_dump(), "following":following,
            "_message":f"{'Followed' if following else 'Unfollowed'} @{user.username} on Product Hunt."}


@lru_cache(maxsize=1)
def product_hunt_service():
    return ProductHuntService()


def product_hunt_plugin_status():
    status = product_hunt_service().status()
    return {"id": PLUGIN_ID, "configured": status.configured, "status": status.status,
        "notes": status.message, "metadata": {"connection": status.model_dump(),
            "provider": "Product Hunt", "integration": "Official Product Hunt API v2 · Vellum connector",
            "documentation_url": DOCS, "website": "https://www.producthunt.com",
            "credential_storage": "Operating system credential store", "access": "Public and account reads; confirmed follow actions subject to provider approval"}}
