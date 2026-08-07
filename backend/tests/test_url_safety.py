import socket

from agent.tools import url_safety


def _fake_getaddrinfo(ips):
    def fake(hostname, port=None, family=0, socktype=0, protocol=0):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 80))
            for ip in ips
        ]

    return fake


def test_safe_public_url(monkeypatch):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"]))

    assert url_safety.is_safe_url("https://example.com/page") is True


def test_blocks_loopback(monkeypatch):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_getaddrinfo(["127.0.0.1"]))

    assert url_safety.is_safe_url("http://localhost:5000/private") is False
    assert url_safety.is_safe_url("http://127.0.0.1/private") is False


def test_blocks_private_ranges(monkeypatch):
    for ip in ("10.0.0.5", "192.168.1.1", "172.16.0.9", "100.64.0.1", "169.254.169.254", "::1"):
        monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_getaddrinfo([ip]))
        assert url_safety.is_safe_url(f"http://{ip}/") is False, ip


def test_blocks_metadata_hostname(monkeypatch):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_getaddrinfo(["169.254.169.254"]))

    assert url_safety.is_safe_url("http://metadata.google.internal/") is False


def test_blocks_unsupported_scheme():
    assert url_safety.is_safe_url("file:///etc/passwd") is False
    assert url_safety.is_safe_url("ftp://example.com/") is False


def test_fails_closed_on_dns_error(monkeypatch):
    def raise_gaierror(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", raise_gaierror)

    assert url_safety.is_safe_url("https://nonexistent.invalid/") is False


def test_blocks_ipv4_mapped_private(monkeypatch):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_getaddrinfo(["::ffff:10.0.0.5"]))

    assert url_safety.is_safe_url("http://example.com/") is False


def test_normalize_url_for_request_handles_iri():
    assert url_safety.normalize_url_for_request("https://wttr.in/Köln") == "https://wttr.in/K%C3%B6ln"


def test_sensitive_query_param_detection():
    assert url_safety.sensitive_query_param_name("https://example.com/signed?token=abc") == "token"
    assert url_safety.sensitive_query_param_name("https://example.com/?api_key=abc") == "api_key"
    assert url_safety.sensitive_query_param_name("https://example.com/?q=hello") is None
    assert url_safety.sensitive_query_param_name("https://example.com/plain") is None
