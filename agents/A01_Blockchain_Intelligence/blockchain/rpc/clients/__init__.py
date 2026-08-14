"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    blockchain.rpc.clients

Purpose:
    Executing a chain read against a chosen endpoint, and caching the answer
    for as long as it stays true.

Contents:
    dispatch -- endpoint selection, execution, health feedback, provenance
    cache    -- TTL cache whose lifetimes follow chain finality

Boundary:
    Endpoint *selection policy* is not here. Load balancing lives in
    ``config.rpc.rpc_manager`` and the failover circuit breaker in
    ``config.rpc.fallback``; both already existed and are consumed rather than
    reimplemented. This package decides how to speak to an endpoint, not which
    endpoint deserves the next request.
"""

from __future__ import annotations

from .cache import (
    EVM_METHOD_VOLATILITY,
    ResponseCache,
    Volatility,
    cache_key,
    resolve_volatility,
    ttl_for,
)
from .dispatch import (
    DEFAULT_MAX_ATTEMPTS,
    CallResult,
    ChainDispatcher,
    Outcome,
    SpendSink,
)

__all__ = [
    "ChainDispatcher",
    "CallResult",
    "Outcome",
    "SpendSink",
    "DEFAULT_MAX_ATTEMPTS",
    "ResponseCache",
    "Volatility",
    "EVM_METHOD_VOLATILITY",
    "cache_key",
    "resolve_volatility",
    "ttl_for",
]
