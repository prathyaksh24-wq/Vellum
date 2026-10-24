"""Google's service chooser reuses Calendar's existing OS credential owner.

Enablement stays in PluginRegistry. Broader access is a separate OAuth consent;
published API writes use the existing operation-bound App Action owner.
"""
from __future__ import annotations

from functools import lru_cache
import json
import base64
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import secrets
from threading import RLock
import time
import webbrowser
from urllib.parse import quote, urlencode

import httpx

from agent.contracts.google_workspace import GoogleFlow, GoogleSelection, GoogleServiceStatus, GoogleStatus
from agent.plugins.google_calendar_runtime import _credentials, google_calendar_pkce_pair, google_calendar_scopes, google_calendar_store
from agent.plugins.registry import get_plugin_registry

SCOPE = "https://www.googleapis.com/auth/"
SERVICES = {
    "drive": {"plugin_id": "google-drive", "name": "Google Drive", "scopes": [SCOPE + "drive.readonly"], "description": "Read and manage Drive files, folders, content and sharing with reviewed changes."},
    "gmail": {"plugin_id": "gmail", "name": "Gmail", "scopes": [SCOPE + "gmail.readonly"], "description": "Read messages and manage drafts, mail, labels and settings with reviewed changes."},
    "calendar": {"plugin_id": "google-calendar", "name": "Google Calendar", "scopes": list(google_calendar_scopes()), "description": "Read and manage calendars, events and sharing with reviewed changes."},
    "contacts": {"plugin_id": "google-contacts", "name": "Google Contacts", "scopes": [SCOPE + "contacts.readonly"], "description": "Read and manage personal contacts and groups with reviewed changes."},
}
WRITE_SCOPES = {
    "gmail": ["https://mail.google.com/", SCOPE + "gmail.settings.basic", SCOPE + "gmail.settings.sharing"],
    "drive": [SCOPE + "drive"],
    "calendar": [SCOPE + "calendar"],
    "contacts": [SCOPE + "contacts"],
}


def has_read_access(service, scopes):
    return set(SERVICES[service]["scopes"]).issubset(scopes) or WRITE_SCOPES[service][0] in scopes


def has_write_access(service, scopes):
    return WRITE_SCOPES[service][0] in scopes
REDIRECT = "http://127.0.0.1:8000"
STATE_PREFIX = "google."


class GoogleError(ValueError):
    pass


def readable_mail(message):
    """Project MIME data into bounded text; attachments and encoded payloads stay out."""
    payload = message.get('payload') or {}
    plain, html = [], []
    def visit(part):
        if part.get('filename'):
            return
        encoded = (part.get('body') or {}).get('data')
        if encoded and part.get('mimeType') in {'text/plain','text/html'}:
            try:
                text = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('utf-8',errors='replace')
                (plain if part['mimeType']=='text/plain' else html).append(text)
            except (ValueError, TypeError):
                pass
        for child in part.get('parts',[]):visit(child)
    visit(payload)
    text = '\n'.join(plain)
    if not text and html:
        class Text(HTMLParser):
            def __init__(self):super().__init__();self.parts=[];self.hidden=0
            def handle_starttag(self,tag,attrs):
                if tag in {'script','style'}:self.hidden+=1
            def handle_endtag(self,tag):
                if tag in {'script','style'}:self.hidden=max(0,self.hidden-1)
            def handle_data(self,data):
                if not self.hidden:self.parts.append(data)
        parser=Text();parser.feed('\n'.join(html));text=' '.join(parser.parts)
    text = text.strip() or str(message.get('snippet') or '')
    return {'id':message.get('id'),'threadId':message.get('threadId'),
        'headers':{item['name']:str(item.get('value',''))[:500] for item in payload.get('headers',[]) if item.get('name','').casefold() in {'from','to','subject','date'}},
        'text':text[:1500], 'truncated':len(text)>1500,'untrusted_provider_data':True}


