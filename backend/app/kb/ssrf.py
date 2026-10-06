"""SSRF guard for outbound calls to user-configured URLs (MCP servers, spec §10.4).

Every URL is checked right before it is used: the host is resolved and *every* address must be
globally routable (no loopback, private, link-local/cloud-metadata, CGNAT, multicast, reserved).
Redirects are never followed by the callers, so a public host cannot bounce us inward.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

Resolver = Callable[[str, int], list[str]]
BLOCKED_HOSTNAMES = frozenset(
    {"localhost", "metadata", "metadata.google.internal", "instance-data", "host.docker.internal"}
)
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa")


class UnsafeUrl(ValueError):
    """The URL is malformed, uses a forbidden scheme, or points at a non-public address."""


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeUrl(f"cannot resolve {host}") from exc
    return sorted({str(i[4][0]) for i in infos})


def is_public_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            return is_public_ip(str(mapped))
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def check_url(
    url: str,
    *,
    allow_http: bool = False,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> str:
    """Validate ``url`` and return it normalised; ``UnsafeUrl`` otherwise."""
    if len(url) > 2048 or any(c.isspace() for c in url):
        raise UnsafeUrl("invalid URL")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrl("invalid URL") from exc
    schemes = ("https", "http") if allow_http else ("https",)
    if parts.scheme not in schemes:
        raise UnsafeUrl("URL must use https")
    if parts.username or parts.password:
        raise UnsafeUrl("credentials in the URL are not allowed; use auth headers")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrl("URL has no host")
    if parts.fragment:
        raise UnsafeUrl("URL must not have a fragment")
    if allow_private:
        return url
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeUrl(f"{host} is an internal host")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addrs = [str(literal)]
    else:
        if "." not in host:
            raise UnsafeUrl(f"{host} is not a public host name")
        default_port = 443 if parts.scheme == "https" else 80
        addrs = (resolver or system_resolver)(host, port or default_port)
    if not addrs:
        raise UnsafeUrl(f"cannot resolve {host}")
    bad = [a for a in addrs if not is_public_ip(a)]
    if bad:
        raise UnsafeUrl(f"{host} resolves to a non-public address")
    return url
