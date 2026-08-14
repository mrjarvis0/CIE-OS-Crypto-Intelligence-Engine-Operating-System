"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    blockchain.rpc.rate_limit

Purpose:
    Keep A01 inside the request budget of the free provider tiers it runs on.

Contents:
    bucket -- per-provider token buckets with 429 feedback
"""

from __future__ import annotations

from .bucket import (
    DEFAULT_PENALTY_SECONDS,
    DEFAULT_SAFETY_FACTOR,
    WINDOW_SECONDS,
    BucketState,
    RateLimiter,
)

__all__ = [
    "RateLimiter",
    "BucketState",
    "WINDOW_SECONDS",
    "DEFAULT_PENALTY_SECONDS",
    "DEFAULT_SAFETY_FACTOR",
]
