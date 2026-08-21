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
from dataclasses import dataclass
from typing import Optional

from ..utils.paths import is_under

__all__ = [
    "DEFAULT_BLOCKED_HOSTS",
    "IsolationError",
    "IsolationPolicy",
    "SandboxSpec",
    "restrict_path",
    "can_use_capability",
    "host_allowed",
    "restrict_ip",
]


class IsolationError(ValueError):
    """Raised when program attempts to cross an isolation boundary."""


#: Hosts a sandbox may never dial, whatever its allow-list says.
#:
#: The previous default was ``["127.0.0.1", "localhost"]``, which named two
#: spellings of loopback and missed every other one. ``::1`` is loopback,
#: ``0.0.0.0`` routes to local on most stacks, and ``169.254.169.254`` is the
#: cloud instance-metadata endpoint -- the single most valuable SSRF target on
#: a deployed host, and A01 deploys to one.
DEFAULT_BLOCKED_HOSTS: tuple = (
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "localhost",
    "*.localhost",
    "169.254.169.254",
    "metadata.google.internal",
    "metadata",
)


@dataclass(frozen=True)
class IsolationPolicy:
    """
    Declarative description of what sandboxed code may do.

    Frozen, and the sequence fields are normalised to tuples. A policy is
    handed to a sandbox and then consulted repeatedly; when it was a mutable
    dataclass holding mutable lists, anything holding a reference could widen
    it after the decision to trust it had been made, and no reader could tell
    a policy had changed under it.

    Parameters
    ----------
    allowed_capabilities:
        Capability names (schema vocabulary). Empty means deny-all.
    file_roots:
        Absolute directories the tool may read/write. Empty means deny-all.
    hosts:
        Outbound host patterns (``*.example.com``). Empty means deny-outbound
        unless ``allow_any_network`` is set.
    block_hosts:
        Deny-list patterns that always win over ``hosts``.
    """

    allowed_capabilities: tuple = ()
    file_roots: tuple = ()
    hosts: tuple = ()
    block_hosts: tuple = DEFAULT_BLOCKED_HOSTS
    allow_any_network: bool = False
    timeout: Optional[float] = None

    def __post_init__(self) -> None:
        for name in ("allowed_capabilities", "file_roots", "hosts", "block_hosts"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

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


def host_allowed(
    policy: IsolationPolicy, host: str, *, allow_private: bool = False
) -> bool:
    """
    Decision helper: may this sandbox dial ``host``?

    :func:`restrict_ip` is applied here rather than left to the caller.
    The two checks used to be independent functions, and a caller that
    consulted only this one would happily dial ``10.0.0.5`` or
    ``169.254.169.254`` whenever ``allow_any_network`` was set. A guard that
    depends on remembering to call a second guard is not one.
    """
    for blocked in policy.block_hosts:
        if _match_host(blocked, host):
            return False

    if not restrict_ip(host, allow_private=allow_private):
        return False

    if policy.allow_any_network:
        return True
    if not policy.hosts:
        return False
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