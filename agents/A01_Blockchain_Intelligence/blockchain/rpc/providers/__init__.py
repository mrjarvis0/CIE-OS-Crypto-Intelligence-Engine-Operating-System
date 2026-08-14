"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    blockchain.providers

Purpose:
    Where A01 reads chain data from, and what it takes to get in.

Contents:
    keys     -- API key specs and environment resolution
    catalog  -- node, explorer and market endpoints for every supported chain
"""

from __future__ import annotations

from .catalog import (
    ALL_ENDPOINTS,
    DEFAULT_CATALOG,
    Access,
    Endpoint,
    Protocol,
    ProviderCatalog,
    ProviderRole,
    default_catalog,
)
from .keys import (
    ALL_KEY_SPECS,
    ApiKeySpec,
    KeyResolution,
    KeyState,
    configured_providers,
    get_key_spec,
    has_key,
    resolve_all,
    resolve_key,
)

__all__ = [
    # catalog
    "Protocol",
    "Access",
    "ProviderRole",
    "Endpoint",
    "ProviderCatalog",
    "ALL_ENDPOINTS",
    "DEFAULT_CATALOG",
    "default_catalog",
    # keys
    "KeyState",
    "ApiKeySpec",
    "KeyResolution",
    "resolve_key",
    "resolve_all",
    "has_key",
    "get_key_spec",
    "configured_providers",
    "ALL_KEY_SPECS",
]
