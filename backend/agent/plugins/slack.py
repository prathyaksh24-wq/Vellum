"""Slack user OAuth with PKCE, local credentials and a deferred official catalog."""
import asyncio
import base64
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import re
import secrets
from threading import RLock, Thread
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from jsonschema import Draft202012Validator

from agent.contracts.slack import SlackAppRegistration, SlackFlowStart, SlackFlowStatus, SlackMcpTool, SlackOAuthRequest, SlackStatus

SERVER = "https://mcp.slack.com/mcp"
AUTHORIZE = "https://slack.com/oauth/v2_user/authorize"
TOKEN = "https://slack.com/api/oauth.v2.user.access"
CALLBACK = "http://localhost:8000/api/plugins/slack/oauth/callback"
# The complete user-scope set published by Slack's MCP authorization metadata.
SCOPES = ("canvases:read canvases:write channels:history channels:read channels:write chat:write emoji:read "
    "files:read files:write groups:history groups:read groups:write im:history im:read im:write lists:read lists:write "
    "mpim:history mpim:read mpim:write reactions:read reactions:write search:read.files search:read.im "
    "search:read.mpim search:read.private search:read.public search:read.users users:read users:read.email")


class SlackError(ValueError):
    pass


logger = logging.getLogger(__name__)
KEYRING_SERVICE = "vellum.plugins.slack"
KEYRING_ACCOUNT = "connection-v1"
RECORD_FORMAT = "vellum-keyring-parts-v1"
PART_CHARS = 500  # Even worst-case JSON escaping fits Windows' 2,560-byte limit.
MAX_PARTS = 64


def catalog_failure(error):
    """Keep diagnostic categories, never provider bodies, URLs or credentials."""
    known = {
        "app_not_mcp_enabled": "Enable the Slack MCP Server feature in the app's Agents settings.",
        "mcp_not_enabled": "Enable the Slack MCP Server feature in the app's Agents settings.",
        "app_not_admin_approved": "A Slack workspace admin must approve this app for MCP access.",
        "not_allowed_token_type": "Slack rejected the token type for MCP. Reconnect using user authorization.",
        "invalid_auth": "Slack rejected this authorization for MCP. Reconnect in Vellum.",
        "missing_scope": "Slack reports missing MCP permissions. Review the app's configured user scopes.",
        "team_access_not_granted": "Slack did not grant MCP access to this workspace.",
        "plan_restricted": "Slack reports a workspace plan restriction for MCP access.",
    }
    pending, seen = [error], set()
    while pending and len(seen) < 24:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, httpx.HTTPStatusError):
            response = item.response
            code = None
            try:
                payload = response.json()
                value = payload.get("error") if isinstance(payload, dict) else None
                code = value if isinstance(value, str) and value in known else None
            except (ValueError, TypeError):
                pass
            status = response.status_code
            return code or f"mcp_http_{status}", known.get(code) or f"Slack's MCP endpoint returned HTTP {status}. Account sign-in succeeded, but MCP access was not verified."
        if isinstance(item, (TimeoutError, httpx.TimeoutException)):
            return "mcp_timeout", "Slack's MCP catalog did not respond in time. Retry the connection before changing app permissions."
        if isinstance(item, httpx.RequestError):
            return "mcp_network_error", "Vellum could not reach Slack's MCP endpoint. Check network access before changing the Slack app."
        from mcp.shared.exceptions import McpError
        from pydantic import ValidationError
        if isinstance(item, McpError):
            code = item.error.code
            return f"mcp_protocol_{code}", f"Slack's MCP server rejected the protocol request (code {code})."
        if isinstance(item, ValidationError):
            return "mcp_response_schema", "Vellum could not parse Slack's MCP response. This needs a connector correction, not another permissions change."
        if isinstance(item, (TypeError, AttributeError, ImportError)):
            return "mcp_client_error", "Vellum encountered a local MCP client compatibility error. This needs a connector correction."
        pending.extend(getattr(item, "exceptions", ()) or ())
        if item.__cause__ is not None:
            pending.append(item.__cause__)
        elif item.__context__ is not None:
            pending.append(item.__context__)
    return "mcp_transport_error", "Vellum could not complete the Slack MCP connection. The local diagnostic records the failure category; no workspace access was marked ready."


def invalidate_tools():
    from agent.graph.agent import agent
    agent.invalidate()


def tool_name(name):
    value = "slack_tool_" + name
    return value if len(value) <= 64 else value[:45] + "_" + hashlib.sha256(value.encode()).hexdigest()[:12]


