"""Linear transport and OS-owned credential lifecycle; no raw query interface."""
from datetime import datetime, timezone
from functools import lru_cache
import json
import secrets
from threading import RLock
import time


from agent.contracts.linear import PLUGIN_ID, LinearStatus
from agent.plugins.product_hunt import serialized
from agent.plugins.credentials import KeyringRecordStore



class LinearError(ValueError):
    def __init__(self, message, status="error"):
        super().__init__(message)
        self.status = status


def scrub(value, token=""):
    """Return task data, but never credential-bearing fields or the connection key."""
    if isinstance(value, dict):
        return {key: "[redacted credential]" if any(part in key.lower() for part in
                ("token", "secret", "password", "authorization", "cookie")) else scrub(item, token)
                for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, token) for item in value]
    if isinstance(value, str) and token:
        return value.replace(token, "[redacted credential]")
    return value


def connection_failure(error):
    """Preserve useful failure categories without exposing OAuth response text."""
    pending, seen = [error], set()
    while pending and len(seen) < 32:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, LinearError):
            return item
        if type(item).__name__ == 'OAuthFlowError' and str(item) in {
            'No redirect handler provided for authorization code grant',
            'No callback handler provided for authorization code grant'}:
            return LinearError('Linear authorization needs to be renewed. Choose Sign in with Linear and approve access again. Your saved connection has not been deleted.', 'authorization_required')
        pending.extend(getattr(item, 'exceptions', ()) or ())
        if item.__cause__ is not None:
            pending.append(item.__cause__)
        elif item.__context__ is not None:
            pending.append(item.__context__)
    return LinearError('Linear MCP could not complete this request. Verify the connection and check permissions. Check Linear before retrying a write.')


def same_authorization(before, after):
    if any(before.get(key) != after.get(key) for key in ('actor_id', 'workspace_id', 'grant_id')):
        return False
    return before.get('token') == after.get('token') or (
        after.get('oauth_refresh_generation', 0) > before.get('oauth_refresh_generation', 0))


