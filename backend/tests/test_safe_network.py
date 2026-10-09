
import socket
from unittest.mock import AsyncMock

import pytest

from app.core.safe_network import SafeNetworkBackend
from app.core.url_safety import UnsafeURLError


@pytest.mark.anyio
async def test_blocks_private_dns_resolution(monkeypatch):
    backend = SafeNetworkBackend()

    def fake_getaddrinfo(host, port, **kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1", port),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    connect_mock = AsyncMock()
    monkeypatch.setattr(
        backend._backend,
        "connect_tcp",
        connect_mock,
    )

    with pytest.raises(UnsafeURLError):
        await backend.connect_tcp("example.com", 443)

    connect_mock.assert_not_awaited()


@pytest.mark.anyio
async def test_connects_only_to_validated_public_ip(monkeypatch):
    backend = SafeNetworkBackend()

    def fake_getaddrinfo(host, port, **kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.215.14", port),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    connect_mock = AsyncMock()
    monkeypatch.setattr(
        backend._backend,
        "connect_tcp",
        connect_mock,
    )

    await backend.connect_tcp("example.com", 443)

    assert connect_mock.await_args.kwargs["host"] == "93.184.215.14"
    assert connect_mock.await_args.kwargs["port"] == 443


@pytest.mark.anyio
async def test_blocks_mixed_public_and_private_dns(monkeypatch):
    backend = SafeNetworkBackend()

    def fake_getaddrinfo(host, port, **kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.215.14", port),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("10.0.0.5", port),
            ),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    connect_mock = AsyncMock()
    monkeypatch.setattr(
        backend._backend,
        "connect_tcp",
        connect_mock,
    )

    with pytest.raises(UnsafeURLError):
        await backend.connect_tcp("example.com", 443)

    connect_mock.assert_not_awaited()