class SlackService:
    def __init__(self, *, keyring=None, enabled=None, clock=time.time, request=None, transport=None, invalidator=invalidate_tools):
        if keyring is None:
            import keyring as keyring
        self.keyring, self.clock = keyring, clock
        self.enabled = enabled or self._enabled
        self.request, self.transport, self.invalidator = request or httpx.request, transport, invalidator
        self.lock, self.flows = RLock(), {}
        self.tools, self.tools_revision = [], ""

    @staticmethod
    def _enabled():
        from agent.plugins.registry import get_plugin_registry
        return get_plugin_registry().is_enabled("slack")

    def load(self):
        try:
            value = self.keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
            data = json.loads(value) if value else {}
            if not isinstance(data, dict):
                raise ValueError()
            if data.get("storage") == RECORD_FORMAT:
                generation, count = self._record_pointer(data)
                parts = []
                for index in range(count):
                    value = self.keyring.get_password(self._part_service(generation, index), KEYRING_ACCOUNT)
                    part = json.loads(value) if value else {}
                    if part.get("generation") != generation or not isinstance(part.get("value"), str):
                        raise ValueError()
                    parts.append(part["value"])
                data = json.loads("".join(parts))
                if not isinstance(data, dict):
                    raise ValueError()
            return data
        except Exception:
            raise SlackError("Unlock the system credential store and retry Slack.") from None

    def save(self, data):
        written, committed, pointer, root_update_attempted = [], False, None, False
        generation = secrets.token_urlsafe(24)
        try:
            # Parts have unique service names, so Windows keyring does not create
            # shadow copies of prior token blobs when its root entry is updated.
            encoded = json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
            values = [encoded[index:index + PART_CHARS] for index in range(0, len(encoded), PART_CHARS)]
            if not 1 <= len(values) <= MAX_PARTS:
                raise ValueError()
            old = self.keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
            for index, value in enumerate(values):
                service = self._part_service(generation, index)
                part = json.dumps({"generation": generation, "value": value}, separators=(",", ":"))
                # Escaping this envelope can expand backslashes from JSON values.
                # The byte guard is authoritative for every platform backend.
                if len(part.encode("utf-16-le")) > 2400:
                    raise ValueError()
                self.keyring.set_password(service, KEYRING_ACCOUNT, part)
                written.append(service)
                if self.keyring.get_password(service, KEYRING_ACCOUNT) != part:
                    raise ValueError()
            pointer = json.dumps({"storage": RECORD_FORMAT, "generation": generation, "parts": len(values)}, separators=(",", ":"))
            try:
                root_update_attempted = True
                self.keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, pointer)
            except Exception:
                # A backend can fail after committing. Do not remove parts that
                # are already referenced by the active record in that case.
                if self.keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) != pointer:
                    raise
            committed = True
            logger.info("Slack authorization stored: entries=%d utf16_bytes=%d", len(values), len(encoded.encode("utf-16-le")))
            try:
                previous = json.loads(old) if old else {}
                if previous.get("storage") == RECORD_FORMAT:
                    previous_generation, count = self._record_pointer(previous)
                    self._delete_parts([self._part_service(previous_generation, index) for index in range(count)])
            except (ValueError, TypeError):
                pass
        except Exception as exc:
            logger.warning("Slack credential save failed: error_type=%s winerror=%s", type(exc).__name__, getattr(exc, "winerror", None))
            if not committed:
                # Cleanup is best-effort; a locked OS store must never make us
                # delete or replace the preceding verified connection.
                safe_to_delete = not root_update_attempted
                if root_update_attempted:
                    try:
                        safe_to_delete = self.keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) != pointer
                    except Exception:
                        pass
                if safe_to_delete:
                    self._delete_parts(written)
            raise SlackError("Slack authorization could not be saved in the system credential store.") from None

    @staticmethod
    def _record_pointer(data):
        generation, count = data.get("generation"), data.get("parts")
        if not isinstance(generation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", generation) or type(count) is not int or not 1 <= count <= MAX_PARTS:
            raise ValueError("Invalid OS credential record")
        return generation, count

    @staticmethod
    def _part_service(generation, index):
        return f"{KEYRING_SERVICE}.part.{generation}.{index}"

    def _delete_parts(self, services):
        for service in services:
            try:
                self.keyring.delete_password(service, KEYRING_ACCOUNT)
            except Exception:
                logger.warning("Slack credential cleanup deferred: OS entry could not be removed")

    def configure(self, registration: SlackAppRegistration):
        with self.lock:
            data = self.load()
            app = registration.model_dump()
            if data.get("access_token") and app != data.get("app"):
                raise SlackError("Disconnect Slack before changing its app registration.")
            if app != data.get("app"):
                self._cancel_flows()
                self.save({**data, "app": app})
        return self.status()

    def status(self):
        enabled = self.enabled()
        try:
            data = self.load()
        except SlackError as exc:
            return SlackStatus(enabled=enabled, status="keyring_unavailable", message=str(exc))
        app = data.get("app") or {}
        configured = bool(data.get("access_token"))
        fresh = 0 <= self.clock() - data.get("checked_epoch", 0) < 86400
        connected = enabled and configured and data.get("status") == "ready" and fresh
        return SlackStatus(enabled=enabled, configured=configured, connected=connected, oauth_available=bool(app),
            app_id=app.get("app_id"), client_id=app.get("client_id"), account_name=data.get("account_name"),
            workspace_name=data.get("workspace_name"), verified_at=data.get("verified_at"),
            mcp_tool_count=data.get("mcp_tool_count", 0), granted_scopes=data.get("granted_scopes", []),
            status="disabled" if not enabled else "ready" if connected else "not_checked" if configured else "not_connected",
            message="Slack account, workspace and official MCP access verified." if connected else
                "Enable Slack to use its connection." if not enabled else
                "Verify the saved Slack connection before using it." if configured else
                "Sign in with Slack to connect its official MCP server." if app else
                "Create a Slack app from the supplied manifest, then save its public App ID and Client ID.")

    def _json(self, url, **kwargs):
        try:
            response = self.request("POST", url, timeout=30, follow_redirects=False, **kwargs)
            if response.status_code >= 300:
                raise SlackError("Slack rejected the request. Check workspace approval and retry later.")
            data = response.json()
            if not isinstance(data, dict) or data.get("ok") is not True:
                error = data.get("error") if isinstance(data, dict) else None
                hint = {"missing_scope": "Approve the required Slack user scopes and reconnect.",
                    "invalid_client_id": "Check the Slack app's Client ID.",
                    "bad_redirect_uri": "Register the exact localhost callback URL from Vellum.",
                    "invalid_code": "This sign-in code expired or was already used. Start again.",
                    "token_revoked": "Slack authorization was revoked. Reconnect.",
                    "token_expired": "Slack authorization expired. Reconnect.",
                    "app_not_admin_approved": "Ask a workspace admin to approve this Slack app."}.get(error)
                raise SlackError(hint or "Slack did not authorize the request. Check the app's MCP/PKCE settings and workspace approval.")
            return data
        except SlackError:
            raise
        except Exception:
            raise SlackError("Slack is unavailable. Retry later; no operation was automatically replayed.") from None

    def require(self):
        if not self.enabled():
            raise SlackError("Enable Slack in Plugins first.")
        data = self.load()
        if not data.get("access_token"):
            raise SlackError("Sign in with Slack in Plugins first.")
        if data.get("expires_at") and self.clock() >= data["expires_at"] - 60:
            with self.lock:
                data = self.load()
                if data.get("expires_at") and self.clock() >= data["expires_at"] - 60:
                    if not data.get("refresh_token"):
                        raise SlackError("Slack authorization expired. Reconnect in Plugins.")
                    refreshed = self._json(TOKEN, data={"grant_type": "refresh_token", "client_id": data["app"]["client_id"], "refresh_token": data["refresh_token"]})
                    data = {**data, **self._tokens(refreshed)}
                    self.save(data)
        return data

    def _tokens(self, value):
        token = value.get("access_token")
        if not isinstance(token, str) or not token or value.get("token_type", "user") not in {"user", "bearer", "Bearer"}:
            raise SlackError("Slack did not return a user authorization token.")
        expires = value.get("expires_in")
        if expires is not None and (not isinstance(expires, (int, float)) or expires <= 0):
            raise SlackError("Slack returned an invalid token lifetime.")
        return {"access_token": token, "refresh_token": value.get("refresh_token"),
            "expires_at": self.clock() + expires if expires else None}

    def identity(self, data):
        value = self._json("https://slack.com/api/auth.test", headers={"Authorization": "Bearer " + data["access_token"]})
        if not value.get("user_id") or not value.get("team_id") or value.get("bot_id"):
            raise SlackError("Slack did not verify a user and workspace. Use user scopes, not a bot token.")
        return {"account_id": str(value["user_id"]), "account_name": str(value.get("user") or value["user_id"]),
            "workspace_id": str(value["team_id"]), "workspace_name": str(value.get("team") or value["team_id"])}

    def connector(self, data):
        from agent.mcp.plugin_runtime import PluginMcpConnector
        return PluginMcpConnector(plugin_id="slack", name="slack", root=Path(__file__).parent,
            transport="http", url=SERVER, headers={"Authorization": "Bearer " + data["access_token"]})

    def _catalog(self, data):
        from agent.mcp.plugin_runtime import SdkPluginMcpTransport
        from agent.tools.plugin_mcp import _run_async
        phase = "transport"
        try:
            values = _run_async(asyncio.wait_for((self.transport or SdkPluginMcpTransport()).list_tools(self.connector(data)), timeout=40))
            phase = "catalog_validation"
            if not values or len(values) > 1000:
                raise ValueError()
            tools = [SlackMcpTool.model_validate(value).model_dump() for value in values]
            for tool in tools:
                if not tool["name"].isascii() or not tool["name"].replace("_", "").isalnum() or len(tool["name"]) > 100:
                    raise ValueError()
                Draft202012Validator.check_schema(tool["input_schema"])
            return tools
        except Exception as exc:
            code, message = catalog_failure(exc) if phase == "transport" else (
                "mcp_catalog_validation", "Slack returned a tool catalog that Vellum could not validate. This needs a connector correction, not another permissions change.")
            logger.warning("Slack MCP catalog failed: phase=%s code=%s error_type=%s", phase, code, type(exc).__name__)
            raise SlackError(message + f" Diagnostic: {code}.") from None

    def catalog(self, refresh=False):
        data = self.require()
        if not refresh and self.tools_revision == data["revision"]:
            return list(self.tools)
        tools = self._catalog(data)
        with self.lock:
            if self.require()["revision"] != data["revision"]:
                raise SlackError("The Slack connection changed. Refresh its tools.")
            self.tools, self.tools_revision = tools, data["revision"]
            self.save({**self.require(), "mcp_tool_count": len(tools)})
        self.invalidator()
        return list(tools)

    def cached_tools(self):
        data = self.load()
        return list(self.tools) if self.enabled() and data.get("revision") == self.tools_revision else []

    def start(self, request: SlackOAuthRequest):
        if not self.enabled():
            raise SlackError("Enable Slack before connecting.")
        with self.lock:
            data = self.load()
            if not data.get("app"):
                raise SlackError("Save the Slack app's public App ID and Client ID first.")
            self._cancel_flows()
            self.flows = {}
            identifier, state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            url = AUTHORIZE + "?" + urlencode({"client_id": data["app"]["client_id"], "redirect_uri": CALLBACK,
                "scope": SCOPES, "response_type": "code", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
            self.flows[identifier] = {"status": "pending", "message": "Approve Vellum in Slack to connect your workspace.",
                "created": self.clock(), "state": state, "verifier": verifier, "consumed": False, "app": data["app"],
                "original_revision": data.get("revision"), "return_url": request.return_url, "popup": request.popup, "authorization_url": url}
        return SlackFlowStart(flow_id=identifier, authorization_url=url, status="pending", message="Review Slack's requested permissions.")

    def flow_status(self, identifier):
        with self.lock:
            flow = self.flows.get(identifier)
            if not flow:
                raise SlackError("Slack sign-in expired. Start again.")
            if flow["status"] == "pending" and self.clock() - flow["created"] > 600:
                flow.update(status="failed", message="Slack sign-in expired. Start again.")
                flow.pop("verifier", None)
            return SlackFlowStatus(flow_id=identifier, status=flow["status"], message=flow["message"])

    def callback(self, state, code, error=""):
        if not state or not state.isascii() or len(state) > 200 or len(code) > 2048:
            raise SlackError("Slack sign-in expired. Start again.")
        with self.lock:
            identifier = next((key for key, value in self.flows.items() if secrets.compare_digest(value["state"], state)), None)
            if not identifier or self.flow_status(identifier).status != "pending" or self.flows[identifier]["consumed"]:
                raise SlackError("Slack sign-in expired or was already used.")
            flow = self.flows[identifier]
            flow["consumed"] = True
            if error or not code:
                flow.update(status="failed", message="Slack sign-in was declined. Your saved connection is unchanged.")
                flow.pop("verifier", None)
                return identifier
            flow["message"] = "Verifying your Slack account, workspace and official MCP access…"
        Thread(target=self._finish, args=(identifier, code), daemon=True).start()
        return identifier

    def _finish(self, identifier, code):
        phase = "exchanging authorization"
        try:
            with self.lock:
                flow = dict(self.flows[identifier])
            value = self._json(TOKEN, data={"grant_type": "authorization_code", "client_id": flow["app"]["client_id"],
                "code": code, "code_verifier": flow["verifier"], "redirect_uri": CALLBACK})
            data = {**self._tokens(value), "app": flow["app"], "revision": secrets.token_urlsafe(32)}
            phase = "verifying your account"
            data.update(self.identity(data))
            granted = value.get("scope") or (value.get("authed_user") or {}).get("scope") or ""
            data["granted_scopes"] = sorted(set(granted.replace(",", " ").split()))
            phase = "verifying official MCP access"
            tools = self._catalog(data)
            phase = "saving authorization"
            with self.lock:
                current, saved = self.flows.get(identifier), self.load()
                if (not current or self.flow_status(identifier).status != "pending" or not self.enabled()
                        or saved.get("revision") != flow["original_revision"] or saved.get("app") != flow["app"]):
                    raise SlackError("The Slack connection changed during sign-in.")
                self.save({**data, "status": "ready", "checked_epoch": self.clock(), "verified_at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(), "mcp_tool_count": len(tools)})
                self.tools, self.tools_revision = tools, data["revision"]
                current.update(status="connected", message="Connected to Slack. Continue in your original Vellum window.")
            self.invalidator()
        except Exception as exc:
            logger.warning("Slack OAuth stopped: phase=%s error_type=%s", phase, type(exc).__name__)
            with self.lock:
                current = self.flows.get(identifier)
                if current and current["status"] == "pending":
                    detail = str(exc) if isinstance(exc, SlackError) else "Vellum encountered a local connection error."
                    current.update(status="failed", message=f"Slack sign-in stopped while {phase}. {detail} Vellum has not marked this sign-in complete.")
        finally:
            with self.lock:
                if identifier in self.flows:
                    self.flows[identifier].pop("verifier", None)

    def return_url(self, identifier):
        with self.lock:
            self.flow_status(identifier)
            target = urlsplit(self.flows[identifier]["return_url"])
            query = [(key, value) for key, value in parse_qsl(target.query) if key not in {"view", "slack_oauth"}]
            return urlunsplit((target.scheme, target.netloc, target.path, urlencode(query + [("view", "apps"), ("slack_oauth", identifier)]), ""))

    def verify(self):
        data = self.require()
        actor = self.identity(data)
        if (actor["account_id"], actor["workspace_id"]) != (data["account_id"], data["workspace_id"]):
            raise SlackError("The Slack account or workspace changed. Reconnect.")
        self.catalog(refresh=True)
        with self.lock:
            current = self.require()
            if current["revision"] != data["revision"]:
                raise SlackError("The Slack connection changed. Verify again.")
            self.save({**current, **actor, "status": "ready", "checked_epoch": self.clock(), "verified_at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()})
        return self.status()

    def _cancel_flows(self):
        for flow in self.flows.values():
            if flow["status"] == "pending":
                flow.update(status="cancelled", message="Slack sign-in cancelled.")
                flow.pop("verifier", None)

    def cancel(self, identifier):
        with self.lock:
            self.flow_status(identifier)
            if self.flows[identifier]["status"] == "pending":
                self.flows[identifier].update(status="cancelled", message="Slack sign-in cancelled.")
                self.flows[identifier].pop("verifier", None)
        return {"changed": True}

    def disconnect(self):
        with self.lock:
            app = self.load().get("app")
            self._cancel_flows()
            self.save({"app": app} if app else {})
            self.tools, self.tools_revision = [], ""
        self.invalidator()
        return self.status()


@lru_cache(maxsize=1)
def slack_service():
    return SlackService()


def slack_plugin_status():
    service = slack_service()
    status = service.status()
    try:
        published = service.cached_tools()
    except SlackError:
        published = []
    return {"id": "slack", "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["slack_mcp_catalog", "slack_mcp_describe", "slack_mcp_read", "slack_mcp_execute", *[tool_name(tool["name"]) for tool in published]],
        "metadata": {"connection": status.model_dump(), "provider": "Slack", "website": "https://slack.com",
            "integration": "Official Slack MCP server", "documentation_url": "https://docs.slack.dev/ai/slack-mcp-server/",
            "credential_storage": "Operating system credential store", "coverage": "Complete live MCP catalog; your user scopes and workspace policies determine access. Not the entire Slack Web API."}}
