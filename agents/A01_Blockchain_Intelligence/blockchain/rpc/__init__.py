"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    blockchain.rpc

Purpose:
    A01's communication layer with blockchain nodes.

Contents:
    providers    -- endpoint catalog and credential resolution
    clients      -- dispatch, execution, caching, provenance
    rate_limit   -- per-provider token buckets
    health_check -- live endpoint probing

Deliberately absent:
    ``load_balancer`` and ``failover`` are named in the A01 blockchain
    architecture but are not implemented here, because they already exist and
    work: ``config.rpc.rpc_manager`` resolves and ranks endpoints, and
    ``config.rpc.fallback`` is a circuit breaker with failure thresholds and
    cooldown. Reimplementing either would put endpoint health in two places
    that disagree, which is worse than having it in the less obvious one.
    ``blockchain.rpc.clients.dispatch`` consumes both.
"""

from __future__ import annotations

from .clients import (
    DEFAULT_MAX_ATTEMPTS,
    EVM_METHOD_VOLATILITY,
    CallResult,
    ChainDispatcher,
    Outcome,
    ResponseCache,
    SpendSink,
    Volatility,
    cache_key,
    resolve_volatility,
    ttl_for,
)
from .rate_limit import RateLimiter

__all__ = [
    # clients
    "ChainDispatcher",
    "CallResult",
    "Outcome",
    "SpendSink",
    "DEFAULT_MAX_ATTEMPTS",
    # cache
    "ResponseCache",
    "Volatility",
    "EVM_METHOD_VOLATILITY",
    "cache_key",
    "resolve_volatility",
    "ttl_for",
    # rate limiting
    "RateLimiter",
]
