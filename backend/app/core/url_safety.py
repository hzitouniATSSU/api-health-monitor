import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


def _is_unsafe_ip(ip_string: str) -> bool:
    ip = ipaddress.ip_address(ip_string)

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError("Only HTTP and HTTPS URLs are allowed")

    hostname = parsed.hostname

    if not hostname:
        raise UnsafeURLError("URL must contain a hostname")

    if hostname.lower() == "localhost":
        raise UnsafeURLError("Local addresses are not allowed")

    try:
        addresses = socket.getaddrinfo(
            hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UnsafeURLError("Hostname could not be resolved") from exc

    resolved_ips = {
        address[4][0]
        for address in addresses
    }

    if not resolved_ips:
        raise UnsafeURLError("Hostname could not be resolved")

    for resolved_ip in resolved_ips:
        if _is_unsafe_ip(resolved_ip):
            raise UnsafeURLError(
                "URL resolves to a non-public IP address"
            )