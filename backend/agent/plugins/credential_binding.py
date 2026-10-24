"""Process-local credential bindings for operation-bound provider reviews.

These authenticators are not password verifiers or stored credentials. A secret
HMAC key prevents a review's binding from exposing an unkeyed credential hash.
The key lasts for the same process lifetime as pending App Action confirmations.
"""
import hmac
import json
import secrets


_BINDING_KEY = secrets.token_bytes(32)


def credential_digest(value, *, provider: str) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hmac.new(_BINDING_KEY, provider.encode("utf-8") + b"\0" + payload, "sha256").hexdigest()