class LinearService(KeyringRecordStore):
    def __init__(self, *, keyring=None, enabled=None, clock=time.time):
        if keyring is None:
            import keyring as system_keyring
            keyring = system_keyring
        self.keyring = keyring
        super().__init__(keyring, service='vellum.plugins.linear', error_type=LinearError, account='connection-v1')
        self.enabled = enabled or self._plugin_enabled
        self.clock = clock
        self._lock = RLock()
        self._mcp_catalog = None
        self._mcp_catalog_token = None

    @staticmethod
    def _plugin_enabled():
        from agent.plugins.registry import get_plugin_registry
        return get_plugin_registry().is_enabled(PLUGIN_ID)

    def _load(self):
        try:
            return self.load()
        except LinearError:
            raise LinearError("Unlock the system credential store and retry.", "keyring_unavailable") from None

    def _save(self, value):
        try:
            self.save(value)
        except LinearError:
            raise LinearError("Linear could not be saved in the system credential store.", "keyring_unavailable") from None

    def status(self):
        from agent.plugins.linear_mcp import published_tools
        base = dict(enabled=self.enabled())
        try:
            data = self._load()
        except LinearError as exc:
            return LinearStatus(**base, status=exc.status, message=str(exc))
        configured = bool(data.get("token")) and data.get("auth_type")=="oauth"
        state = data.get("status", "not_checked") if configured else "not_connected"
        if state == "ready" and not 0 <= self.clock() - data.get("checked_epoch", 0) < 86400:
            state = "not_checked"
        connected = configured and state == "ready" and base["enabled"]
        reconnect_required = configured and state in {'authorization_required', 'unauthorized', 'invalid_grant'}
        message = ("Verified Linear account and workspace. Your account permissions apply."
                   if connected else "Authorization is saved. Verify the connection before using it." if configured
                   else "Sign in with Linear to connect its official MCP server.")
        if not base["enabled"]:
            message = "Enable Linear to use its connection."
        elif reconnect_required:
            message = 'Sign in with Linear again to renew authorization. Your existing connection is retained until a replacement is verified.'
        return LinearStatus(**base, configured=configured, connected=connected,
            status=state if base["enabled"] else "disabled", message=message,
            verified_at=data.get("verified_at"), account_name=data.get("account_name"), workspace_name=data.get("workspace_name"),
            read_access="verified" if connected else "not_verified", write_access=data.get("write_access", "not_verified"),
            auth_type="oauth",mcp_tool_count=data.get("mcp_tool_count",len(published_tools())),mcp_status=data.get("mcp_status","not_checked"),reconnect_required=reconnect_required)

    def _require(self):
        if not self.enabled():
            raise LinearError("Linear is disabled. Enable it in Plugins first.", "disabled")
        data = self._load()
        if not data.get("token") or data.get("auth_type")!="oauth":
            raise LinearError("Connect Linear in Plugins first.", "not_connected")
        return data

    @serialized
    def update_connection(self, **fields):
        self._save({**self._require(), **fields})

    @serialized
    def cached_mcp_tools(self):
        if self._mcp_catalog is None:
            return None
        data=self._load()
        if self._mcp_catalog_token == data.get("token"):
            return self._mcp_catalog
        return None

    @serialized
    def cache_mcp_tools(self, tools):
        previous=self._mcp_catalog
        self._mcp_catalog=tools
        self._mcp_catalog_token=self._require()["token"]
        if previous!=tools:
            from agent.graph.agent import agent
            agent.invalidate()

    @serialized
    def connect_oauth(self, tokens, client_info, identity):
        if not self.enabled():
            raise LinearError("Enable Linear before connecting.")
        if not all(identity.get(key) for key in ("actor_id","workspace_id","account_name","workspace_name")):
            raise LinearError("Linear did not verify this account and workspace.")
        self._save({"token":"Bearer "+tokens["access_token"], **identity,
                    "grant_id": secrets.token_urlsafe(32), "oauth_refresh_generation": 0,
                    "status":"ready", "checked_epoch":self.clock(),
                    "verified_at":datetime.fromtimestamp(self.clock(),timezone.utc).isoformat(),
                    "auth_type":"oauth","oauth_tokens":tokens,"oauth_client_info":client_info,
                    "oauth_expires_at":self.clock()+tokens.get("expires_in",3600)})
        return self.status()

    def _identity(self, token):
        from agent.plugins.linear_oauth import stored_auth, identity_from_mcp, oauth_connector
        from agent.plugins.linear_mcp import _run
        data=self._require()
        if token != data["token"]:
            raise LinearError("The Linear connection changed. Verify it again.")
        return _run(identity_from_mcp(oauth_connector(stored_auth(self,connection=data))))

    def verify(self):
        # Network verification may refresh OAuth on another event-loop thread.
        # Never hold this lock while waiting for it, or overwrite refreshed tokens.
        with self._lock:
            data = self._require()
        try:
            identity = self._identity(data['token'])
        except LinearError as exc:
            with self._lock:
                current = self._require()
                if current.get('token') == data.get('token'):
                    self._save({**current, 'status': exc.status})
            raise
        with self._lock:
            current = self._require()
            if not same_authorization(data, current):
                raise LinearError('The Linear account changed. Verify its current connection again.')
            self._save({**current, **identity, 'status': 'ready', 'checked_epoch': self.clock(),
                'verified_at': datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()})
        return self.status()

    @serialized
    def disconnect(self):
        from agent.plugins.linear_oauth import cancel_oauth
        for flow_id in list(getattr(self,"_oauth_flows",{})):
            cancel_oauth(flow_id,self)
        self._save({})
        self._mcp_catalog=None
        self._mcp_catalog_token=None
        return self.status()






@lru_cache(maxsize=1)
def linear_service():
    return LinearService()


def linear_plugin_status():
    status = linear_service().status()
    from agent.plugins.linear_mcp import published_tools
    try:tools=linear_service().cached_mcp_tools() or published_tools()
    except LinearError:tools=published_tools()
    return {"id": PLUGIN_ID, "configured": status.configured, "status": status.status, "notes": status.message,
            "tools":["linear_"+tool["name"] for tool in tools],
            "metadata": {"connection": status.model_dump(), "provider": "Linear", "website": "https://linear.app",
                "integration": "Official Linear MCP server", "documentation_url": "https://linear.app/docs/mcp",
                "credential_storage": "Operating system credential store",
                "coverage": "Every tool published in the official MCP catalog is available. Account permissions and workspace plan apply; provider API operations absent from MCP are not exposed."}}
