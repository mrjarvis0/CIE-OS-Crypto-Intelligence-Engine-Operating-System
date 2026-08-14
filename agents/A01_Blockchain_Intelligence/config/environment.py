"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.environment

Purpose:
    Runtime environment detection and helper utilities.

Responsibilities:
    - Detect runtime environment
    - Validate supported environments
    - Provide helper methods
    - Detect CI / Docker
    - Never load settings
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache


# ==============================================================================
# ENVIRONMENT ENUM
# ==============================================================================

class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


# ==============================================================================
# RUNTIME DETECTION
# ==============================================================================

DEFAULT_ENVIRONMENT = Environment.DEVELOPMENT


@lru_cache(maxsize=1)
def get_environment() -> Environment:
    """
    Return current runtime environment.

    Reads:
        APP_ENV

    Allowed:
        development
        testing
        staging
        production
    """

    value = os.getenv("APP_ENV", DEFAULT_ENVIRONMENT.value).lower()

    try:
        return Environment(value)
    except ValueError as exc:
        raise RuntimeError(
            f"Unsupported environment: {value}"
        ) from exc


# ==============================================================================
# HELPERS
# ==============================================================================

def is_development() -> bool:
    return get_environment() is Environment.DEVELOPMENT


def is_testing() -> bool:
    return get_environment() is Environment.TESTING


def is_staging() -> bool:
    return get_environment() is Environment.STAGING


def is_production() -> bool:
    return get_environment() is Environment.PRODUCTION


# ==============================================================================
# DEBUG
# ==============================================================================

def debug_enabled() -> bool:
    """
    Debug is enabled only in development unless overridden.
    """

    override = os.getenv("DEBUG")

    if override is not None:
        return override.lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    return is_development()


# ==============================================================================
# CI DETECTION
# ==============================================================================

def is_ci() -> bool:
    """
    Detect common CI providers.
    """

    return any(
        os.getenv(name)
        for name in (
            "CI",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "JENKINS_URL",
            "BUILDKITE",
        )
    )


# ==============================================================================
# CONTAINER DETECTION
# ==============================================================================

def is_docker() -> bool:
    """
    Detect Docker runtime.
    """

    if os.path.exists("/.dockerenv"):
        return True

    try:
        with open("/proc/1/cgroup", "rt", encoding="utf-8") as file:
            return "docker" in file.read()
    except OSError:
        return False


# ==============================================================================
# VALIDATION
# ==============================================================================

def validate_environment() -> None:
    """
    Validate environment.

    Raises:
        RuntimeError
    """

    _ = get_environment()


# ==============================================================================
# EXPORTS
# ==============================================================================

__all__ = [
    "Environment",
    "get_environment",
    "is_development",
    "is_testing",
    "is_staging",
    "is_production",
    "debug_enabled",
    "is_ci",
    "is_docker",
    "validate_environment",
]