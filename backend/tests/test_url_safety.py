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