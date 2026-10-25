"""GitHub OAuth lifecycle shared by CLI-first and official MCP operations.

The application identity owner remains separate. This connector reuses its
registered callback address, but never changes the active Vellum account.
"""
import base64
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import secrets
import shutil
from threading import RLock, Thread
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from jsonschema import Draft202012Validator

from agent.config import get_settings
from agent.contracts.github_connection import GitHubConnectionRequest, GitHubConnectionStatus, GitHubFlowStart, GitHubFlowStatus, GitHubMcpTool

MCP_URL = "https://api.githubcopilot.com/mcp/x/all"
CALLBACK = "http://127.0.0.1:8000/api/accounts/callback/github"
SCOPES = "repo read:org gist workflow notifications read:user"


def native_tool_name(provider_name):
    name = "github_tool_" + provider_name
    return name if len(name) <= 64 else name[:45] + "_" + hashlib.sha256(provider_name.encode()).hexdigest()[:12]


class GitHubConnectionError(ValueError):
    pass


def invalidate_tools():
    from agent.graph.agent import agent
    agent.invalidate()


class GitHubConnectionService:
    def __init__(self, *, keyring=None, settings=get_settings, clock=time.time, enabled=None, request=None, transport=None, invalidator=invalidate_tools):
        if keyring is None:
            import keyring as keyring
        self.keyring, self.settings, self.clock = keyring, settings, clock
        self.enabled = enabled or self._enabled
        self.request = request or httpx.request
        self.transport = transport
        self.invalidator = invalidator
        self.lock = RLock()
        self.flows = {}
        self.tools = []
        self.tools_revision = ""

    @staticmethod
    def _enabled():
        from agent.plugins.registry import get_plugin_registry
        return get_plugin_registry().is_enabled("github")

    def load(self):
        try:
            raw = self.keyring.get_password("vellum.plugins.github", "connection-v1")
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except Exception:
            raise GitHubConnectionError("Unlock the system credential store and retry GitHub.") from None

    def save(self, data):
        try:
            self.keyring.set_password("vellum.plugins.github", "connection-v1", json.dumps(data))
        except Exception:
            raise GitHubConnectionError("GitHub authorization could not be saved in the system credential store.") from None

    def require(self):
        if not self.enabled():
            raise GitHubConnectionError("Enable GitHub in Plugins first.")
        data = self.load()
        if not data.get("access_token"):
            raise GitHubConnectionError("Sign in with GitHub in Plugins first.")
        return data

    def status(self):
        enabled = self.enabled()
        settings = self.settings()
        base = dict(enabled=enabled, oauth_available=bool(settings.account_github_client_id and settings.account_github_client_secret), cli_available=bool(shutil.which("gh")))
        try:
            data = self.load()
        except GitHubConnectionError as exc:
            return GitHubConnectionStatus(**base, status="keyring_unavailable", message=str(exc))
        configured = bool(data.get("access_token"))
        connected = configured and enabled and data.get("status") == "ready" and 0 <= self.clock() - data.get("checked_epoch", 0) < 86400
        return GitHubConnectionStatus(**base, configured=configured, connected=connected,
            status="disabled" if not enabled else "ready" if connected else "not_connected",
            message="GitHub account and official MCP access verified. Compatible operations prefer the CLI; other tools use MCP." if connected else
                "Enable GitHub to use its connection." if not enabled else "Sign in with GitHub to authorize the CLI and official MCP fallback.",
            account_name=data.get("account_name"), login=data.get("login"), verified_at=data.get("verified_at"),
            access=data.get("access", "read"), mcp_tool_count=data.get("mcp_tool_count", 0))

    def _json(self, method, url, **kwargs):
        try:
            response = self.request(method, url, timeout=25, follow_redirects=False, **kwargs)
            if response.status_code >= 300:
                raise GitHubConnectionError("GitHub rejected this request. Check the account grant and organization access.")
            data = response.json()
            if not isinstance(data, dict) or data.get("error"):
                raise GitHubConnectionError("GitHub did not return a usable authorization response.")
            return data
        except GitHubConnectionError:
            raise
        except Exception:
            raise GitHubConnectionError("GitHub is unavailable. Retry the connection; no authorization change was saved.") from None

    def connector(self, data):
        from agent.mcp.plugin_runtime import PluginMcpConnector
        headers = {"Authorization": "Bearer " + data["access_token"]}
        if data.get("access") == "read":
            headers["X-MCP-Readonly"] = "true"
        return PluginMcpConnector(plugin_id="github", name="github", root=Path(__file__).parent,
            transport="http", url=MCP_URL, headers=headers)

    def _catalog(self, data):
        from agent.mcp.plugin_runtime import SdkPluginMcpTransport
        from agent.tools.plugin_mcp import _run_async
        import asyncio
        transport = self.transport or SdkPluginMcpTransport()
        try:
            values = _run_async(asyncio.wait_for(transport.list_tools(self.connector(data)), timeout=40))
        except Exception:
            raise GitHubConnectionError("GitHub's official MCP catalog is unavailable. Check the grant and organization access, then retry.") from None
        if len(values) > 1000:
            raise GitHubConnectionError("GitHub returned an unexpectedly large tool catalog.")
        tools = [GitHubMcpTool.model_validate(value).model_dump() for value in values]
        for tool in tools:
            if not tool["name"].isascii() or not tool["name"].replace("_", "").isalnum() or len(tool["name"]) > 100:
                raise GitHubConnectionError("GitHub returned an invalid tool name.")
            Draft202012Validator.check_schema(tool["input_schema"])
        return tools

    def catalog(self, refresh=False):
        data = self.require()
        with self.lock:
            if not refresh and self.tools_revision == data.get("revision"):
                return list(self.tools)
        tools = self._catalog(data)
        with self.lock:
            if self.require().get("revision") != data.get("revision"):
                raise GitHubConnectionError("The GitHub connection changed. Refresh its tools.")
            self.tools, self.tools_revision = tools, data["revision"]
            self.save({**data, "mcp_tool_count": len(tools)})
        self.invalidator()
        return list(tools)

    def cached_tools(self):
        data = self.load()
        return list(self.tools) if self.enabled() and data.get("revision") == self.tools_revision else []

    def start(self, request: GitHubConnectionRequest):
        if not self.enabled():
            raise GitHubConnectionError("Enable GitHub before connecting.")
        settings = self.settings()
        if not settings.account_github_client_id or not settings.account_github_client_secret:
            raise GitHubConnectionError("Configure Vellum's registered GitHub OAuth app before connecting.")
        with self.lock:
            for previous in self.flows.values():
                if previous["status"] == "pending":
                    previous["status"] = "cancelled"
            self.flows = {}
            flow_id, state, verifier = secrets.token_urlsafe(32), "github-plugin." + secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            url = "https://github.com/login/oauth/authorize?" + urlencode(dict(client_id=settings.account_github_client_id,
                redirect_uri=CALLBACK, scope=SCOPES, state=state, code_challenge=challenge, code_challenge_method="S256"))
            self.flows[flow_id] = dict(state=state, verifier=verifier, status="pending", message="Continue to GitHub and review Vellum's permissions.",
                created=self.clock(), return_url=request.return_url, access=request.access, client_id=settings.account_github_client_id,
                original_revision=self.load().get("revision"), consumed=False, popup=request.popup, authorization_url=url)
        return GitHubFlowStart(flow_id=flow_id, status="pending", message="Continue to GitHub and review Vellum's permissions.", authorization_url=url)

    def flow_status(self, flow_id):
        with self.lock:
            flow = self.flows.get(flow_id)
            if not flow:
                raise GitHubConnectionError("GitHub sign-in expired. Start again.")
            if flow["status"] == "pending" and self.clock() - flow["created"] > 600:
                flow.update(status="failed", message="GitHub sign-in expired. Start again.")
            return GitHubFlowStatus(flow_id=flow_id, status=flow["status"], message=flow["message"])

    def cancel(self, flow_id):
        with self.lock:
            self.flow_status(flow_id)
            flow = self.flows[flow_id]
            if flow["status"] == "pending":
                flow.update(status="cancelled", message="GitHub sign-in cancelled.")
        return {"changed": True}

    def callback(self, state, code, error=""):
        if not state.isascii() or len(state) > 128:
            raise GitHubConnectionError("This GitHub callback is invalid or expired.")
        with self.lock:
            match = next(((identifier, flow) for identifier, flow in self.flows.items() if secrets.compare_digest(flow["state"], state)), None)
            if not match:
                raise GitHubConnectionError("This GitHub callback is invalid or expired.")
            flow_id, flow = match
            if self.flow_status(flow_id).status != "pending" or flow["consumed"]:
                raise GitHubConnectionError("This GitHub callback is invalid or already used.")
            flow["consumed"] = True
            if error or not code:
                flow.update(status="failed", message="GitHub authorization was declined. Your saved connection is unchanged.")
            else:
                Thread(target=self._finish, args=(flow_id, code), daemon=True, name="vellum-github-oauth").start()
        return flow_id

    def _finish(self, flow_id, code):
        phase = "exchanging authorization"
        try:
            with self.lock:
                flow = dict(self.flows[flow_id])
            settings = self.settings()
            if settings.account_github_client_id != flow["client_id"]:
                raise GitHubConnectionError("The GitHub OAuth app changed during sign-in.")
            tokens = self._json("POST", "https://github.com/login/oauth/access_token", headers={"Accept": "application/json"}, data=dict(
                client_id=flow["client_id"], client_secret=settings.account_github_client_secret, code=code, redirect_uri=CALLBACK, code_verifier=flow["verifier"]))
            token = tokens.get("access_token")
            if not token:
                raise GitHubConnectionError("GitHub did not return authorization.")
            phase = "verifying the account"
            profile = self._json("GET", "https://api.github.com/user", headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
            if not profile.get("id") or not profile.get("login"):
                raise GitHubConnectionError("GitHub did not verify an account.")
            data = dict(access_token=token, account_id=str(profile["id"]), login=profile["login"], account_name=profile.get("name") or profile["login"],
                access=flow["access"], scope=tokens.get("scope", ""), revision=secrets.token_urlsafe(32), status="ready", checked_epoch=self.clock(),
                verified_at=datetime.fromtimestamp(self.clock(), timezone.utc).isoformat())
            phase = "verifying official MCP access"
            tools = self._catalog(data)
            with self.lock:
                current = self.flows.get(flow_id)
                if not current or self.flow_status(flow_id).status != "pending" or self.load().get("revision") != flow["original_revision"] or not self.enabled():
                    raise GitHubConnectionError("The GitHub connection changed during sign-in.")
                self.save({**data, "mcp_tool_count": len(tools)})
                self.tools, self.tools_revision = tools, data["revision"]
                current.update(status="connected", message="Connected to GitHub. Return to Vellum.")
            self.invalidator()
        except Exception:
            with self.lock:
                current = self.flows.get(flow_id)
                if current and current["status"] == "pending":
                    current.update(status="failed", message=f"GitHub sign-in stopped while {phase}. Check your OAuth app and organization access, then retry; your saved connection is unchanged.")
        finally:
            with self.lock:
                current = self.flows.get(flow_id)
                if current:
                    current.pop("verifier", None)

    def return_url(self, flow_id):
        with self.lock:
            self.flow_status(flow_id)
            parsed = urlsplit(self.flows[flow_id]["return_url"])
            query = [(key, value) for key, value in parse_qsl(parsed.query) if key not in {"github_oauth", "view"}]
            query += [("view", "apps"), ("github_oauth", flow_id)]
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))

    def verify(self):
        data = self.require()
        profile = self._json("GET", "https://api.github.com/user", headers={"Authorization": "Bearer " + data["access_token"], "Accept": "application/vnd.github+json"})
        if str(profile.get("id")) != data["account_id"]:
            raise GitHubConnectionError("The GitHub account changed. Reconnect and review the intended account.")
        self.catalog(refresh=True)
        with self.lock:
            current = self.require()
            if current["revision"] != data["revision"]:
                raise GitHubConnectionError("The GitHub connection changed. Verify it again.")
            self.save({**current, "status": "ready", "checked_epoch": self.clock(), "verified_at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()})
        return self.status()

    def disconnect(self):
        with self.lock:
            for flow in self.flows.values():
                if flow["status"] == "pending":
                    flow.update(status="cancelled", message="GitHub sign-in cancelled.")
            self.save({})
            self.tools, self.tools_revision = [], ""
        self.invalidator()
        return self.status()


@lru_cache(maxsize=1)
def github_service():
    return GitHubConnectionService()


def github_plugin_status():
    service = github_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except GitHubConnectionError:
        tools = []
    return {"id": "github", "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["github_mcp_catalog", "github_mcp_describe", "github_mcp_read", "github_mcp_execute", *[native_tool_name(tool["name"]) for tool in tools]],
        "metadata": {"connection": status.model_dump(), "provider": "GitHub", "website": "https://github.com",
            "integration": "GitHub CLI first · Official GitHub MCP fallback", "documentation_url": "https://github.com/github/github-mcp-server",
            "credential_storage": "Operating system credential store", "coverage": "Live official MCP catalog; access depends on the signed-in account, OAuth grant, organization policy and enabled toolsets."}}
