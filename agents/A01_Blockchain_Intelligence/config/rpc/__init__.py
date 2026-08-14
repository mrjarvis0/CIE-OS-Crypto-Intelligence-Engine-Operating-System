"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    config.rpc

Purpose:
    RPC configuration package for blockchain endpoint selection and failover.
"""

from __future__ import annotations

from .chains import (
    ChainConfig,
    ChainName,
    ChainRegistry,
    ChainType,
    NativeCurrency,
    DEFAULT_CHAIN_CONFIGS,
    default_registry,
    get_chain,
    get_chain_by_id,
    is_supported_chain,
    is_supported_chain_id,
    supported_chain_ids,
    supported_chain_names,
)
from .fallback import (
    EndpointState,
    FallbackDecision,
    FallbackDecisionResult,
    RpcFallbackManager,
    build_fallback_manager,
)
from .rpc_config import (
    ChainRpcConfig,
    RpcEndpoint,
    RpcHealthStatus,
    RpcRegistry,
    RpcTransport,
    build_default_rpc_registry,
    normalize_rpc_urls,
)
from .rpc_manager import RpcManager, RpcResolution, default_rpc_manager

__all__ = [
    "ChainConfig",
    "ChainName",
    "ChainRegistry",
    "ChainType",
    "NativeCurrency",
    "DEFAULT_CHAIN_CONFIGS",
    "default_registry",
    "get_chain",
    "get_chain_by_id",
    "is_supported_chain",
    "is_supported_chain_id",
    "supported_chain_ids",
    "supported_chain_names",
    "EndpointState",
    "FallbackDecision",
    "FallbackDecisionResult",
    "RpcFallbackManager",
    "build_fallback_manager",
    "ChainRpcConfig",
    "RpcEndpoint",
    "RpcHealthStatus",
    "RpcRegistry",
    "RpcTransport",
    "build_default_rpc_registry",
    "normalize_rpc_urls",
    "RpcManager",
    "RpcResolution",
    "default_rpc_manager",
]
