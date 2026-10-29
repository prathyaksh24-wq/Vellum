"""Official MCP OAuth/PKCE, using LinearService's existing OS credential entry."""
import asyncio
import logging
import json
from pathlib import Path
import queue
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit, urlencode, urlunsplit

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata, OAuthClientInformationFull, OAuthToken

from agent.contracts.linear import LinearOAuthStart, LinearOAuthStatus, LinearOAuthRequest
from agent.mcp.plugin_runtime import PluginMcpConnector, SdkPluginMcpTransport
from agent.plugins.linear import LinearError, linear_service

SERVER = "https://mcp.linear.app/mcp"
CALLBACK = "http://127.0.0.1:8000/api/plugins/linear/oauth/callback"
logger = logging.getLogger(__name__)


def metadata():
    return OAuthClientMetadata(client_name="Vellum", redirect_uris=[CALLBACK],
        grant_types=["authorization_code","refresh_token"],response_types=["code"],
        token_endpoint_auth_method="none",scope="read write")


class OAuthStorage:
    def __init__(self, service=None,connection=None):
        self.service=service
        self.tokens=None
        self.client_info=None
        self.connection=(connection or service._require()) if service else None

    async def get_tokens(self):
        if self.service:
            data=self.connection
            value=dict(data.get("oauth_tokens") or {})
            if value and data.get("oauth_expires_at"):
                value["expires_in"]=max(0,int(data["oauth_expires_at"]-self.service.clock()))
        else:value=self.tokens
        return OAuthToken.model_validate(value) if value else None

    async def set_tokens(self, tokens):
        value=tokens.model_dump(mode="json",exclude_none=True)
        if self.service:
            with self.service._lock:
                current=self.service._require()
                if current.get("auth_type")!="oauth" or current.get("oauth_tokens")!=self.connection.get("oauth_tokens"):
                    raise LinearError("The Linear connection changed. Retry with the current connection.")
                if not value.get('refresh_token') and (current.get('oauth_tokens') or {}).get('refresh_token'):
                    value['refresh_token'] = current['oauth_tokens']['refresh_token']
                self.service.update_connection(oauth_tokens=value,token="Bearer "+value["access_token"],
                    oauth_expires_at=self.service.clock()+value.get("expires_in",3600),
                    oauth_refresh_generation=current.get('oauth_refresh_generation',0)+1)
                self.connection=self.service._require()
        else:self.tokens=value

    async def get_client_info(self):
        value=self.connection.get("oauth_client_info") if self.service else self.client_info
        return OAuthClientInformationFull.model_validate(value) if value else None

    async def set_client_info(self, client_info):
        value=client_info.model_dump(mode="json",exclude_none=True)
        if self.service:self.service.update_connection(oauth_client_info=value)
        else:self.client_info=value


class ExpiringOAuthClientProvider(OAuthClientProvider):
    async def _initialize(self):
        await super()._initialize()
        # The SDK loads stored tokens without restoring its in-memory deadline.
        # Restore it before the first request, so an expired grant refreshes rather
        # than taking the interactive authorization branch on a 401 response.
        if self.context.current_tokens:
            self.context.update_token_expiry(self.context.current_tokens)


def stored_auth(service,connection=None):
    # No interactive handlers here: expired/revoked grants require a user-driven
    # reconnect. Valid refresh tokens are handled by the official MCP SDK.
    return ExpiringOAuthClientProvider(SERVER,metadata(),OAuthStorage(service,connection))


def oauth_connector(auth):
    return PluginMcpConnector(plugin_id="linear",name="linear",root=Path(__file__).parent,
        transport="http",url=SERVER,auth=auth)


async def identity_from_mcp(connector):
    """MCP access tokens belong to the MCP resource, never the GraphQL API."""
    transport=SdkPluginMcpTransport()
    async def read(name,args,wrappers):
        raw=await transport.call_tool(connector,name,args)
        try:
            if len(raw)>2*1024*1024:raise ValueError()
            value=json.loads(raw)
            for key in wrappers:
                if isinstance(value,dict) and isinstance(value.get(key),dict):value=value[key]
            if not isinstance(value,dict) or not value.get("id") or not value.get("name"):raise ValueError()
            return value
        except (ValueError,TypeError):
            raise LinearError("Linear's MCP server did not verify this account and workspace.") from None
    user=await read("get_user",{"query":"me"},("data","user","viewer"))
    workspace=await read("get_workspace",{},("data","workspace","organization"))
    return {"actor_id":str(user["id"]),"account_name":str(user["name"]),
        "workspace_id":str(workspace["id"]),"workspace_name":str(workspace["name"])}


