"""Published Google REST operations through the shared account and App Actions."""
from __future__ import annotations

import base64
from email import policy
from email.parser import BytesParser
import json
import re
import secrets

import httpx

from agent.contracts.google_workspace import GoogleApiOperation
from agent.plugins import google_api_catalog as catalog
from agent.plugins.google_workspace import GoogleError, SERVICES, google_service
from agent.plugins.credential_binding import credential_digest


def _label(value):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value.replace("_", " ")).capitalize()


def _fields(value, prefix=""):
    if isinstance(value, dict):
        return [field for key, item in value.items() for field in _fields(item, (prefix + " · " if prefix else "") + _label(key))]
    if isinstance(value, list):
        return [field for index, item in enumerate(value) for field in _fields(item, prefix + f" {index + 1}")]
    return [{"label": prefix, "value": str(value) if value is not None else "Clear"}]


class GoogleApiAdapter:
    def __init__(self, service=None):
        self.service = service or google_service()

    def _authorized(self, operation, request):
        current = self.service
        if not current.registry.is_enabled("google-workspace") or not current.registry.is_enabled(SERVICES[operation.service]["plugin_id"]):
            raise GoogleError("Enable this service in the Google connection before using it.")
        tokens = current._tokens()
        scopes = set(str(tokens.get("scope") or "").split())
        required = catalog.method(operation.service, operation.method_id).get("scopes", [])
        if required and not scopes.intersection(required):
            raise GoogleError("This operation needs additional Google permission. Open Google plugins → Enable changes and approve access. Some methods also require a Workspace administrator or domain-wide authorization.")
        metadata = current.store.load_metadata()
        user = request["parameters"].get("userId", "me")
        if operation.service == "gmail" and user not in {"me", metadata.get("google_email")}:
            raise GoogleError("Gmail operations must use the currently connected account (userId=me).")
        return tokens, metadata

    def _binding(self, operation, request, tokens, metadata):
        client_id, _ = self.service.credentials()
        return {"account_id": metadata.get("google_account_id", ""), "client_id": client_id,
            "credential_digest": credential_digest(tokens.get("refresh_token") or tokens.get("access_token"),provider="google"),
            "scope_digest": catalog.digest(sorted(str(tokens.get("scope") or "").split())),
            "request_digest": catalog.digest(operation.model_dump()), "schema_digest": request["schema_digest"],
            "service": operation.service, "method_id": operation.method_id}

    def read(self, operation):
        request = catalog.plan(operation)
        if request["method"] != "GET":
            raise GoogleError("This Google operation changes data. Use its confirmed App Action; it cannot execute through the read path.")
        with self.service.lock:
            tokens, _ = self._authorized(operation, request)
            result = self._send(operation, request, tokens)
            from agent.tools.app_actions import note_google_read
            note_google_read(operation.service)
            return result

    def prepare(self, operation):
        request = catalog.plan(operation)
        if request["method"] == "GET":
            raise GoogleError("Read this Google operation directly; it does not need write confirmation.")
        with self.service.lock:
            tokens, metadata = self._authorized(operation, request)
            if not metadata.get("google_account_id"):
                raise GoogleError("Reconnect this Google account before enabling changes.")
            binding = self._binding(operation, request, tokens, metadata)
            preview = self.preview(operation, request, metadata)
            return {**binding, "preview": preview,
                "message": preview["heading"] + " as " + preview["account"] + ". Review the exact target and changes before confirming."}

    def execute(self, operation, *, binding=None, confirmed=False):
        if not confirmed or not binding:
            raise GoogleError("Review and confirm this exact Google operation first.")
        with self.service.lock:
            request = catalog.plan(operation)
            tokens, metadata = self._authorized(operation, request)
            expected = self._binding(operation, request, tokens, metadata)
            if request["method"] == "GET" or any(expected[key] != binding.get(key) for key in expected):
                raise GoogleError("The Google account, permission or operation changed. Review this operation again.")
            result = self._send(operation, request, tokens)
            return {"changed": True, **result, "_message": binding["preview"]["heading"] + " completed."}

    def _send(self, operation, request, tokens):
        headers = {"Authorization": "Bearer " + tokens["access_token"]}
        kwargs = {"params": request["query"], "headers": headers}
        if request["media"] is not None:
            boundary = "vellum_" + secrets.token_hex(16)
            headers["Content-Type"] = "multipart/related; boundary=" + boundary
            kwargs["content"] = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                + json.dumps(request["body"] or {}).encode() + f"\r\n--{boundary}\r\nContent-Type: {operation.media_type}\r\n\r\n".encode()
                + request["media"] + f"\r\n--{boundary}--\r\n".encode())
        elif request["body"] is not None:
            kwargs["json"] = request["body"]
        try:
            if request["query"].get("alt") == "media":
                response = self.service.request(request["method"], request["url"], **kwargs, timeout=20, follow_redirects=False)
                if response.status_code >= 400:
                    raise GoogleError(f"Google media request failed (HTTP {response.status_code}).")
                if len(response.content) > 2 * 1024 * 1024:
                    raise GoogleError("This media read exceeds the 2 MiB tool limit.")
                data = {"data_base64": base64.b64encode(response.content).decode(), "mime_type": response.headers.get("content-type", "application/octet-stream"), "bytes": len(response.content)}
            else:
                data = self.service._json(request["method"], request["url"], **kwargs)
        except (httpx.HTTPError, GoogleError) as exc:
            message = str(exc) if isinstance(exc, GoogleError) else "Google is unreachable."
            if request["method"] != "GET":
                message += " This write may have reached Google. Check the target before retrying; Vellum did not replay it."
            raise GoogleError(message) from None
        return {"service": operation.service, "method_id": operation.method_id, "result": data,
                "untrusted_provider_data": True}

    def preview(self, operation, request, metadata):
        suffix = operation.method_id.rsplit(".", 1)[-1]
        heading = _label(suffix) + " in " + SERVICES[operation.service]["name"]
        fields = _fields(request["parameters"])
        body = dict(operation.body or {})
        raw = body.pop("raw", None)
        if isinstance(body.get("message"), dict) and body["message"].get("raw"):
            body["message"] = dict(body["message"])
            raw = body["message"].pop("raw")
        if raw:
            try:
                parsed = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
                fields += [{"label": key, "value": str(parsed[key])} for key in ("From", "To", "Cc", "Bcc", "Subject") if parsed[key]]
                content = parsed.get_body(preferencelist=("plain", "html"))
                if content:
                    fields.append({"label": "Message", "value": content.get_content()})
                fields += [{"label": "Attachment", "value": item.get_filename() or item.get_content_type()} for item in parsed.iter_attachments()]
            except (ValueError, TypeError, LookupError):
                raise GoogleError("The email could not be decoded for review. Supply a valid RFC 2822 message.") from None
        fields += _fields(body)
        if request["media"] is not None:
            fields.append({"label": "Upload", "value": f"{len(request['media'])} bytes · {operation.media_type}"})
        destructive = request["method"] == "DELETE" or suffix.casefold() in {"delete", "batchdelete", "clear", "emptytrash"}
        return {"heading": heading, "account": metadata.get("google_email") or "Connected Google account",
            "service": operation.service, "method_id": operation.method_id, "fields": fields,
            "warning": "This operation deletes data and may be permanent. Confirm only the exact intended target." if destructive else
                "This operation changes Google data. Sending, sharing and notifications follow the fields shown below.",
            "confirm_label": "Confirm deletion" if destructive else "Confirm " + _label(suffix).lower()}
