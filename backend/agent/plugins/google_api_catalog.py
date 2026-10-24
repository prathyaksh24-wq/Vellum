"""Offline published Google methods; caller input can never supply a URL or verb."""
from __future__ import annotations

import base64
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from jsonschema import Draft202012Validator

ROOTS = {"gmail": "https://gmail.googleapis.com/", "drive": "https://www.googleapis.com/drive/v3/",
         "calendar": "https://www.googleapis.com/calendar/v3/", "contacts": "https://people.googleapis.com/"}
COMMON_PARAMETERS = {"fields", "alt", "prettyPrint", "quotaUser", "$.xgafv"}
MAX_MEDIA = 8 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def tool_name(service, method_id):
    prefix={"gmail":"gmail","drive":"google_drive","calendar":"google_calendar","contacts":"google_contacts"}[service]
    suffix=re.sub(r'(?<=[a-z0-9])(?=[A-Z])','_',method_id.split('.',1)[1]).replace('.','_').lower()
    name=prefix+'_'+suffix
    if len(name)>64:
        verb=re.sub(r'(?<=[a-z0-9])(?=[A-Z])','_',method_id.rsplit('.',1)[-1]).lower()
        name=name[:32]+'_'+verb[:20]+'_'+digest(method_id)[:6]
    return name