class Flow:
    def __init__(self, service, return_url=None, popup=False):
        self.id=secrets.token_urlsafe(32)
        self.service=service
        self.started=time.monotonic()
        self.ready=threading.Event()
        self.callback=queue.Queue(maxsize=1)
        self.state=""
        self.url=""
        self.status="pending"
        self.message="Approve Vellum in Linear to finish connecting."
        self.original_token=service._load().get("token")
        self.phase="authorization"
        self.popup=popup
        self.finished=threading.Event()
        target=urlsplit(LinearOAuthRequest(**({"return_url":return_url} if return_url else {})).return_url)
        query=parse_qs(target.query)
        query.update(view=["apps"],linear_oauth=[self.id])
        self.return_url=urlunsplit(target._replace(query=urlencode(query,doseq=True)))
        self.callback_received=False

    def public(self):
        return LinearOAuthStatus(flow_id=self.id,status=self.status,message=self.message)

    async def redirect(self,url):
        parsed=urlsplit(url)
        if parsed.scheme!="https" or parsed.hostname not in {"linear.app","mcp.linear.app"}:
            raise LinearError("Linear returned an unexpected authorization destination.")
        self.state=parse_qs(parsed.query).get("state",[""])[0]
        if not self.state:raise LinearError("Linear did not create a secure sign-in state.")
        self.url=url
        self.ready.set()

    async def receive(self):
        code,state=await asyncio.to_thread(self.callback.get,True,300)
        if not code:raise asyncio.CancelledError()
        self.phase="token_exchange"
        return code,state

    async def run(self):
        storage=OAuthStorage()
        provider=OAuthClientProvider(SERVER,metadata(),storage,redirect_handler=self.redirect,callback_handler=self.receive)
        connector=oauth_connector(provider)
        try:
            tools=await asyncio.wait_for(SdkPluginMcpTransport().list_tools(connector),timeout=300)
            self.phase="identity_verification"
            identity=await asyncio.wait_for(identity_from_mcp(connector),timeout=60)
            with self.service._lock:
                if self.status!="pending":return
                if self.service._load().get("token") != self.original_token:
                    raise LinearError("The connection changed during sign-in. Start again.")
                self.service.connect_oauth(storage.tokens,storage.client_info,identity)
                self.service.cache_mcp_tools(tools)
                self.service.update_connection(mcp_status="verified",mcp_tool_count=len(tools))
                self.status="connected"
                self.message="Connected to Linear. Return to Vellum."
        except asyncio.CancelledError:
            self.status="cancelled"
            self.message="Linear sign-in was cancelled."
        except Exception as exc:
            # Never log exception text, URLs, OAuth state, authorization codes or tokens.
            logger.warning("Linear OAuth failed: phase=%s error_type=%s provider_status=%s",
                self.phase,type(exc).__name__,exc.status if isinstance(exc,LinearError) else "unavailable")
            if self.status=="pending":
                self.status="failed"
                self.message="Linear sign-in did not complete. "+("Your existing authorization was preserved. " if self.original_token else "No connection was saved. ")+"Try connecting again."
        finally:
            self.ready.set()
            self.finished.set()


def _flows(service):
    if not hasattr(service,"_oauth_flows"):service._oauth_flows={}
    return service._oauth_flows


def start_oauth(service=None,return_url=None,popup=False):
    service=service or linear_service()
    if not service.enabled():raise LinearError("Enable Linear before connecting.")
    with service._lock:
        flows=_flows(service)
        for previous in flows.values():
            if previous.status=="pending":cancel_oauth(previous.id,service)
        flows.clear()
        flow=Flow(service,return_url,popup=popup)
        flows[flow.id]=flow
    threading.Thread(target=lambda:asyncio.run(flow.run()),daemon=True,name="vellum-linear-oauth").start()
    if not flow.ready.wait(timeout=15) or not flow.url:
        cancel_oauth(flow.id,service)
        raise LinearError("Linear sign-in could not start. Try again; the saved connection is unchanged.")
    return LinearOAuthStart(flow_id=flow.id,authorization_url=flow.url)


def oauth_status(flow_id,service=None):
    service=service or linear_service()
    with service._lock:
        flow=_flows(service).get(flow_id)
        if not flow:raise LinearError("Linear sign-in expired. Start again.")
        if flow.status=="pending" and time.monotonic()-flow.started>300:cancel_oauth(flow.id,service)
        return flow.public()


def cancel_oauth(flow_id,service=None):
    service=service or linear_service()
    with service._lock:
        flow=_flows(service).get(flow_id)
        if flow and flow.status=="pending":
            flow.status="cancelled"
            flow.message="Linear sign-in was cancelled."
            try:flow.callback.put_nowait(("",flow.state))
            except queue.Full:pass
    return {"cancelled":True}


def receive_callback(code,state,error="",service=None):
    service=service or linear_service()
    with service._lock:
        flow=next((flow for flow in _flows(service).values() if flow.state and secrets.compare_digest(flow.state,state)),None)
        if not flow or flow.status!="pending" or time.monotonic()-flow.started>300:
            raise LinearError("This sign-in callback is invalid or expired.")
        if flow.callback_received:
            raise LinearError("This callback was already received.")
        flow.callback_received=True
        if error or not code:
            cancel_oauth(flow.id,service)
            return flow
        try:flow.callback.put_nowait((code,state))
        except queue.Full:raise LinearError("This callback was already received.") from None
        return flow


def return_flow(flow_id,service=None):
    service=service or linear_service()
    oauth_status(flow_id,service)
    return _flows(service)[flow_id]
