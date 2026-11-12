import socket

import pytest

from app.core.url_safety import UnsafeURLError, validate_public_url


def fake_dns(ip: str):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (ip, 80),
        )
    ]


@pytest.mark.parametrize(
    "ip",
    ["93.184.216.34", "8.8.8.8", "2606:4700::1111", "2001:4860:4860::8888"],
)
def test_public_ipv4_and_ipv6_addresses_are_allowed(monkeypatch, ip):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: fake_dns(ip),
    )

    validate_public_url("https://example.com")


def test_public_address_is_allowed(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: fake_dns("93.184.216.34"),
    )

    validate_public_url("https://example.com")


@pytest.mark.parametrize(
    "url,ip",
    [
        ("http://127.0.0.1", "127.0.0.1"),
        ("http://10.0.0.1", "10.0.0.1"),
        ("http://192.168.1.1", "192.168.1.1"),
        ("http://172.16.0.1", "172.16.0.1"),
        ("http://169.254.169.254", "169.254.169.254"),
        # Shared address space (RFC 6598): not "private" in Python's
        # classification, but never publicly routable.
        ("http://100.64.0.1", "100.64.0.1"),
        ("http://100.100.100.200", "100.100.100.200"),
    ],
)
def test_private_addresses_are_rejected(monkeypatch, url, ip):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: fake_dns(ip),
    )

    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


def test_localhost_is_rejected():
    with pytest.raises(UnsafeURLError):
        validate_public_url("http://localhost:8000")


def test_non_http_scheme_is_rejected():
    with pytest.raises(UnsafeURLError):
        validate_public_url("ftp://example.com/file")


def test_unresolvable_hostname_is_rejected(monkeypatch):
    def fail_dns(*args, **kwargs):
        raise socket.gaierror()

    monkeypatch.setattr(socket, "getaddrinfo", fail_dns)

    with pytest.raises(UnsafeURLError):
        validate_public_url("https://does-not-exist.example")