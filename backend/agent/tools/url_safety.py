"""URL safety checks — blocks requests to private/internal network addresses.

Stdlib port of Hermes' ``tools/url_safety.py`` for Vellum's web extract
pipeline. Prevents SSRF (Server-Side Request Forgery) where a malicious
prompt, skill, or web page could trick the agent into fetching internal
resources like cloud metadata endpoints (169.254.169.254), localhost
services, or private network hosts.

Fails closed: DNS errors and unexpected exceptions block the request.
Cloud metadata endpoints are always blocked — they are never legitimate
agent targets.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Optional
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

logger = logging.getLogger(__name__)


# Hostnames that should always be blocked regardless of IP resolution.
_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata.goog",
})

# IPs and networks that should always be blocked — cloud metadata /
# credential endpoints (the #1 SSRF target) and the link-local range
# where they all live. IPv4-mapped IPv6 variants included because DNS
# resolvers may return ::ffff:x.x.x.x for IPv4-only hosts.
_ALWAYS_BLOCKED_IPS = frozenset({
    ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure/DO/Oracle metadata
    ipaddress.ip_address("169.254.170.2"),     # AWS ECS task metadata (task IAM creds)
    ipaddress.ip_address("169.254.169.253"),   # Azure IMDS wire server
    ipaddress.ip_address("fd00:ec2::254"),     # AWS metadata (IPv6)
    ipaddress.ip_address("100.100.100.200"),   # Alibaba Cloud metadata
    ipaddress.ip_address("::ffff:169.254.169.254"),
    ipaddress.ip_address("::ffff:169.254.170.2"),
    ipaddress.ip_address("::ffff:169.254.169.253"),
    ipaddress.ip_address("::ffff:100.100.100.200"),
})
_ALWAYS_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),         # entire link-local range
    ipaddress.ip_network("::ffff:169.254.0.0/112"), # IPv4-mapped link-local range
)

# 100.64.0.0/10 (CGNAT / Shared Address Space, RFC 6598) is NOT covered by
# ipaddress.is_private (returns False for both is_private and is_global).
# Used by carrier-grade NAT, Tailscale/WireGuard VPNs, and cloud internal nets.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def normalize_url_for_request(url: str) -> str:
    """Return an ASCII-safe HTTP(S) URL, preserving existing escapes.

    Browsers and HTTP clients expect URIs, but models often provide IRIs
    such as ``https://wttr.in/Köln``. Non-ASCII host/path/query/fragment
    text is percent-encoded. Non-HTTP URLs are returned unchanged.
    """
    if not isinstance(url, str):
        return url

    raw = url.strip()
    if not raw:
        return raw

    raw = re.sub(r"^([A-Za-z][A-Za-z0-9+.-]*://)\s+", r"\1", raw)

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw

    if parsed.scheme.lower() not in {"http", "https"}:
        return raw

    netloc = parsed.netloc
    hostname = parsed.hostname
    if hostname:
        try:
            ascii_host = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            ascii_host = hostname
        if ascii_host != hostname:
            netloc = netloc.replace(hostname, ascii_host, 1)

    path = quote(parsed.path, safe="/%:@!$&'()*+,;=")
    query = quote(parsed.query, safe="/%:@!$&'()*+,;=?")
    fragment = quote(parsed.fragment, safe="/%:@!$&'()*+,;=?")

    return urlunsplit((parsed.scheme, netloc, path, query, fragment))


# Query parameter names that are unambiguously credential-bearing. Kept
# deliberately narrow: bare English words that double as normal page
# facets (``code``, ``key``, ``auth``, ``session``, ``sig``) are excluded.
_SENSITIVE_QUERY_PARAM_NAMES = frozenset({
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "awsaccesskeyid",
    "client_secret",
    "credential",
    "credentials",
    "jwt",
    "password",
    "passwd",
    "secret",
    "session_id",
    "signature",
    "token",
    "x_amz_security_token",
    "x_amz_signature",
    "x-amz-security-token",
    "x-amz-signature",
})


def sensitive_query_param_name(url: str) -> Optional[str]:
    """Return the first sensitive query parameter name in ``url``, if any.

    Used before handing URLs to third-party extract backends. Catches
    opaque magic links, OAuth codes, and signed URL signatures.
    """
    if not isinstance(url, str) or "?" not in url:
        return None
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.query:
        return None
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if value and unquote(key).lower() in _SENSITIVE_QUERY_PARAM_NAMES:
            return key
    return None


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the IP should be blocked for SSRF protection."""
    # IPv4-mapped IPv6 addresses (``::ffff:x.x.x.x``) are checked by their
    # embedded IPv4 address, not as IPv6.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        embedded = ip.ipv4_mapped
        return (
            embedded.is_private
            or embedded.is_loopback
            or embedded.is_link_local
            or embedded.is_reserved
            or embedded.is_multicast
            or embedded.is_unspecified
            or embedded in _CGNAT_NETWORK
        )

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    if ip.is_multicast or ip.is_unspecified:
        return True
    if ip in _CGNAT_NETWORK:
        return True
    return False


def is_safe_url(url: str) -> bool:
    """Return True if the URL target is not a private/internal address.

    Resolves the hostname to an IP and checks against private ranges.
    Fails closed: DNS errors and unexpected exceptions block the request.
    Cloud metadata endpoints remain blocked regardless.
    """
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
        scheme = (parsed.scheme or "").strip().lower()
        if scheme not in {"http", "https"}:
            logger.warning("[URL] blocked request — unsupported URL scheme: %s", scheme or "<empty>")
            return False
        if not hostname:
            return False
        if hostname in _BLOCKED_HOSTNAMES:
            logger.warning("[URL] blocked request to internal hostname: %s", hostname)
            return False

        try:
            addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            logger.warning("[URL] blocked request — DNS resolution failed for: %s", hostname)
            return False

        for _family, _stype, _proto, _canon, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if "%" in ip_str:
                ip_str = ip_str.split("%", 1)[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                logger.warning(
                    "[URL] blocked request — unparseable IP address %r for hostname %s",
                    sockaddr[0], hostname,
                )
                return False

            if ip in _ALWAYS_BLOCKED_IPS or any(ip in net for net in _ALWAYS_BLOCKED_NETWORKS):
                logger.warning(
                    "[URL] blocked request to cloud metadata address: %s -> %s",
                    hostname, ip_str,
                )
                return False

            if _is_blocked_ip(ip):
                logger.warning(
                    "[URL] blocked request to private/internal address: %s -> %s",
                    hostname, ip_str,
                )
                return False

        return True
    except Exception as exc:  # noqa: BLE001 — fail closed on parsing edge cases
        logger.warning("[URL] blocked request — URL safety check error for %s: %s", url, exc)
        return False
