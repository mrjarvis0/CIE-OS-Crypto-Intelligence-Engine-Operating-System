"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    blockchain

Purpose:
    A01's live connection to chain data -- the network-backed counterpart to
    the pure, offline machinery in ``tools/blockchain``.

Boundary:
    ``tools/blockchain`` holds the codecs and client contracts: ABI encoding,
    address validation, block and log parsing, and the ``*Client`` abstract
    bases with their ``Local*`` stub implementations. None of it touches the
    network, which is why it is safe to import anywhere and trivial to test.

    This package supplies what those contracts were shaped around: endpoint
    selection, transport, rate limiting, caching, and live client
    implementations. Everything that can fail because a remote host failed
    lives here.

Layers:
    providers  -- endpoint catalog and credential resolution
    transport  -- dispatch, rate limiting, caching, health feedback
    clients    -- live implementations of the tools/blockchain contracts

Import policy:
    Submodules are exposed lazily. Importing ``blockchain`` costs nothing and
    performs no I/O; a caller that only needs the provider catalog does not
    pay for the transport stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import rpc

__all__ = ["rpc"]

_LAZY_SUBMODULES = frozenset(__all__)


def __getattr__(name: str) -> Any:
    """Import a submodule on first attribute access."""
    if name in _LAZY_SUBMODULES:
        from importlib import import_module

        module = import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_SUBMODULES)
