
import asyncio
import ipaddress
import socket

import httpcore
from httpcore._backends.auto import AutoBackend

from app.core.url_safety import UnsafeURLError, _is_unsafe_ip


class SafeNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self._backend = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise UnsafeURLError(
                "Hostname could not be resolved"
            ) from exc

        public_ips = []

        for address in addresses:
            ip = address[4][0]

            if _is_unsafe_ip(ip):
                raise UnsafeURLError(
                    "Connection to non-public IP address blocked"
                )

            if ip not in public_ips:
                public_ips.append(ip)

        if not public_ips:
            raise UnsafeURLError(
                "Hostname could not be resolved"
            )

        # Connect using a validated IP, never the original hostname.
        return await self._backend.connect_tcp(
            host=public_ips[0],
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        raise UnsafeURLError("Unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)
