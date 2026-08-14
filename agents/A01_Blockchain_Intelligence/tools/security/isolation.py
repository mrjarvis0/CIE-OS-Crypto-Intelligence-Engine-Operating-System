"""
Tools :: Security :: Isolation
==============================

Isolation boundaries for sandboxed code: which capabilities, filesystem roots
and network hosts a tool or plugin may touch.

These helpers are *pure policies*: they decide, they do not enforce. The
plugins layer turns the same :class:`IsolationPolicy` into a subprocess /
container sandbox; the security validator consults it before allowing an
outbound dial. Both share this vocabulary.
"""

from __future__ import annotations

import fnmatch
import ipaddress
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

from ..utils.paths import is_under

__all__ = [
    "IsolationError",
    "IsolationPolicy",
    "restrict_path",
    "can_use_capability",
    "host_allowed",
    "restrict_ip",
]


class IsolationError(ValueError):
    """Raised when program attempts to cross an isolation boundary."""


@dataclass
class IsolationPolicy:
    """
    Declarative description of what sandboxed code "used to" be able to do.

    Parameters
    ----------
    allowed_capabilities:
        Capability names (schema vocabulary). Empty set means deny-all
        capabilities are not automatically granted.
    file_roots:
        Absolute directories the tool may read/write. Empty means deny-all.
    hosts:
        Outbound host patterns (``*.example.com``). Empty means deny-outbound
        unless ``allow_any_network`` is set.
    block_hosts:
        Deny-list patterns that always win over ``hosts``.
    """

    allowed_capabilities: list = field(default_factory=list)
    file_roots: list = field(default_factory=list)
    hosts: list = field(default_factory=list)
    block_hosts: list = field(default_factory=lambda: ["127.0.0.1", "localhost"])
    allow_any_network: bool = False
    timeout: Optional[float] = None

    def allows_capability(self, capability: str) -> bool:
        if not self.allowed_capabilities:
            return False
        return capability in self.allowed_capabilities

    def allows_path(self, path: str) -> bool:
        return any(is_under(path, root) for root in self.file_roots)


class SandboxSpec(IsolationPolicy):
    """Explicit constructor convenience for the plugins layer (same policy)."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)


def can_use_capability(policy: IsolationPolicy, capability: str) -> bool:
    return policy.allows_capability(capability)


def restrict_path(policy: IsolationPolicy, path: str) -> str:
    """
    Return ``path`` untouched when it is allowed, else raise IsolationError.
    """
    if not policy.file_roots:
        raise IsolationError("no filesystem access permitted")
    if policy.allows_path(path):
        return path
    raise IsolationError(f"path outside allowed roots: {path}")


def _match_host(pattern: str, host: str) -> bool:
    pattern = pattern.lower()
    host = host.lower()
    return (
        fnmatch.fnmatchcase(host, pattern)
        or pattern == host
        or (pattern.startswith("*.") and host.endswith(pattern[1:]))
    )


def host_allowed(policy: IsolationPolicy, host: str) -> bool:
    """Decision helper: may this sandbox dial ``host``?"""
    for blocked in policy.block_hosts:
        if _match_host(blocked, host):
            return False
    if not policy.hosts and not policy.allow_any_network:
        return False
    if policy.allow_any_network:
        return True
    return any(_match_host(allowed, host) for allowed in policy.hosts)


def restrict_ip(host: str, *, allow_private: bool = False) -> bool:
    """
    Guard for outbound dials: reject loopback/private/link-local literals
    unless explicitly permitted. Returns True when the host is allowed to
    connect, False when it is blocked. Hostnames are not analyzed here.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # not an IP literal -- passed on to host_policy checks
    if not allow_private and (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved):
        return False
    return True