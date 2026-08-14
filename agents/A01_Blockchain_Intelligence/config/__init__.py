"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    config

Purpose:
    Configuration layer for the A01 Blockchain Intelligence Agent.

Subpackages
-----------
config.providers
    External data-provider configuration (Etherscan, CoinGecko, DefiLlama, ...).
config.rpc
    Blockchain RPC endpoint registry, selection and failover.
config.security
    API key handling, secret resolution and input validation.

Modules
-------
cache, constants, environment, feature_flags, logging, paths, settings

Notes
-----
This package intentionally performs no eager submodule imports. Several config
modules read the environment and build registries at import time, so importing
them lazily keeps ``import config`` cheap and free of import cycles. Import the
module you need directly, e.g.::

    from config.settings import Settings
    from config.rpc import RpcManager
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "CIE-OS"
__package_name__ = "config"

__all__ = [
    "__version__",
    "__author__",
    "__package_name__",
]