class GoogleWorkspaceService:
    def __init__(self, *, store=None, registry=None, credentials=None, request=None, clock=time.time, opener=None):
        self.store = store or google_calendar_store()
        self.registry = registry or get_plugin_registry()
        self.credentials = credentials or _credentials
        self.request = request or httpx.request
        self.clock = clock
        self.opener = opener or webbrowser.open
        self.lock = RLock()

    def _json(self, method, url, **kwargs):
        try:
            response = self.request(method, url, timeout=20, follow_redirects=False, **kwargs)
            if response.status_code >= 400:
                if len(response.content) <= 2 * 1024 * 1024:
                    try:
                        error = response.json().get("error", {})
                        reasons = {item.get("reason") for field in ("errors", "details") for item in error.get(field, []) if isinstance(item, dict)} if isinstance(error, dict) else set()
                    except (ValueError, AttributeError):
                        reasons = set()
                    if reasons & {"SERVICE_DISABLED", "accessNotConfigured"}:
                        name = next((label for prefix, label in (
                            ("https://www.googleapis.com/drive/", "Google Drive API"),
                            ("https://gmail.googleapis.com/", "Gmail API"),
                            ("https://people.googleapis.com/", "People API (Contacts)"),
                        ) if url.startswith(prefix)), "Google API")
                        raise GoogleError(f"{name} is disabled in Vellum's Google Cloud project. Enable the API in Google Cloud, then retry. Signing in again is not required.")
                raise GoogleError(f"Google denied or could not complete this request (HTTP {response.status_code}). Check the account, API and permissions.")
            if not response.content:
                return {}
            if len(response.content) > 2 * 1024 * 1024:
                raise GoogleError("Google returned too much data. Request a smaller page.")
            result = response.json()
            if not isinstance(result, dict):
                raise GoogleError("Google returned an unexpected response.")
            return result
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise GoogleError("Google is unreachable or returned an unreadable response. Check the connection and try again.") from exc

    def status(self):
        client_id, _ = self.credentials()
        storage_message = ""
        try:
            metadata = self.store.load_metadata()
            tokens = self.store.load_tokens(required=False)
        except RuntimeError:
            metadata, tokens = {}, {}
            storage_message = "Google credentials could not be read from this device's system credential store."
        valid_client = not metadata.get("google_client_id") or metadata["google_client_id"] == client_id
        connected = bool(tokens) and bool(client_id) and valid_client
        scopes = set(str(tokens.get("scope") or "").split()) if connected else set()
        rows = []
        with self.registry.read_snapshot():
            group_enabled = self.registry.is_enabled("google-workspace")
            for identifier, spec in SERVICES.items():
                enabled = self.registry.is_enabled(spec["plugin_id"])
                authorized = has_read_access(identifier, scopes)
                from agent.plugins.google_api_catalog import methods
                state = "disabled" if not (enabled and group_enabled) else "not_connected" if not connected else "connected" if authorized else "needs_permission"
                rows.append(GoogleServiceStatus(id=identifier, plugin_id=spec["plugin_id"], name=spec["name"], enabled=enabled,
                    authorized=authorized, status=state, description=spec["description"],
                    can_write=has_write_access(identifier, scopes), operation_count=len(methods(identifier))))
        return GoogleStatus(configured=bool(client_id), connected=connected,
            email=str(metadata.get("google_email") or metadata.get("calendar_id") or "") if connected else "",
            services=rows, message=storage_message or "Switch services on or off for Vellum. Switching off keeps the permission previously granted to Google.")

    def _select(self, services):
        self.registry.set_enabled_many({spec["plugin_id"]: identifier in services for identifier, spec in SERVICES.items()})

    def configure(self, selection: GoogleSelection):
        with self.lock:
            status = self.status()
            granted = {row.id for row in status.services if row.authorized}
            if selection.access == "manage":
                granted = {row.id for row in status.services if row.can_write}
            if not selection.force_signin and (not selection.services or (status.connected and set(selection.services).issubset(granted))):
                self._select(selection.services)
                return {"changed": True, "connection": self.status().model_dump(), "_message": "Google service selection saved."}
            client_id, _ = self.credentials()
            if not client_id:
                raise GoogleError("Vellum's Google OAuth client is not configured. Configure the Google connection before signing in.")
            # Installed apps must request the complete selected scope set again.
            scopes = ["openid", "email"]
            for identifier in selection.services:
                scopes += SERVICES[identifier]["scopes"]
                if selection.access == "manage":
                    scopes += WRITE_SCOPES[identifier]
            scopes = list(dict.fromkeys(scopes))
            verifier, challenge = google_calendar_pkce_pair()
            state, flow_id = STATE_PREFIX + secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            self.store.save_flow({"state": state, "flow_id": flow_id, "created_at": self.clock(), "code_verifier": verifier,
                "redirect_uri": REDIRECT, "client_id": client_id, "services": selection.services, "return_url": selection.return_url})
            url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({"client_id": client_id, "redirect_uri": REDIRECT,
                "response_type": "code", "scope": " ".join(scopes), "access_type": "offline", "prompt": "consent select_account",
                "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
            flow = GoogleFlow(flow_id=flow_id, status="pending", authorization_url=url, message="Sign in with Google and review the selected services.")
            if selection.open_browser:
                try:
                    flow.browser_opened = bool(self.opener(url))
                except Exception:
                    # The pending flow remains usable through the UI retry link.
                    pass
            return {"changed": True, "flow": flow.model_dump(), "_message": flow.message}

    def receive_callback(self, *, code, state, error=""):
        with self.lock:
            flow = self.store.consume_flow(state)
            result = {"flow_id": flow["flow_id"], "status": "failed", "message": "Google sign-in was not completed. Return to Vellum and try again."}
            try:
                client_id, secret = self.credentials()
                if error or not code or client_id != flow["client_id"]:
                    raise GoogleError("Google sign-in was not completed.")
                data = {"grant_type": "authorization_code", "client_id": client_id, "code": code,
                    "redirect_uri": flow["redirect_uri"], "code_verifier": flow["code_verifier"]}
                if secret:
                    data["client_secret"] = secret
                tokens = self._json("POST", "https://oauth2.googleapis.com/token", data=data)
                if not all(tokens.get(key) for key in ("access_token", "scope", "refresh_token")):
                    raise GoogleError("Google did not return a complete grant. Reconnect and approve offline access.")
                profile = self._json("GET", "https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": "Bearer " + tokens["access_token"]})
                if not profile.get("sub") or not profile.get("email") or profile.get("email_verified") is not True:
                    raise GoogleError("Google did not verify the connected account.")
                self.store.save_tokens(tokens)
                metadata = self.store.load_metadata()
                if metadata.get("google_account_id") != profile["sub"]:
                    for key in ("calendar_id", "calendar_label", "time_zone"):
                        metadata.pop(key, None)
                metadata.update(google_account_id=profile["sub"], google_email=profile["email"], google_client_id=client_id)
                self.store._atomic_write(self.store.metadata_path, metadata)
                scopes = set(str(tokens["scope"]).split())
                enabled = [identifier for identifier in flow["services"] if has_read_access(identifier, scopes)]
                self._select(enabled)
                missing = [SERVICES[key]["name"] for key in flow["services"] if key not in enabled]
                result.update(status="connected", message="Google connected." + (" Permission still needed for " + ", ".join(missing) + "." if missing else ""))
            except (GoogleError, ValueError, RuntimeError):
                pass
            metadata = self.store.load_metadata()
            metadata["google_flow"] = {**result, "completed_at": self.clock()}
            self.store._atomic_write(self.store.metadata_path, metadata)
            return flow["return_url"], result

    def flow_status(self, flow_id):
        result = self.store.load_metadata().get("google_flow") or {}
        if result.get("flow_id") == flow_id:
            return GoogleFlow(**{key: value for key, value in result.items() if key != "completed_at"})
        if self.store.flow_path.exists():
            pending = self.store._read_json(self.store.flow_path, "Google sign-in is unreadable.")
            if pending.get("flow_id") == flow_id:
                return GoogleFlow(flow_id=flow_id, status="pending" if self.clock() - pending["created_at"] < 600 else "expired")
        return GoogleFlow(flow_id=flow_id, status="expired", message="Start Google sign-in again.")

    def disconnect(self):
        with self.lock:
            self.store.clear()
            self._select([])
            return {"changed": True, "connection": self.status().model_dump(), "_message": "Google disconnected from Vellum on this device."}

    def _tokens(self):
        client_id, secret = self.credentials()
        metadata = self.store.load_metadata()
        if metadata.get("google_client_id") and metadata["google_client_id"] != client_id:
            raise GoogleError("Google's OAuth configuration changed. Reconnect the Google account.")
        tokens = self.store.load_tokens()
        if float(tokens.get("expires_at") or 0) <= self.clock() + 60:
            data = {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens.get("refresh_token", "")}
            if secret:
                data["client_secret"] = secret
            fresh = self._json("POST", "https://oauth2.googleapis.com/token", data=data)
            fresh.setdefault("scope", tokens.get("scope", ""))
            tokens = self.store.save_tokens(fresh)
        return tokens

    def read_mail(self, *, query='', limit=20, page_token=''):
        """A requested page of readable mail, with an explicit continuation cursor."""
        with self.lock:
            limit = min(50, max(1, int(limit)))
            listing = self.read('gmail',query=query,limit=limit,page_token=page_token)['result']
            tokens = self._tokens()
            def fetch(item):
                try:
                    message=self._json('GET','https://gmail.googleapis.com/gmail/v1/users/me/messages/'+quote(item['id'],safe=''),
                        params={'format':'full'},headers={'Authorization':'Bearer '+tokens['access_token']})
                    return readable_mail(message)
                except GoogleError as exc:
                    return {'id':item['id'],'error':str(exc)}
            with ThreadPoolExecutor(max_workers=3) as pool:
                messages=list(pool.map(fetch,listing.get('messages',[])))
            return {'service':'gmail','action':'search','result':{'messages':messages,'nextPageToken':listing.get('nextPageToken'),
                'partial':bool(listing.get('nextPageToken')) or any('error' in message for message in messages),
                'limit':limit,'query':query,
                'continuation':{'service':'gmail','action':'search','query':query,'page_token':listing['nextPageToken'],'limit':limit,'period':''} if listing.get('nextPageToken') else None,
                'note':'This is one page, not the total matching mail. For a time-range summary, call google_workspace_read with continuation until absent. Its query preserves the original time window; leave period empty on continuation. Report incomplete coverage if a page or message fails; truncated text is not the full message.'}}

    def read(self, service, *, action="search", query="", resource_id="", limit=20, page_token='', time_min='', time_max=''):
        """Small fixed read surface; all URLs and HTTP methods are application-owned."""
        if service not in SERVICES:
            raise GoogleError("Choose Gmail, Drive, Calendar or Contacts.")
        if not self.registry.is_enabled("google-workspace") or not self.registry.is_enabled(SERVICES[service]["plugin_id"]):
            raise GoogleError("Enable this service in the Google connection before using it.")
        with self.lock:
            tokens = self._tokens()
            if not has_read_access(service, set(str(tokens.get("scope") or "").split())):
                raise GoogleError("Reconnect Google and grant permission for this service.")
            limit = max(1, min(int(limit), 50))
            encoded = quote(resource_id, safe="")
            if service == "gmail" and action == "search":
                url, params = "https://gmail.googleapis.com/gmail/v1/users/me/messages", {"q": query, "maxResults": limit}
                if page_token:params['pageToken']=page_token
            elif service == "gmail" and action in {"message", "thread"} and resource_id:
                collection = "messages" if action == "message" else "threads"
                url, params = f"https://gmail.googleapis.com/gmail/v1/users/me/{collection}/{encoded}", {"format": "full"}
            elif service == "drive" and action == "search":
                url, params = "https://www.googleapis.com/drive/v3/files", {"q": query or "trashed=false", "pageSize": limit, "orderBy":"modifiedTime desc", "fields": "files(id,name,mimeType,modifiedTime,webViewLink,description),nextPageToken"}
                if page_token:params['pageToken']=page_token
            elif service == "drive" and action == "file" and resource_id:
                url, params = f"https://www.googleapis.com/drive/v3/files/{encoded}", {"fields": "id,name,mimeType,modifiedTime,webViewLink,description,size"}
            elif service == "calendar" and action == "search":
                from datetime import datetime, timezone
                url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
                params = {"maxResults":limit,"singleEvents":"true","orderBy":"startTime","timeMin":datetime.fromtimestamp(self.clock(),timezone.utc).isoformat()}
                bounds = {}
                for key,value in [('timeMin',time_min),('timeMax',time_max)]:
                    if value:
                        try:stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
                        except ValueError:raise GoogleError('Calendar time bounds must be ISO 8601 timestamps with timezone offsets.') from None
                        if stamp.tzinfo is None or stamp.utcoffset() is None:
                            raise GoogleError('Calendar time bounds require a timezone offset.')
                        bounds[key]=stamp
                        params[key]=stamp.isoformat()
                if time_max and datetime.fromisoformat(params['timeMin']) >= bounds['timeMax']:
                    raise GoogleError('Calendar time_max must be later than time_min.')
                if page_token:params['pageToken']=page_token
                if query:params["q"]=query
            elif service == "contacts" and action == "search":
                if query:
                    url, params = "https://people.googleapis.com/v1/people:searchContacts", {"query": query, "pageSize": limit, "readMask": "names,emailAddresses,phoneNumbers"}
                else:
                    url, params = "https://people.googleapis.com/v1/people/me/connections", {"pageSize": limit, "personFields": "names,emailAddresses,phoneNumbers"}
            else:
                raise GoogleError("This read action is unavailable. Use search, message/thread for Gmail, or file for Drive.")
            return {"service": service, "action": action, "result": self._json("GET", url, params=params, headers={"Authorization": "Bearer " + tokens["access_token"]})}


@lru_cache(maxsize=1)
def google_service():
    return GoogleWorkspaceService()


def google_connection_context():
    """Current capability evidence, without credentials or private account contents."""
    status = google_service().status()
    if not status.connected:
        return ""
    services = [row for row in status.services if row.enabled and row.authorized]
    if not services:
        return ""
    flags = "; ".join(f"{row.id}: read authorized" + (", changes authorized with review" if row.can_write else "") for row in services)
    return ("## Current Google connection\n" + flags + ".\n"
        "Use google_workspace_read for connected Google reads; no specialist is needed. "
        "Earlier assistant statements denying access are not current capability evidence. "
        "For today's mail use google_workspace_read(service=gmail, action=search, period=today); last 24 hours uses period=last_24_hours, not local midnight. For a time-range summary follow every nextPageToken using page_token and the same filters before calling the summary complete; a page size is not a total count. Disclose incomplete coverage and text truncation. "
        "To book or change an event, search for google_calendar_events_insert (create) or the exact edit/delete tool, then call it with calendarId and body including explicit date, timezone, start and end. Reading events does not schedule anything. Ask for a missing duration rather than inventing one. Never claim a change without its successful receipt; a prepared review still needs user confirmation. "
        "For missing-booking follow-ups, prior assistant claims are not creation receipts. Verify the exact event ID or title and local date/time from this conversation, using a bounded Calendar read (period=today or time_min/time_max). Do not replace that lookup with an unrelated upcoming agenda or list of subscribed F1 events. "
        "Permission flags are not proof of successful retrieval; report tool errors accurately.")


def google_plugin_statuses():
    status = google_service().status()
    result = [{"id": "google-workspace", "configured": status.configured, "status": "ready" if status.connected else "not_connected",
        "notes": status.message, "metadata": {"connection": status.model_dump(), "integration": "Google APIs with shared OAuth", "source_url": "https://developers.google.com/workspace"}}]
    for row in status.services:
        result.append({"id": row.plugin_id, "configured": row.authorized, "status": "ready" if row.status == "connected" else row.status,
            "notes": row.description if row.status == "connected" else "Choose this service in the shared Google connection.",
            "metadata": {"google_service": row.id, "connection_group": "google-workspace", "source_url": "https://developers.google.com/workspace"}})
    return result
