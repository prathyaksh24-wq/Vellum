"""Process-local credential bindings for operation-bound provider reviews.

These bindings are not password verifiers or stored credentials. Secret-salted
PBKDF2 follows the credential fingerprinting pattern already used by LLM routing,
without exposing a stable unkeyed credential hash. The salt lasts for the same
process lifetime as pending App Action confirmations.
"""
import hashlib
import json
import secrets


_BINDING_SALT = secrets.token_bytes(32)


def credential_digest(value, *, provider: str) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256", payload, _BINDING_SALT + b"\0" + provider.encode("utf-8"), 600_000, dklen=32
    ).hex()
