"""
CIE-OS
A02 News Intelligence Agent

Module:
    config.environment

Purpose:
    Runtime environment detection.

Design goals:
    - No settings loading
    - Safe to import everywhere
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


DEFAULT_ENVIRONMENT = Environment.DEVELOPMENT


@lru_cache(maxsize=1)
def get_environment() -> Environment:
    """Return current runtime environment from APP_ENV."""

    value = os.getenv("APP_ENV", DEFAULT_ENVIRONMENT.value).lower()
    try:
        return Environment(value)
    except ValueError as exc:
        raise RuntimeError(f"Unsupported environment: {value}") from exc


def is_development() -> bool:
    return get_environment() is Environment.DEVELOPMENT


def is_testing() -> bool:
    return get_environment() is Environment.TESTING


def is_production() -> bool:
    return get_environment() is Environment.PRODUCTION


def debug_enabled() -> bool:
    """Debug is enabled only in development unless overridden."""

    override = os.getenv("DEBUG")
    if override is not None:
        return override.lower() in ("1", "true", "yes", "on")
    return is_development()


__all__ = [
    "Environment",
    "get_environment",
    "is_development",
    "is_testing",
    "is_production",
    "debug_enabled",
]