@lru_cache(maxsize=4)
def document(service):
    directory = Path(__file__).with_name("google_discovery")
    if service == "gmail":
        path = directory / "gmail.json"
    elif service == "drive":
        path = directory / "drive.json"
    elif service == "calendar":
        path = directory / "calendar.json"
    elif service == "contacts":
        path = directory / "contacts.json"
    else:
        raise ValueError("Choose Gmail, Drive, Calendar or Contacts.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["baseUrl"] != ROOTS[service]:
        raise ValueError("The bundled Google API destination is invalid.")
    return result


@lru_cache(maxsize=4)
def methods(service):
    result = {}
    def walk(node):
        for method in node.get("methods", {}).values():
            result[method["id"]] = method
        for child in node.get("resources", {}).values():
            walk(child)
    walk(document(service))
    return result


def method(service, identifier):
    result = methods(service).get(identifier)
    if result is None:
        raise ValueError("Unknown Google operation. List or describe the service's published methods first.")
    return result


def _schema(raw):
    """Translate Discovery's schema dialect without discarding nested fields."""
    if "$ref" in raw:
        return {"$ref": "#/$defs/" + raw["$ref"]}
    result = {key: deepcopy(raw[key]) for key in ("type", "enum", "description", "pattern") if key in raw}
    if result.get("type") == "any":
        result.pop("type")
    for key in ("minimum", "maximum"):
        if key in raw:
            result[key] = float(raw[key])
    if "items" in raw:
        result["items"] = _schema(raw["items"])
    if "properties" in raw:
        result["properties"] = {key: _schema(value) for key, value in raw["properties"].items()}
        required = [key for key, value in raw["properties"].items() if value.get("required") is True]
        if required:
            result["required"] = required
    if "additionalProperties" in raw:
        value = raw["additionalProperties"]
        result["additionalProperties"] = _schema(value) if isinstance(value, dict) else value
    elif raw.get("type") == "object":
        result["additionalProperties"] = False
    if raw.get("repeated"):
        return {"type": "array", "items": result}
    return result


def parameters_for(service, published):
    common = {key: value for key, value in document(service).get("parameters", {}).items() if key in COMMON_PARAMETERS}
    return {**common, **published.get("parameters", {})}


def describe(service, identifier):
    published = method(service, identifier)
    parameters = parameters_for(service, published)
    body = _schema(published["request"]) if published.get("request") else None
    if body is not None:
        # Only include reachable schemas in each on-demand description.
        definitions, pending = {}, [body]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                ref = node.get("$ref", "").removeprefix("#/$defs/")
                if ref and ref not in definitions:
                    definitions[ref] = _schema(document(service)["schemas"][ref])
                    pending.append(definitions[ref])
                pending.extend(value for value in node.values() if isinstance(value, (dict, list)))
            elif isinstance(node, list):
                pending.extend(node)
        body["$defs"] = definitions
    return {"service": service, "method_id": identifier, "description": published.get("description", ""),
        "http_method": published["httpMethod"], "read_only": published["httpMethod"] == "GET",
        "scopes": published.get("scopes", []), "parameters": {"type": "object", "additionalProperties": False,
            "properties": {key: _schema(value) for key, value in parameters.items()},
            "required": [key for key, value in parameters.items() if value.get("required") and "default" not in value]},
        "body": body, "supports_media_upload": bool(published.get("supportsMediaUpload")),
        "supports_media_download": bool(published.get("supportsMediaDownload")),
        "source": document(service)["discovery_source"], "revision": document(service)["revision"]}


def catalog(service, query="", offset=0, limit=20):
    words = re.findall(r"[a-z0-9]+", query.casefold())
    rows = [{"method_id": identifier, "tool_name":tool_name(service,identifier), "description": value.get("description", ""),
             "read_only": value["httpMethod"] == "GET"} for identifier, value in sorted(methods(service).items())]
    if words:
        rows = [row for row in rows if any(word in (row["method_id"] + " " + row["description"]).casefold() for word in words)]
    return {"service": service, "total": len(rows), "operation_count": len(methods(service)),
            "methods": rows[offset:offset + limit], "next_offset": offset + limit if offset + limit < len(rows) else None,
            "source": document(service)["discovery_source"], "revision": document(service)["revision"]}


def plan(operation):
    published = method(operation.service, operation.method_id)
    details = describe(operation.service, operation.method_id)
    if operation.service == 'drive' and (operation.body or {}).get('mimeType') == 'application/vnd.google_apps.folder':
        raise ValueError('A Drive folder requires mimeType=application/vnd.google-apps.folder (hyphen, not underscore). Correct it before preparing the review.')
    parameters = dict(operation.parameters)
    definitions = parameters_for(operation.service, published)
    for key, value in definitions.items():
        if value.get("required") and key not in parameters and "default" in value:
            default = value["default"]
            parameters[key] = int(default) if value.get("type") == "integer" else default
    if not Draft202012Validator(details["parameters"]).is_valid(parameters):
        raise ValueError("Google parameters do not match the published schema. Describe this operation and supply its required fields.")
    if details["body"] is None and operation.body is not None:
        raise ValueError("This Google operation does not accept a request body.")
    if details["body"] is not None and operation.body is None and operation.media_base64 is None:
        raise ValueError('This Google operation needs body with the requested fields. For a Drive rename, pass body={"name":new_name}; a resource ID alone does not specify a change. Describe the operation for other fields.')
    if details["body"] is not None:
        error = next(Draft202012Validator(details["body"]).iter_errors(operation.body or {}), None)
        if error:
            location = ".".join(str(part) for part in error.absolute_path) or "body"
            allowed = list(error.schema.get("properties", {}))[:20]
            hint = " Allowed field names: " + ", ".join(allowed) + "." if allowed else ""
            raise ValueError(f"Google body fields do not match the published schema at {location} ({error.validator}).{hint} Describe {operation.method_id} before retrying.")
    path = published["path"]
    def expand(match):
        reserved, key = match.groups()
        value = str(parameters[key])
        if value.startswith("/") or any(part in {".", ".."} for part in value.split("/")):
            raise ValueError("Google resource identifiers must not contain traversal segments.")
        return quote(value, safe="/" if reserved else "")
    path = re.sub(r"\{(\+?)([A-Za-z0-9_]+)\}", expand, path)
    query = {key: value for key, value in parameters.items() if definitions[key].get("location", "query") == "query"}
    query = {key: str(value).lower() if isinstance(value, bool) else value for key, value in query.items()}
    media = None
    if operation.media_base64 is not None:
        if not published.get("supportsMediaUpload"):
            raise ValueError("This Google operation does not support a media upload.")
        try:
            media = base64.b64decode(operation.media_base64, validate=True)
        except ValueError:
            raise ValueError("Provide valid base64 media data.") from None
        if len(media) > MAX_MEDIA:
            raise ValueError("Google uploads in this tool are limited to 8 MiB.")
        path = published["mediaUpload"]["protocols"]["simple"]["path"]
        path = re.sub(r"\{(\+?)([A-Za-z0-9_]+)\}", expand, path)
        url = document(operation.service)["rootUrl"].rstrip("/") + path
        query["uploadType"] = "multipart"
    else:
        url = ROOTS[operation.service] + path
    expected = urlsplit(ROOTS[operation.service])
    target = urlsplit(url)
    if target.scheme != "https" or target.netloc != expected.netloc or target.fragment or target.query:
        raise ValueError("The Google API destination is invalid.")
    if query.get("alt", "json") not in {"json", "media"}:
        raise ValueError("Google response format must be json or media.")
    return {"method": published["httpMethod"], "url": url, "parameters": parameters,
            "query": query, "body": operation.body, "media": media, "schema_digest": digest(details)}
